"""Tests del cliente. Sin red: los controles se prueban con dobles."""

import contextlib
import re
import urllib.parse
from pathlib import Path

import httpx
import pytest

from mcp_pjud import client
from mcp_pjud.client import (
    BASE,
    INTERVALO_MINIMO,
    MODULOS,
    RAFAGA_MAXIMA,
    PjudBloqueado,
    PjudClient,
)
from mcp_pjud.parser import COMPETENCIAS, EstructuraInesperada, parse_resultados

FIXTURES = Path(__file__).parent / "fixtures"


def _cliente(respuesta: httpx.Response) -> PjudClient:
    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(lambda _: respuesta))
    return c


# -- cláusula CUARTA: no sobrecargar -------------------------------------------


def test_no_se_puede_bajar_el_intervalo_minimo():
    """El intervalo implementa la prohibición de sobrecargar el portal.
    Es un límite, no una preferencia configurable."""
    with pytest.raises(ValueError, match="CUARTA"):
        PjudClient("test@example.cl", intervalo=0.1)


def _reloj(monkeypatch, dormido):
    """Reloj falso que avanza sólo cuando el código duerme, para medir el ritmo real."""
    ahora = [1000.0]
    monkeypatch.setattr("mcp_pjud.client.time.monotonic", lambda: ahora[0])

    def dormir(segundos):
        dormido.append(segundos)
        ahora[0] += segundos

    monkeypatch.setattr("mcp_pjud.client.time.sleep", dormir)
    return ahora


def test_la_rafaga_inicial_sale_sin_esperar(monkeypatch):
    """Una consulta de actuaciones son cinco peticiones encadenadas para responder una sola
    pregunta. Con intervalo plano tardaba veinticinco segundos."""
    dormido = []
    _reloj(monkeypatch, dormido)
    monkeypatch.setattr("mcp_pjud.client._FICHAS", float(RAFAGA_MAXIMA))
    monkeypatch.setattr("mcp_pjud.client._ULTIMA", 1000.0)

    c = PjudClient("test@example.cl")
    for _ in range(RAFAGA_MAXIMA):
        c._esperar()

    assert dormido == [], f"la ráfaga de {RAFAGA_MAXIMA} no debía esperar"


def test_agotada_la_rafaga_manda_el_intervalo(monkeypatch):
    dormido = []
    _reloj(monkeypatch, dormido)
    monkeypatch.setattr("mcp_pjud.client._FICHAS", float(RAFAGA_MAXIMA))
    monkeypatch.setattr("mcp_pjud.client._ULTIMA", 1000.0)

    c = PjudClient("test@example.cl")
    for _ in range(RAFAGA_MAXIMA + 1):
        c._esperar()

    assert dormido == [pytest.approx(INTERVALO_MINIMO)], (
        "la petición siguiente a la ráfaga tiene que esperar el intervalo completo"
    )


def test_la_rafaga_esta_acotada():
    """El tope de la ráfaga es lo único que separa esto de no tener control de ritmo.

    Los tests de abajo dimensionan sus bucles con esta constante, así que crecen con ella y
    no pueden detectar que crezca: con una ráfaga de diez mil, todos siguen verdes y el
    régimen sostenido deja de existir. Ese piso lo pone este test y nada más.

    Cinco es el largo de la cadena más larga que hace el cliente, o sea alcanza para que una
    pregunta se responda de una vez y no para barrer.
    """
    assert RAFAGA_MAXIMA <= 5, (
        f"La ráfaga es de {RAFAGA_MAXIMA}. Por encima de la cadena más larga deja de ser "
        "'responder una pregunta sin esperas' y pasa a ser un permiso para barrer."
    )


def test_el_ritmo_sostenido_no_supera_una_peticion_por_intervalo(monkeypatch):
    """Lo que la cláusula CUARTA exige es el régimen, no la forma de las primeras.

    Se mide sobre bastantes peticiones: la ráfaga se amortiza y lo que queda es la tasa.
    """
    dormido = []
    ahora = _reloj(monkeypatch, dormido)
    monkeypatch.setattr("mcp_pjud.client._FICHAS", float(RAFAGA_MAXIMA))
    monkeypatch.setattr("mcp_pjud.client._ULTIMA", 1000.0)
    inicio = ahora[0]

    c = PjudClient("test@example.cl")
    peticiones = 40
    for _ in range(peticiones):
        c._esperar()
        # El reloj de recarga se mueve al terminar cada petición, como hace `_req`.
        monkeypatch.setattr("mcp_pjud.client._ULTIMA", ahora[0])

    transcurrido = ahora[0] - inicio
    minimo = (peticiones - RAFAGA_MAXIMA) * INTERVALO_MINIMO
    assert transcurrido >= minimo, (
        f"{peticiones} peticiones tomaron {transcurrido}s y el régimen exige al menos "
        f"{minimo}s una vez agotada la ráfaga"
    )


def test_el_balde_no_se_recarga_al_abrir_un_cliente_nuevo(monkeypatch):
    """`server.py` abre un cliente por llamada de herramienta. Si el balde fuera de la
    instancia, cada herramienta llegaría con la ráfaga entera y el régimen no existiría."""
    dormido = []
    _reloj(monkeypatch, dormido)
    monkeypatch.setattr("mcp_pjud.client._FICHAS", 0.0)
    monkeypatch.setattr("mcp_pjud.client._ULTIMA", 1000.0)

    PjudClient("test@example.cl")._esperar()  # cliente recién creado

    assert dormido == [pytest.approx(INTERVALO_MINIMO)], (
        "un cliente nuevo no puede llegar con fichas que el proceso ya gastó"
    )


# -- detención total: sin reintento, sin evasión --------------------------------


@pytest.mark.parametrize("codigo", [403, 429])
def test_403_y_429_detienen_sin_reintentar(codigo, monkeypatch):
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    llamadas = []

    def transporte(req):
        llamadas.append(req.url)
        return httpx.Response(codigo, text="bloqueado")

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    with pytest.raises(PjudBloqueado, match=str(codigo)):
        c._req("GET", "https://oficinajudicialvirtual.pjud.cl/x")
    assert len(llamadas) == 1, "no debe reintentar"


@pytest.mark.parametrize("codigo", [403, 429])
def test_el_bloqueo_detiene_tambien_al_resto_del_proceso(codigo, monkeypatch):
    """La detención es del portal, no de la llamada que se topó con él.

    `server.py` abre un cliente por herramienta y el cliente MCP puede llamar a dos a la
    vez. Si el bloqueo quedara guardado en la instancia, la segunda esperaría su turno y
    consultaría igual cuando la primera ya recibió el rechazo: reintentar por el lado.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    llamadas = []

    def transporte(req):
        llamadas.append(req.url)
        return httpx.Response(codigo, text="bloqueado")

    primero = PjudClient("test@example.cl")
    primero._http = httpx.Client(transport=httpx.MockTransport(transporte))
    with pytest.raises(PjudBloqueado):
        primero._req("GET", "https://oficinajudicialvirtual.pjud.cl/x")

    # Cliente distinto, como el que abriría la herramienta siguiente.
    segundo = PjudClient("test@example.cl")
    segundo._http = httpx.Client(transport=httpx.MockTransport(transporte))
    with pytest.raises(PjudBloqueado, match=str(codigo)):
        segundo._req("GET", "https://oficinajudicialvirtual.pjud.cl/y")

    assert len(llamadas) == 1, "tras el bloqueo no debe salir ninguna petición más"


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadError("[Errno 104] Connection reset by peer"),
        httpx.ConnectError("connection refused"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
)
def test_un_corte_de_conexion_detiene_igual_que_un_403(error, monkeypatch):
    """Un cortafuegos que rechaza a nivel de red no manda un 403: corta la conexión.

    Reportado en la incidencia #34, con un reset saliendo desde Canadá. `httpx.ReadError`
    hereda de `TransportError` y se propagaba como error de red sin tocar `_BLOQUEADO`, así
    que quien envolviera las llamadas en un reintento seguía golpeando un cortafuegos que ya
    lo había rechazado. Eso es exactamente lo que convierte un bloqueo temporal en una IP
    baneada.

    Y la petición que recibió el corte igual salió a la red, así que sigue en la bitácora:
    el registro existe para acreditar cuánto se consultó, no cuánto se respondió.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    salieron = []

    def transporte(req):
        salieron.append(str(req.url))
        raise error

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    with pytest.raises(PjudBloqueado, match=type(error).__name__):
        c._req("GET", "https://oficinajudicialvirtual.pjud.cl/consultaUnificada.php")
    assert c.bitacora[-1][2] == 0, "la petición cortada tiene que quedar en la bitácora"

    # Y detiene al proceso entero, igual que el 403: otro cliente, otro host.
    otro = PjudClient("test@example.cl")
    otro._http = httpx.Client(transport=httpx.MockTransport(transporte))
    with pytest.raises(PjudBloqueado):
        otro._req("GET", "https://juris.pjud.cl/busqueda/buscar_sentencias")

    assert len(salieron) == 1, "tras el corte no debe salir ninguna petición más"


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("timed out"),
        httpx.ConnectTimeout("timed out"),
        httpx.PoolTimeout("timed out"),
    ],
)
def test_un_timeout_no_detiene_el_proceso(error, monkeypatch):
    """Éste es el contrapeso del de arriba, y es el que decide dónde va el corte.

    `TimeoutException` hereda de `TransportError`, así que capturar `TransportError` entero,
    que es lo primero que uno escribe, dejaría el servidor detenido por una consulta lenta.
    Y está medido que lo son: una búsqueda en el buscador de fallos tardó 177 segundos. Sería
    negarse el servicio a uno mismo, no cuidar la plataforma.

    Sin este test, alguien "simplifica" el `isinstance` a `TransportError` y la suite entera
    sigue verde.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)

    def transporte(req):
        raise error

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    with pytest.raises(httpx.TimeoutException):
        c._req("GET", "https://juris.pjud.cl/busqueda/buscar_sentencias")
    assert client._BLOQUEADO is None, "un timeout no es un rechazo y no puede detener el proceso"


def test_un_desafio_de_f5_con_200_detiene_en_la_peticion_que_lo_trae(monkeypatch):
    """El cortafuegos también rechaza con HTTP 200: manda su desafío en vez de la página.

    Reportado en la incidencia #34. El 200 se tomaba por bueno y el fallo aparecía recién en
    la petición SIGUIENTE, un paso más allá de la causa real. `_SENAL_CAPTCHA` no lo ve
    porque busca palabras en un aviso de la aplicación, y esto viene antes de la aplicación.

    No se resuelve el desafío: ejecutarlo es sortear un control anti-automatización, que es
    justo lo que `ACCEPTABLE_USE.md` pide no hacer.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    salieron = []
    desafio = (
        '<APM_DO_NOT_TOUCH>\n<script type="text/javascript">\n'
        "(function(){ window.sWvc=!!window.sWvc; })();\n</script>"
    )

    def transporte(req):
        salieron.append(str(req.url))
        return httpx.Response(200, text=desafio)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    with pytest.raises(PjudBloqueado, match="F5 BIG-IP APM"):
        c._req("GET", f"{BASE}/includes/sesion-consultaunificada.php")

    assert len(salieron) == 1, "el desafío tiene que detener en la petición que lo trae"


def test_la_secuencia_reportada_en_la_incidencia_34_se_detiene_en_la_primera(monkeypatch):
    """La incidencia reporta la secuencia entera, y el punto es dónde había que parar.

    La petición 1, el GET a `sesion-consultaunificada.php`, devolvía **HTTP 200**, y quien
    la recibía la tomaba por buena porque el código de estado decía que sí. La petición 2,
    el GET a `consultaUnificada.php`, moría con `Connection reset by peer` en el cortafuegos,
    antes de llegar a la aplicación.

    Con eso, el traceback culpaba a `abrir_sesion` de no poder derivar el prefijo, un paso
    más allá de la causa real, que ya estaba servida en la respuesta anterior. Es la misma
    forma de diagnóstico equivocado que este proyecto ya pagó caro con los timeouts.

    Acá se reproduce completa, con el cuerpo del desafío guardado como fixture, y se exige
    que la petición 2 **no salga**: el desafío detiene en la que lo trae.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    desafio = (FIXTURES / "desafio_f5_apm.html").read_text(encoding="utf-8")
    salieron = []

    def transporte(req):
        salieron.append(str(req.url))
        if "sesion-consultaunificada" in str(req.url):
            return httpx.Response(200, text=desafio)
        raise httpx.ReadError("[Errno 104] Connection reset by peer")

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    with pytest.raises(PjudBloqueado, match="F5 BIG-IP APM"):
        c.abrir_sesion()

    assert len(salieron) == 1, (
        f"la segunda petición no debe salir: el desafío ya rechazó a esta IP. Salieron {salieron}"
    )


def test_un_bloqueo_en_un_host_detiene_tambien_al_otro(monkeypatch):
    """La detención es del proceso, no del host que bloqueó.

    Se evaluó llevarla por host, para que un bloqueo consultando jurisprudencia no dejara sin
    consulta de causas a quien tiene un plazo corriendo. Se descartó al medir quién bloquea:
    los dos hosts responden con la cookie `TS<hex>` de F5 BIG-IP, o sea están detrás del mismo
    cortafuegos y el 403 llega antes de la aplicación. Seguir consultando el otro después de
    un rechazo es lo que convierte un bloqueo temporal en una IP baneada.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    salieron = []

    def transporte(req):
        salieron.append(str(req.url))
        return httpx.Response(403 if "juris" in str(req.url) else 200, text="ok")

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    with pytest.raises(PjudBloqueado):
        c._req("GET", "https://juris.pjud.cl/busqueda/buscar_sentencias")

    with pytest.raises(PjudBloqueado, match="mismo cortafuegos"):
        c._req("GET", "https://oficinajudicialvirtual.pjud.cl/consultaUnificada.php")

    assert len(salieron) == 1, "tras el bloqueo no debe salir ninguna petición, ni a otro host"


def test_sesion_sin_prefijo_derivable_se_detiene(monkeypatch):
    """Si el sitio cambia y ya no se puede derivar el prefijo, detenerse.
    Consultar rutas que ya no existen produciría falsos negativos."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _cliente(httpx.Response(200, text="<html>rediseñado</html>"))
    with pytest.raises(PjudBloqueado, match="prefijo"):
        c.abrir_sesion()


def test_competencia_que_no_existe_se_rechaza():
    c = PjudClient("test@example.cl")
    with pytest.raises(ValueError, match="no existe"):
        c._modulo("familia")


def test_competencia_que_existe_pero_no_se_verifico_se_rechaza(monkeypatch):
    """Saber leer una competencia y haberla probado son cosas distintas.

    `parser.COMPETENCIAS` sabe leer las seis; `MODULOS` dice cuáles se midieron. Exponer la
    primera lista como si fuera la segunda es adivinar, y una consulta mal armada devuelve
    vacío, que se lee como que la causa no existe.

    Al verificarse suprema y apelaciones las seis quedaron en `MODULOS`, así que no hay
    ninguna competencia real que ejercite este camino y el guardia quedó inalcanzable. Antes
    esto se resolvía reapuntando el test a la siguiente competencia sin verificar, y se acabó
    la fila. Se saca una de `MODULOS` a propósito: un guardia que no puede fallar imprime
    exactamente lo mismo que uno que pasa, y la próxima vez que alguien agregue una
    competencia sin medirla no habría nada que lo detuviera.
    """
    monkeypatch.setattr("mcp_pjud.client.MODULOS", MODULOS - {"cobranza"})
    c = PjudClient("test@example.cl")
    assert "cobranza" in COMPETENCIAS, "el parser tiene que seguir sabiendo leerla"
    with pytest.raises(ValueError, match="no verificada"):
        c._modulo("cobranza")


def test_toda_peticion_queda_en_bitacora(monkeypatch):
    """§8: registrar cada consulta para poder acreditar uso razonable."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _cliente(httpx.Response(200, text="ok"))
    c._req("GET", "https://oficinajudicialvirtual.pjud.cl/a")
    c._req("GET", "https://oficinajudicialvirtual.pjud.cl/b")
    assert [u for _, u, _ in c.bitacora] == [
        "https://oficinajudicialvirtual.pjud.cl/a",
        "https://oficinajudicialvirtual.pjud.cl/b",
    ]
    assert all(estado == 200 for *_, estado in c.bitacora)


# -- listado de resultados ------------------------------------------------------


def test_parse_resultados_extrae_la_causa_y_su_referencia():
    causas = parse_resultados((FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8"))
    assert len(causas) == 1
    c = causas[0]
    assert c.rol == "E-468-2026"
    assert c.tribunal == "3º Juzgado Civil de Concepción"
    assert c.caratulado.startswith("BANCO DE CHILE")
    # Valor exacto, no sólo que exista. Una extracción truncada o del enlace equivocado
    # devolvería algo no vacío que igual se enviaría como dtaCausa, y el test pasaría sin
    # proteger lo que su nombre anuncia. La fixture trae una referencia ficticia estable.
    assert c.referencia == "referencia-ficticia-001"


def test_recorre_todos_los_cuadernos(monkeypatch):
    """Si la causa tiene cuaderno de apremio, hay que leerlo también.

    Devolver sólo el cuaderno que el sitio despliega por defecto produce una respuesta
    que parece completa y omite el requerimiento de pago y el embargo.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    apremio = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")
    listado = (FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8")

    pedidos: list[str] = []

    def transporte(req: httpx.Request) -> httpx.Response:
        cuerpo = req.content.decode()
        if "consultaRit" in str(req.url):
            return httpx.Response(200, text=listado)
        pedidos.append(cuerpo)
        # El segundo cuaderno se pide con la referencia que trae el select del primero.
        return httpx.Response(200, text=apremio if len(pedidos) > 2 else principal)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    # El listado es la fixture real de civil, cuyo rol es E-468-2026: se pide ése, porque
    # ahora la causa que se abre tiene que corresponder a la pedida.
    acts = c.actuaciones_receptor("E", 468, 2026, tribunal=162)
    cuadernos = {a.cuaderno for a in acts}
    assert cuadernos == {"1 - Principal", "2 - Apremio Ejecutivo Obligación de Dar"}
    assert any("EMBARGO" in a.desc_tramite for a in acts)


def test_sin_resultados_devuelve_lista_vacia_sin_reventar():
    sin_coincidencias = (
        "<tr><td colspan='8'>No se han encontrado resultados con los datos ingresados.</td></tr>"
    )
    assert parse_resultados(sin_coincidencias) == []


def test_listado_irreconocible_levanta_excepcion():
    """Ni filas ni el mensaje conocido: hay que enterarse, no devolver vacío."""
    with pytest.raises(EstructuraInesperada):
        parse_resultados("<tr><td>algo totalmente distinto</td></tr>")


# -- validación de campos, medida contra el sistema real -------------------------
#
# La plataforma no responde con un código de error cuando faltan campos: devuelve HTTP 200
# con un aviso dentro de un <script>. Validar antes evita gastar una petición y evita que
# ese aviso llegue disfrazado de resultado.


def _sin_red() -> PjudClient:
    c = PjudClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("no debía consultar"))
    )
    c._adir, c._token = "ADIR_1", "0" * 32
    return c


def test_rit_exige_rol_y_anio():
    c = _sin_red()
    with pytest.raises(ValueError, match="rol y año"):
        c.buscar_por_rit("C", 0, 2026)
    with pytest.raises(ValueError, match="rol y año"):
        c.buscar_por_rit("C", 1156, 0)


def test_nombre_exige_dos_campos_de_nombre():
    """El año no cuenta para el mínimo de dos.

    Medido: "apellido paterno + año" es rechazado por la plataforma, "paterno + materno"
    es aceptado.
    """
    c = _sin_red()
    with pytest.raises(ValueError, match="al menos dos"):
        c.buscar_por_nombre(apellido_paterno="PEREZ", tribunal=162)
    with pytest.raises(ValueError, match="al menos dos"):
        c.buscar_por_nombre(apellido_paterno="PEREZ", anio=2026, tribunal=162)


def test_nombre_exige_tribunal():
    """Limitación del sitio, no del cliente: no se puede buscar por nombre en todos los
    tribunales a la vez."""
    c = _sin_red()
    with pytest.raises(ValueError, match="tribunal"):
        c.buscar_por_nombre(nombre="JUAN", apellido_paterno="PEREZ")


def test_juridica_exige_digito_verificador_y_tribunal():
    c = _sin_red()
    with pytest.raises(ValueError, match="dígito verificador"):
        c.buscar_por_rut_juridica(76406172, "", tribunal=163)
    with pytest.raises(ValueError, match="tribunal"):
        c.buscar_por_rut_juridica(76406172, "1")


def test_fecha_exige_rango_completo_y_tribunal():
    c = _sin_red()
    with pytest.raises(ValueError, match="fecha inicial y fecha final"):
        c.buscar_por_fecha("04/03/2026", "", tribunal=162)
    with pytest.raises(ValueError, match="tribunal"):
        c.buscar_por_fecha("04/03/2026", "04/03/2026")


def test_el_aviso_de_la_plataforma_no_se_devuelve_como_resultado():
    """Sin esto, el aviso llegaría al usuario como estructura rota o como lista vacía."""
    from mcp_pjud.parser import PlataformaRechaza

    aviso = '<script>swal("","Por favor ingresar Rol para la b\\\\u00fasqueda","warning");</script>'
    with pytest.raises(PlataformaRechaza, match="Rol"):
        parse_resultados(aviso)


@pytest.mark.parametrize(
    "aviso",
    [
        "Por favor complete el captcha para continuar",
        "Error de reCAPTCHA, intente nuevamente",
        "Marque la casilla No soy un robot",
        "Falló la verificación de seguridad",
    ],
)
def test_un_aviso_de_captcha_detiene_en_vez_de_pedir_corregir(aviso, monkeypatch):
    """Un captcha llega como aviso con HTTP 200, no como código de error.

    Sin distinguirlo quedaría clasificado como "corrige los parámetros", el usuario
    reintentaría, y eso es justo lo que la regla de detención total prohíbe.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    cuerpo = f'<script>swal("","{aviso}","warning");</script>'
    c = _cliente(httpx.Response(200, text=cuerpo))
    with pytest.raises(PjudBloqueado, match="Detención total"):
        c._req("GET", "https://oficinajudicialvirtual.pjud.cl/x")


def test_un_aviso_de_validacion_no_se_confunde_con_un_bloqueo(monkeypatch):
    """El otro lado del mismo guardia: faltar un campo no es un bloqueo."""
    from mcp_pjud.parser import PlataformaRechaza

    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    cuerpo = '<script>swal("","Por favor ingresar Rol para la búsqueda","warning");</script>'
    c = _cliente(httpx.Response(200, text=cuerpo))
    c._req("GET", "https://oficinajudicialvirtual.pjud.cl/x")  # no debe levantar
    with pytest.raises(PlataformaRechaza, match="Rol"):
        parse_resultados(cuerpo)


# -- paginación ------------------------------------------------------------------
#
# La plataforma pagina con un identificador opaco, no con un número: el control de
# "siguiente" trae el token de la página que viene. Medido contra el sistema real: 251
# resultados en tres páginas de 100, 100 y 51, y la tercera sin control de siguiente.
#
# Los bloques de navegación de las fixtures son REALES, capturados de esas tres páginas.
# Las filas de resultado que arma `_pagina()` son sintéticas y auto-consistentes: sirven
# para ejercitar el recorrido, no para representar un listado de la plataforma.

NAV_INTERMEDIA = (FIXTURES / "nav_pagina_intermedia.html").read_text(encoding="utf-8")
NAV_ULTIMA = (FIXTURES / "nav_ultima_pagina.html").read_text(encoding="utf-8")


def _fila(n: int, celdas: int = 5) -> str:
    """Una fila del listado. `celdas` la ensancha para las competencias con más columnas.

    Suprema declara columnas hasta la 6 y apelaciones hasta la 7, así que la fila de cinco
    celdas de civil las hace levantar `EstructuraInesperada`, que es exactamente lo que el
    parser debe hacer. Se rellena con celdas vacías en vez de escribir una fila por
    competencia: lo que estos tests miden no es el contenido de las columnas de más.
    """
    relleno = "<td></td>" * max(0, celdas - 5)
    return (
        f"<tr><td align='center'><a onClick=\"detalleCausaCivil('ref-{n:03d}')\">"
        f"</a></td><td nowrap>C-{9000 + n}-2026</td><td>01/03/2026</td>"
        f"<td>PARTE FICTICIA/CONTRAPARTE FICTICIA</td>"
        f"<td nowrap>2º Juzgado Civil de Concepción</td>{relleno}</tr>"
    )


def _pagina(filas: range, total: int, ultima: bool, token: str = "", celdas: int = 5) -> str:
    """Una página sintética con el bloque de navegación real que corresponda.

    `token` distingue el identificador de "siguiente" entre páginas. Sin eso, dos páginas
    consecutivas ofrecen el mismo y el cliente lo detecta como paginación que no avanza,
    que es justo lo que debe hacer.
    """
    nav = NAV_ULTIMA if ultima else NAV_INTERMEDIA
    # El bloque capturado trae el total real de aquel listado (251). Se quita para que la
    # página sintética declare el suyo: que venga incluido confirma, de paso, que la
    # plataforma siempre lo publica junto a la navegación.
    nav = re.sub(r"<div[^>]*>\s*Total de registros:.*?</div>", "", nav, flags=re.S)
    if token:
        nav = re.sub(r"paginaFecSig\('[^']+'", f"paginaFecSig('{token}'", nav)
    cuerpo = "".join(_fila(n, celdas) for n in filas)
    return (
        f"{cuerpo}<tr><td colspan='5'><div>Total de registros: <b>{total}</b></div>{nav}</td></tr>"
    )


def test_lee_el_control_de_siguiente_de_una_pagina_real():
    """Contra el bloque de navegación capturado de la página 2 de un listado de 251."""
    from mcp_pjud.parser import siguiente_pagina

    assert siguiente_pagina(NAV_INTERMEDIA)


def test_la_ultima_pagina_real_no_ofrece_siguiente():
    """Contra el bloque capturado de la página 3, la última de ese mismo listado."""
    from mcp_pjud.parser import siguiente_pagina

    assert siguiente_pagina(NAV_ULTIMA) is None


def test_total_declarado_tolera_las_formas_que_usa_la_plataforma():
    """La versión anterior sólo leía `<b>7</b>` exacto.

    Con separador de miles devolvía None, y como el guardia se saltaba cuando el total era
    desconocido, se desactivaba solo justo a partir de mil registros.
    """
    from mcp_pjud.parser import total_declarado

    assert total_declarado("Total de registros: <b>7</b>") == 7
    assert total_declarado("Total de registros: <b>1.234</b>") == 1234
    assert total_declarado("Total de registros: <b>12,345</b>") == 12345
    assert total_declarado('Total de registros: <b class="x">7</b>') == 7
    assert total_declarado("Total de registros:&nbsp;<b>7</b>") == 7
    assert total_declarado("<div>otra cosa</div>") is None


def _cliente_con(paginas: list[str]) -> PjudClient:
    entregadas = []

    def transporte(_req: httpx.Request) -> httpx.Response:
        i = min(len(entregadas), len(paginas) - 1)
        entregadas.append(i)
        return httpx.Response(200, text=paginas[i])

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32
    return c


def test_recorre_las_paginas_y_acumula(monkeypatch):
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _cliente_con(
        [
            _pagina(range(1, 4), total=7, ultima=False, token="p2"),
            _pagina(range(4, 7), total=7, ultima=False, token="p3"),
            _pagina(range(7, 8), total=7, ultima=True),
        ]
    )
    causas = c.buscar_por_rit("C", 1156, 2026)
    assert len(causas) == 7
    assert len({x.rol for x in causas}) == 7


def test_una_sola_pagina_no_pide_mas(monkeypatch):
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _cliente_con([_pagina(range(1, 4), total=3, ultima=True)])
    assert len(c.buscar_por_rit("C", 1156, 2026)) == 3


def test_lista_parcial_levanta_en_vez_de_pasar_por_completa(monkeypatch):
    """El control de "siguiente" puede faltar porque se acabaron las páginas, o porque la
    respuesta vino truncada. La plataforma declara el total, así que se comprueba."""
    from mcp_pjud.parser import EstructuraInesperada

    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _cliente_con([_pagina(range(1, 4), total=7, ultima=True)])
    with pytest.raises(EstructuraInesperada, match="declaró 7 resultados"):
        c.buscar_por_rit("C", 1156, 2026)


def test_sin_total_declarado_levanta(monkeypatch):
    """Ambos listados de la plataforma traen el total; su ausencia es cambio de estructura.

    Antes se seguía sin comprobar nada, o sea el guardia se apagaba solo."""
    from mcp_pjud.parser import EstructuraInesperada

    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    sin_total = re.sub(
        r"<div>Total de registros:.*?</div>",
        "<div>sin total</div>",
        _pagina(range(1, 4), total=3, ultima=True),
    )
    c = _cliente_con([sin_total])
    with pytest.raises(EstructuraInesperada, match="no declara el total"):
        c.buscar_por_rit("C", 1156, 2026)


def test_una_paginacion_que_no_avanza_se_detecta_de_inmediato(monkeypatch):
    """Antes se gastaban las diez páginas del tope acumulando duplicados, y el mensaje
    final culpaba al usuario por hacer una búsqueda amplia."""
    from mcp_pjud.parser import EstructuraInesperada

    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    repetida = _pagina(range(1, 4), total=99, ultima=False)
    c = _cliente_con([repetida])
    with pytest.raises(EstructuraInesperada, match="no está avanzando"):
        c.buscar_por_rit("C", 1156, 2026)
    # Se detiene en la segunda vuelta, no al agotar el tope de diez.
    assert len(c.bitacora) == 2


def test_el_tope_de_paginas_levanta_en_vez_de_recortar(monkeypatch):
    """Una lista recortada en silencio se leería como "no hay más resultados"."""
    from mcp_pjud.client import ResultadosTruncados

    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    # Cada página trae un token distinto, así que la paginación sí avanza.
    paginas = [
        _pagina(range(i * 3 + 1, i * 3 + 4), total=999, ultima=False, token=f"p{i}")
        for i in range(4)
    ]
    c = _cliente_con(paginas)
    with pytest.raises(ResultadosTruncados, match="tope de 3 páginas"):
        c.buscar_por_rit("C", 1156, 2026, paginas=3)


@pytest.mark.parametrize("paginas", [0, -1])
def test_un_tope_de_paginas_invalido_no_devuelve_lista_vacia(paginas):
    """Un error de configuración no debe disfrazarse de "no hay causas"."""
    c = _sin_red()
    with pytest.raises(ValueError, match="1 o más"):
        c.buscar_por_rit("C", 1156, 2026, paginas=paginas)


def test_las_actuaciones_no_recorren_todo_el_listado(monkeypatch):
    """El listado se pide UNA vez, aunque declare más páginas.

    Recorrer hasta el tope gastaría hasta nueve peticiones y cuarenta y cinco segundos contra
    la plataforma para descartarlas. El ritmo de consulta no es un parámetro de rendimiento.

    El título de antes decía "sólo se usa la primera causa", y esa parte dejó de ser cierta a
    propósito: tomar la primera entregaba la historia de otra causa cuando el rol se repite
    entre libros. Lo que este test cuida es la cantidad de peticiones, no cuál se elige.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    peticiones = []

    def transporte(req: httpx.Request) -> httpx.Response:
        peticiones.append(str(req.url))
        if "consultaRit" in str(req.url):
            # Un listado con más páginas: si paginara, pediría varias.
            return httpx.Response(200, text=_pagina(range(1, 4), total=99, ultima=False))
        return httpx.Response(200, text=principal)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    # Se pide el rol que la primera fila sintética declara, para que la elección sea
    # inequívoca: lo que se mide acá es cuántas veces se pide el listado.
    c.actuaciones_receptor("C", 9001, 2026, tribunal=162)
    listados = [u for u in peticiones if "consultaRit" in u]
    assert len(listados) == 1, "el listado debe pedirse una sola vez"


def test_una_busqueda_sin_coincidencias_devuelve_vacio_y_no_levanta(monkeypatch):
    """La respuesta de "sin resultados" viene sin navegación y sin total declarado.

    Exigirle esos datos convertía una búsqueda legítima sin coincidencias en un error de
    estructura: el error contrario al falso negativo, pero igual de equivocado.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    vacia = (
        "<tr><td colspan='8'>No se han encontrado resultados con los datos ingresados. "
        "Recuerde que las causas reservadas no se muestran en la consulta unificada.</td></tr>"
    )
    c = _cliente_con([vacia])
    assert c.buscar_por_rit("C", 999999, 1990) == []


# -- competencias: buscable no es lo mismo que legible --------------------------


def test_pedir_actuaciones_de_una_competencia_sin_receptor_no_gasta_peticiones():
    """En todo el sitio sólo existen `receptorCivil` y `receptorCobranza`.

    Laboral es buscable y no tiene ministro de fe, así que la pregunta no tiene respuesta
    ahí. Sin este rechazo se gastaban dos peticiones y diez segundos contra la plataforma
    para terminar culpándola de un cambio de estructura que nunca hubo.
    """
    c = _sin_red()
    with pytest.raises(ValueError, match="no expone actuaciones"):
        c.actuaciones_receptor("O", 1583, 2018, competencia="laboral")


def test_pedir_actuaciones_de_una_competencia_sin_panel_mapeado_no_gasta_peticiones(monkeypatch):
    """Una competencia puede exponer ministro de fe y no tener su historia medida.

    Hoy no existe ninguna así: civil y cobranza son las dos con receptor y las dos tienen su
    tabla. O sea el guardia quedaría inalcanzable, que es la forma más silenciosa de que un
    guardia deje de servir. Se construye la competencia que falta para poder ejercitarlo.
    """
    from mcp_pjud.parser import COMPETENCIAS as REALES
    from mcp_pjud.parser import Competencia

    inventada = Competencia(
        99,
        {"rol": 1, "fecha_ingreso": 2, "caratulado": 3, "tribunal": 4},
        litigantes=None,
        materias=None,
        liquidaciones=None,
        notificaciones=None,
        rol_con_libro=False,
        campos_rit={},
        historia=None,
        receptor=True,
        receptor_en_historia=True,
        acota_por="tribunal",
    )
    monkeypatch.setitem(REALES, "inventada", inventada)
    monkeypatch.setattr("mcp_pjud.client.MODULOS", {*MODULOS, "inventada"})

    c = _sin_red()
    with pytest.raises(ValueError, match="No está verificado"):
        c.actuaciones_receptor("C", 1, 2019, competencia="inventada")


def test_una_peticion_colgada_no_gana_fichas(monkeypatch):
    """El reloj de recarga arranca cuando la petición termina, no cuando empieza.

    Si contara desde antes, una petición que estuvo un minuto colgada devolvería el balde
    lleno, o sea el portal recibiría una ráfaga justo cuando peor está. Es la razón por la que
    `_req` estampa la marca en `finally` y no antes de salir a la red.

    Se mide en la petición SIGUIENTE y no en las fichas de esta: la recarga se calcula al
    entrar a `_esperar`, así que mirar el balde justo después de `_req` no distingue una
    implementación de la otra. La primera versión de este test hacía eso y pasaba con la marca
    puesta antes o después.
    """
    ahora = [1000.0]
    dormido = []
    monkeypatch.setattr("mcp_pjud.client.time.monotonic", lambda: ahora[0])

    def dormir(s):
        dormido.append(s)
        ahora[0] += s

    monkeypatch.setattr("mcp_pjud.client.time.sleep", dormir)
    monkeypatch.setattr("mcp_pjud.client._FICHAS", 1.0)  # justo una, sin ráfaga de sobra
    monkeypatch.setattr("mcp_pjud.client._ULTIMA", 1000.0)

    def transporte(req):
        ahora[0] += 60.0  # la plataforma tardó un minuto en responder
        return httpx.Response(200, text="ok")

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    c._req("GET", "https://oficinajudicialvirtual.pjud.cl/a")
    assert dormido == [], "con una ficha en el balde la primera no debía esperar"

    c._req("GET", "https://oficinajudicialvirtual.pjud.cl/b")
    assert dormido == [pytest.approx(INTERVALO_MINIMO)], (
        "la segunda tiene que esperar el intervalo completo: el minuto que la primera estuvo "
        f"colgada no se convierte en fichas. Esperas observadas: {dormido}"
    )


def test_una_peticion_que_muere_por_timeout_queda_en_la_bitacora(monkeypatch):
    """La bitácora existe para acreditar cuánto se consultó (§8).

    Una petición que no llegó a respuesta igual salió a la red. Sin registrarla, el registro
    subestima el tráfico generado justo en las corridas donde la plataforma va peor, que son
    las que uno querría poder explicar.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)

    def transporte(req):
        raise httpx.ReadTimeout("la plataforma no respondió", request=req)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))

    with pytest.raises(httpx.ReadTimeout):
        c._req("GET", "https://juris.pjud.cl/busqueda/buscar_sentencias")

    assert len(c.bitacora) == 1, "la petición que murió por timeout tiene que quedar anotada"
    _, url, estado = c.bitacora[0]
    assert url.endswith("buscar_sentencias")
    assert estado == 0, "se anota con estado 0, que ningún código HTTP usa"


def test_pedir_actuaciones_de_cobranza_dice_que_estan_en_otro_panel():
    """Se midió sobre una respuesta real: los trámites de `historiaCob` son `Actuación`,
    `Resolución` y `Escrito`, nunca "Actuación Receptor", y las diligencias viven en
    `diligenciaCob` con estructura propia. La palabra "receptor" aparece en esa respuesta, o
    sea existen.

    Sin este rechazo, pedir actuaciones de cobranza devolvía una lista vacía mientras las
    diligencias estaban en el panel de al lado: "no hubo actuaciones" cuando lo cierto era "no
    las estoy leyendo". Es el falso negativo que este proyecto existe para evitar.
    """
    c = _sin_red()
    with pytest.raises(ValueError, match="NO están en la tabla"):
        c.actuaciones_receptor("C", 208, 2019, competencia="cobranza")


# -- lo que la plataforma exige por competencia --------------------------------
#
# Suprema y apelaciones se verificaron el 17 de agosto de 2026, y lo que las bloqueaba era un
# campo que las otras cuatro competencias toleran ausente. Los guardias de abajo existen
# porque ese hueco no se veía desde ningún test: la búsqueda de rol andaba en las cuatro
# competencias que estaban expuestas, así que el campo faltante no rompía nada.


def _capturando(respuesta: str = "") -> tuple[PjudClient, list[dict[str, str]]]:
    """Cliente que registra el formulario de cada petición en vez de salir a la red."""
    enviados: list[dict[str, str]] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        cuerpo = peticion.content.decode("utf-8")
        enviados.append(dict(urllib.parse.parse_qsl(cuerpo, keep_blank_values=True)))
        return httpx.Response(200, text=respuesta)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32
    return c, enviados


def test_la_busqueda_por_rol_manda_el_radio_rit(monkeypatch):
    """Sin `radio-group`, suprema y apelaciones responden HTTP 200 con el cuerpo VACÍO.

    Su PHP se ramifica en ese campo para saber si se busca por RIT o por RUC, y si falta
    revienta sin aviso. Las otras cuatro competencias lo toleran ausente, y por eso el hueco
    sobrevivió: no rompía nada de lo que estaba expuesto. Costó dos diagnósticos equivocados
    (que faltaba el código de libro en `conTipoCausa`, y que sobraban los campos que el sitio
    deshabilita) antes de bisectarlo.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c, enviados = _capturando(_pagina(range(1, 2), total=1, ultima=True))
    c.buscar_por_rit("C", 1156, 2026)
    assert enviados, "no se envió ninguna petición"
    assert enviados[0].get("radio-group") == "1", (
        "falta el radio RIT/RUC: suprema y apelaciones devolverían un cuerpo vacío, que se "
        "lee como que la causa no existe"
    )


def test_suprema_no_exige_ni_tribunal_ni_corte(monkeypatch):
    """Medido: las tres búsquedas de suprema andan sin corte ni tribunal.

    El sitio deshabilita los dos selectores para esa competencia. Exigirlos sería rechazar por
    cuenta propia consultas que la plataforma acepta, y eso no gasta una petición ni deja
    rastro: se ve igual que "no hay causas".
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    listado = _pagina(range(1, 2), total=1, ultima=True, celdas=8)
    for consultar in (
        lambda c: c.buscar_por_nombre(
            apellido_paterno="GONZALEZ", apellido_materno="PEREZ", competencia="suprema"
        ),
        lambda c: c.buscar_por_fecha("03/08/2026", "05/08/2026", competencia="suprema"),
        lambda c: c.buscar_por_rut_juridica(97004000, "5", competencia="suprema"),
    ):
        c, enviados = _capturando(listado)
        consultar(c)
        assert enviados, "el cliente rechazó por su cuenta una consulta que la plataforma acepta"


def test_apelaciones_exige_corte_y_no_tribunal():
    """La plataforma responde "Por favor seleccione una Corte para la búsqueda" en las tres.

    Se midió el mismo aviso en nombre, en RUT y en fecha, así que el requisito es de la
    competencia y no de la búsqueda: por eso lo resuelve una sola función con la tabla.
    """
    c = _sin_red()
    with pytest.raises(ValueError, match="exige corte"):
        c.buscar_por_nombre(
            apellido_paterno="GONZALEZ", apellido_materno="PEREZ", competencia="apelaciones"
        )
    with pytest.raises(ValueError, match="exige corte"):
        c.buscar_por_fecha("03/08/2026", "05/08/2026", competencia="apelaciones")
    with pytest.raises(ValueError, match="exige corte"):
        c.buscar_por_rut_juridica(97004000, "5", competencia="apelaciones")


def test_las_de_primera_instancia_siguen_exigiendo_tribunal():
    """Lo que cambió es que el requisito depende de la competencia, no que se haya soltado."""
    c = _sin_red()
    for competencia in ("civil", "laboral", "cobranza", "penal"):
        with pytest.raises(ValueError, match="exige tribunal"):
            c.buscar_por_nombre(
                apellido_paterno="GONZALEZ", apellido_materno="PEREZ", competencia=competencia
            )


def test_toda_competencia_declara_con_que_acotar():
    """Un valor inventado en `acota_por` haría que `_acotacion` no exija nada y pase de largo.

    La función compara contra dos literales; cualquier otra cosa cae en el silencio, que es la
    forma de falla que este proyecto no acepta. El guardia es sobre la tabla, no sobre el
    llamador, porque el llamador nunca vería el problema.
    """
    for nombre, spec in COMPETENCIAS.items():
        assert spec.acota_por in {"tribunal", "corte", None}, (
            f"{nombre} declara acotarse por {spec.acota_por!r}, que `_acotacion` ignora en silencio"
        )


def test_la_busqueda_por_nombre_manda_su_propio_radio_y_los_campos_del_formulario(monkeypatch):
    """El único payload con guardia era el de rol, y el hueco que rompió suprema fue un campo
    de formulario que ningún test miraba.

    `radio-group` viaja acá con "N" y en la búsqueda por rol con "1": son formularios distintos
    con dominios de valores distintos, y no una inconsistencia. Sin este guardia, cambiar
    cualquiera de los dos deja la otra búsqueda muda y verde.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c, enviados = _capturando(_pagina(range(1, 2), total=1, ultima=True, celdas=8))
    c.buscar_por_nombre(
        apellido_paterno="GONZALEZ", apellido_materno="PEREZ", competencia="suprema"
    )
    (formulario,) = enviados
    assert formulario["radio-group"] == "N", (
        "el formulario de nombre usa 'N', no el '1' del de rol: son dominios distintos"
    )
    assert formulario["nomApePaterno"] == "GONZALEZ"
    assert formulario["nomApeMaterno"] == "PEREZ"
    assert formulario["nomCompetencia"] == "1", "suprema es la competencia 1"


def test_la_busqueda_por_rol_no_exige_acotar_en_ninguna_competencia(monkeypatch):
    """Es la única de las cuatro que la plataforma acepta sin corte ni tribunal.

    Medido con `conCorte=0`: suprema devolvió su causa y apelaciones devolvió 31. Por eso
    `buscar_por_rit` no llama a `_acotacion`, y por eso este guardia existe: agregar la llamada
    "por consistencia" haría que este cliente rechace por su cuenta consultas que sí funcionan.

    Se comprueba que la petición SALGA, no que devuelva algo: lo que se está midiendo es que el
    cliente no rechace antes de consultar. Con un doble que falla ante cualquier petición, este
    test se caería justo cuando el código es correcto.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    for competencia in COMPETENCIAS:
        c, enviados = _capturando(_pagina(range(1, 2), total=1, ultima=True, celdas=8))
        motivo = ""
        try:
            c.buscar_por_rit("C", 1156, 2026, competencia=competencia, paginas=None)
        except ValueError as e:
            motivo = str(e)
        except EstructuraInesperada:
            # La fila sintética no calza con todas las competencias, y da lo mismo: la
            # pregunta es si la petición salió.
            pass

        assert "exige tribunal" not in motivo, (
            f"la búsqueda por rol en {competencia} no debe exigir tribunal: {motivo}"
        )
        assert "exige corte" not in motivo, (
            f"la búsqueda por rol en {competencia} no debe exigir corte: {motivo}"
        )
        assert enviados, f"en {competencia} la búsqueda por rol se rechazó antes de consultar"


@pytest.mark.parametrize(
    ("competencia", "filas"),
    [("suprema", 1), ("apelaciones", 3)],
)
def test_un_listado_completo_no_pide_otra_pagina(competencia, filas, monkeypatch):
    """En suprema y apelaciones el listado ofrece "siguiente" aunque esté completo.

    Medido sobre sus dos respuestas reales: 1 de 1 y 3 de 3, las dos con enlace. Civil no lo
    hace, y por eso `_paginado` podía terminar sólo cuando el enlace desaparecía sin que nada
    fallara. Al habilitar estas dos competencias esa condición dejó de alcanzar: seguir el
    enlace pide una página que no existe, y la búsqueda COMPLETA termina en error.

    Se cuentan las peticiones, no el resultado: devolver la lista correcta gastando el doble de
    peticiones contra el Poder Judicial también sería un fallo, y no se vería en los datos.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    listado = (FIXTURES / f"busqueda_rit_{competencia}.html").read_text(encoding="utf-8")
    c, enviados = _capturando(listado)

    causas = c.buscar_por_rit("C", 9999, 2019, competencia=competencia)

    assert len(causas) == filas
    assert len(enviados) == 1, (
        f"el listado de {competencia} venía completo y se pidieron {len(enviados)} páginas"
    )


def test_la_busqueda_por_rol_manda_lo_que_su_competencia_declara(monkeypatch):
    """Tres de las seis competencias exigen un campo propio en la búsqueda por rol, y las tres
    estuvieron rotas por no mandarlo.

    Suprema y apelaciones respondían "Por favor ingrese sólo números para el Tipo de Búsqueda",
    y penal devolvía un cuerpo sin listado ni aviso. Se habían declarado verificadas midiendo
    con peticiones armadas a mano, y los tests usaban dobles: nunca hubo nada que ejercitara
    `buscar_por_rit` de verdad. Se publicaron rotas en la 0.2.0.

    Lo que este guardia puede probar y lo que no, dicho explícito: comprueba que el cliente
    mande lo que la tabla declara, no que la plataforma lo acepte. Lo segundo no se puede probar
    sin red, y la suite no consulta al Poder Judicial. La tabla es el registro de lo medido; el
    test impide que el código y ese registro se separen.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    for competencia, spec in COMPETENCIAS.items():
        if competencia not in MODULOS:
            continue
        c, enviados = _capturando(_pagina(range(1, 2), total=1, ultima=True, celdas=8))
        # La fila sintética no calza con todas las competencias, y da lo mismo: lo que se
        # mide es el formulario que salió, no lo que se pudo leer de vuelta.
        with contextlib.suppress(EstructuraInesperada):
            c.buscar_por_rit("C", 1156, 2026, competencia=competencia, paginas=None)
        (formulario,) = enviados
        for campo, valor in spec.campos_rit.items():
            assert formulario.get(campo) == valor, (
                f"{competencia} declara {campo}={valor!r} y la búsqueda por rol mandó "
                f"{formulario.get(campo)!r}"
            )


def test_solo_las_competencias_medidas_declaran_campos_de_mas():
    """Un campo de más inventado se manda igual y la plataforma no siempre avisa.

    Las tres que los llevan están medidas una por una: `conTipoBus` en suprema,
    `conTipoBusApe` en apelaciones y `radio-groupPenal` en penal. Las otras tres se midieron
    andando sin ninguno, así que declarar uno ahí sería agregar un campo que nadie comprobó.
    """
    con_extras = {n: sorted(c.campos_rit) for n, c in COMPETENCIAS.items() if c.campos_rit}
    assert con_extras == {
        "apelaciones": ["conTipoBusApe"],
        "penal": ["radio-groupPenal"],
        "suprema": ["conTipoBus"],
    }, f"cambió qué competencias exigen campos propios: {con_extras}"


def test_la_historia_se_rechaza_donde_el_panel_no_esta_medido():
    """Penal es buscable y NINGÚN panel de su detalle está mapeado.

    Se pidió su detalle y `historiaPen` vino con encabezados y CERO filas, igual que sus otros
    tres paneles, así que declarar sus columnas sería escribir un mapa que nada comprobó.

    Se rechaza antes de gastar peticiones. Sin esto la lectura combinada gastaría dos para
    devolver todos los campos en nulo, que además se lee como que la causa no tiene nada.
    """
    c = _sin_red()
    with pytest.raises(ValueError, match="No está verificado"):
        c.detalle_causa("1", 528, 2017, competencia="penal", tribunal=1082)


def test_las_dos_lecturas_de_la_causa_recorren_los_mismos_cuadernos(monkeypatch):
    """`actuaciones_receptor` y la lectura combinada sólo difieren en qué filas se quedan.

    Comparten el recorrido a propósito: duplicarlo para cambiar el filtro es la forma más
    segura de que uno de los dos se olvide del cuaderno de apremio, que es exactamente el
    falso negativo que originó este proyecto.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    apremio = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")
    listado = _pagina(range(1, 2), total=1, ultima=True)

    def cliente() -> tuple[PjudClient, list[str]]:
        pedidos: list[str] = []
        paginas = [listado, principal, principal, apremio]

        def transporte(peticion: httpx.Request) -> httpx.Response:
            pedidos.append(str(peticion.url))
            return httpx.Response(200, text=paginas[min(len(pedidos) - 1, len(paginas) - 1)])

        c = PjudClient("test@example.cl")
        c._http = httpx.Client(transport=httpx.MockTransport(transporte))
        c._adir, c._token = "ADIR_1", "0" * 32
        return c, pedidos

    c, pedidos_receptor = cliente()
    del_receptor = c.actuaciones_receptor("C", 9001, 2026, tribunal=162)
    c, pedidos_historia = cliente()
    detalle = c.detalle_causa("C", 9001, 2026, tribunal=162)
    de_historia = detalle.historia or []

    assert pedidos_receptor == pedidos_historia, (
        "las dos lecturas tienen que hacer exactamente las mismas peticiones"
    )
    assert de_historia, "la historia completa no puede venir vacía"
    assert len(de_historia) > len(del_receptor), (
        "la historia completa tiene que traer más filas que el filtro de receptor"
    )

    # Comparar las dos lecturas entre sí NO alcanza, y hubo que verlo: dejando de recorrer los
    # cuadernos las dos siguen coincidiendo y el test seguía verde. Lo que discrimina es contar
    # los cuadernos que llegaron, porque el segundo sólo existe si se pidió aparte.
    cuadernos = {a.cuaderno for a in de_historia}
    assert len(cuadernos) == 2, (
        f"la causa tiene dos cuadernos y llegaron {sorted(cuadernos)}: no se recorrieron. "
        "El de apremio es donde viven el requerimiento de pago y el embargo"
    )
    assert cuadernos == {a.cuaderno for a in del_receptor}
    assert len(pedidos_historia) == 4, (
        f"se esperaban cuatro peticiones (búsqueda, detalle y un cuaderno cada uno) y "
        f"salieron {len(pedidos_historia)}"
    )


def _cliente_apelaciones(monkeypatch) -> tuple[PjudClient, list[str]]:
    """Cliente que responde con el listado REAL de apelaciones, donde el rol se repite."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    listado = (FIXTURES / "busqueda_rit_apelaciones.html").read_text(encoding="utf-8")
    detalle = (FIXTURES / "detalle_apelaciones.html").read_text(encoding="utf-8")
    pedidos: list[str] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidos.append(peticion.content.decode("utf-8"))
        return httpx.Response(200, text=listado if len(pedidos) == 1 else detalle)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32
    return c, pedidos


def test_un_rol_que_existe_en_varios_libros_no_se_resuelve_eligiendo_el_primero(monkeypatch):
    """En Cortes de Apelaciones el número de rol NO identifica una causa.

    La fixture es una respuesta real: 9999-2019 son un Exhorto, una Civil y una Protección, con
    referencias distintas y por lo tanto historias distintas. Abrir la primera entrega las
    actuaciones de otra causa como si fueran las pedidas.

    Es peor que el falso negativo que este proyecto existe para evitar. Una lista vacía se nota;
    una historia ajena viene con folios, fechas y trámites que se ven perfectamente bien, y
    alguien computaría un plazo contra una causa que no es la suya. Por eso se levanta.
    """
    c, _ = _cliente_apelaciones(monkeypatch)
    with pytest.raises(ValueError, match="ninguna corresponde sin ambigüedad"):
        c.detalle_causa("", 9999, 2019, competencia="apelaciones", corte=46)


def test_el_libro_en_tipo_desambigua_la_causa_de_apelaciones(monkeypatch):
    """Y con el libro indicado sí se resuelve, sin preguntar nada más."""
    c, _ = _cliente_apelaciones(monkeypatch)
    actuaciones = c.detalle_causa("Protección", 9999, 2019, competencia="apelaciones", corte=46)
    assert actuaciones, "con el libro indicado la causa se resuelve"


def test_el_mensaje_de_ambiguedad_nombra_los_libros_encontrados(monkeypatch):
    """Un error que no dice cómo salir del problema obliga a leer el código.

    Acá la salida existe y es concreta: indicar el libro en `tipo`. El mensaje tiene que traer
    los que la plataforma devolvió, o quien consulta no sabe cuáles puede pedir.
    """
    c, _ = _cliente_apelaciones(monkeypatch)
    with pytest.raises(ValueError, match="ambigüedad") as fallo:
        c.detalle_causa("", 9999, 2019, competencia="apelaciones", corte=46)
    for libro in ("Exhorto", "Civil", "Protección"):
        assert libro in str(fallo.value), f"el mensaje no nombra el libro {libro!r}"


def test_un_unico_resultado_de_otro_libro_tampoco_se_abre(monkeypatch):
    """El atajo de devolver la única coincidencia dejaba el riesgo intacto.

    `buscar_por_rit` no filtra apelaciones por `tipo`, así que pedir un libro y recibir una
    sola fila de OTRO libro es un caso real: con el atajo se abría igual, sin comparar nada, y
    entregaba la historia de una causa distinta. Que haya un solo resultado no prueba que sea
    el pedido.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    completo = (FIXTURES / "busqueda_rit_apelaciones.html").read_text(encoding="utf-8")
    # Se recorta el listado a la fila del Exhorto: una sola coincidencia, de otro libro.
    corte = completo.index("Civil-9999-2019")
    solo_exhorto = (
        completo[: completo.rindex("<tr", 0, corte)]
        + completo[completo.index("Total de registros") - 40 :]
    )

    c, _ = _capturando(solo_exhorto)
    with pytest.raises(ValueError, match="ambigüedad"):
        c.detalle_causa("Protección", 9999, 2019, competencia="apelaciones", corte=46)


def test_leer_todo_el_detalle_cuesta_una_sola_cadena(monkeypatch):
    """Es la razón de existir de la lectura combinada, y va como número.

    Antes cada panel se pedía por su cuenta y cada uno repetía la cadena entera: buscar, abrir
    el detalle y recorrer los cuadernos. Preguntar cuatro cosas de una causa con dos cuadernos
    costaba dieciséis peticiones contra la plataforma para leer paneles que ya venían juntos en
    la primera respuesta.

    Cuadruplicar las consultas va contra la cláusula CUARTA, que es la obligación central del
    proyecto, así que el ahorro se fija acá y no en la prosa.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    apremio = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")
    listado = (FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8")
    pedidos: list[str] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidos.append(str(peticion.url))
        if "consultaRit" in str(peticion.url):
            return httpx.Response(200, text=listado)
        return httpx.Response(200, text=apremio if len(pedidos) > 3 else principal)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    detalle = c.detalle_causa("E", 468, 2026, tribunal=162)

    assert len(pedidos) == 4, (
        f"leer el detalle completo de una causa de dos cuadernos costó {len(pedidos)} "
        f"peticiones: la búsqueda, el detalle y un cuaderno cada uno son cuatro. Acá la "
        f"sesión ya está abierta; desde un cliente frío son seis, y así se midió contra la "
        f"plataforma real"
    )
    assert detalle.historia, "la historia no puede venir vacía"
    assert detalle.litigantes, "los litigantes tampoco"
    assert len({a.cuaderno for a in detalle.historia}) == 2, (
        "se leyó un solo cuaderno: el de apremio es donde viven el requerimiento y el embargo"
    )


def test_un_panel_que_la_competencia_no_publica_viaja_en_nulo_y_no_vacio(monkeypatch):
    """La distinción que este proyecto existe para no borrar.

    Lista vacía significa "el panel existe y no trae filas", que es una respuesta. Nulo
    significa "esta competencia no lo informa". Devolver vacío en el segundo caso haría leer
    "acá no se informa" como "no ocurrió".
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    listado = (FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8")

    def transporte(peticion: httpx.Request) -> httpx.Response:
        if "consultaRit" in str(peticion.url):
            return httpx.Response(200, text=listado)
        return httpx.Response(200, text=principal)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    detalle = c.detalle_causa("E", 468, 2026, tribunal=162)

    assert detalle.liquidaciones is None, "civil no liquida el crédito: eso es nulo, no vacío"
    assert detalle.materias is None, "civil no publica materias"
    assert detalle.notificaciones == [], (
        "civil SÍ publica el panel de notificaciones y esta causa no tiene ninguna: eso es "
        "una lista vacía, que es una respuesta, y no un nulo"
    )


def test_una_causa_que_no_aparece_no_se_confunde_con_una_competencia_sin_paneles(monkeypatch):
    """Sin marca explícita, los dos casos viajan idénticos: todos los campos en nulo.

    Y significan cosas opuestas. "No encontré la causa" es una respuesta sobre el rol pedido;
    "esta competencia no publica ese panel" es una respuesta sobre la competencia. Una causa
    civil reservada o inexistente se habría informado como que civil no publica historia ni
    litigantes ni notificaciones, que es falso.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    sin_coincidencias = (
        "<tr><td colspan='8'>No se han encontrado resultados con los datos ingresados. "
        "Recuerde que las causas reservadas no se muestran en la consulta unificada.</td></tr>"
    )
    c, _ = _capturando(sin_coincidencias)

    detalle = c.detalle_causa("C", 9999, 2026, tribunal=162)

    assert detalle.causa_encontrada is False, (
        "la causa no apareció y el resultado no lo dice: todos los campos en nulo se leen como "
        "que la competencia no publica ninguno"
    )
    assert detalle.historia is None


def test_el_detalle_trae_el_exhorto_una_vez_aunque_los_dos_cuadernos_lo_repitan(monkeypatch):
    """El panel de exhortos NO lleva el cuaderno en la fila, y C-1156 lo publica idéntico en
    los dos: sin deduplicar, el mismo exhorto llegaría dos veces y se leería como dos causas
    despachadas.

    Y el campo importa por lo que significa: si trae algo, parte de la tramitación ocurre en
    OTRO expediente. Un plazo que corre por una diligencia exhortada no se computa desde acá.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    apremio = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")
    paginas = [_pagina(range(1, 2), total=1, ultima=True), principal, principal, apremio]
    pedidos: list[str] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidos.append(str(peticion.url))
        return httpx.Response(200, text=paginas[min(len(pedidos) - 1, len(paginas) - 1)])

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    detalle = c.detalle_causa("C", 9001, 2026, tribunal=162)

    assert detalle.exhortos is not None, "civil publica el panel: no puede venir en nulo"
    assert len(detalle.exhortos) == 1, (
        f"el mismo exhorto viene en los dos cuadernos y llegó {len(detalle.exhortos)} veces"
    )
    assert detalle.exhortos[0].rol_destino == "E-875-2026"
    assert detalle.exhortos[0].tribunal_destino == "1º Juzgado Civil de Chillán"


@pytest.mark.parametrize("competencia", ["cobranza", "laboral"])
def test_el_detalle_de_una_competencia_sin_exhortos_medidos_los_deja_en_nulo(
    competencia, monkeypatch
):
    """Nulo y lista vacía dicen cosas distintas: "acá no se informa" contra "no despachó
    ninguno". Sólo civil tiene el panel medido."""
    from mcp_pjud.parser import COMPETENCIAS

    assert COMPETENCIAS[competencia].exhortos is None


def test_una_referencia_que_cambia_entre_cuadernos_no_duplica_el_exhorto(monkeypatch):
    """El MISMO exhorto llega con una referencia distinta en cada cuaderno.

    Está medido sobre C-1156-2026: `referencia-ficticia-021` en el principal y `-030` en el de
    apremio. Son tokens de render, no identidades, así que deduplicar incluyéndolas informaba
    dos exhortos donde hay uno, y una causa que despachó uno diría que despachó dos.

    Se entregan igual, porque son lo único que permitiría abrir el detalle del exhorto cuando
    ese panel esté medido. Lo que cambia es que no cuentan para decidir si dos filas son la
    misma cosa.
    """
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    apremio = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")

    from mcp_pjud.parser import parse_exhortos

    refs = {parse_exhortos(pagina, "civil")[0].referencia for pagina in (principal, apremio)}
    assert len(refs) == 2, (
        "las fixtures dejaron de traer referencias distintas por cuaderno y este test ya no "
        f"prueba nada: {refs}"
    )

    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    paginas = [_pagina(range(1, 2), total=1, ultima=True), principal, principal, apremio]
    pedidos: list[str] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidos.append(str(peticion.url))
        return httpx.Response(200, text=paginas[min(len(pedidos) - 1, len(paginas) - 1)])

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    exhortos = c.detalle_causa("C", 9001, 2026, tribunal=162).exhortos or []
    assert len(exhortos) == 1, f"un exhorto llegó {len(exhortos)} veces"
    assert exhortos[0].referencia, "la referencia se entrega igual, sólo no cuenta para dedup"


# -- los códigos que las búsquedas exigen -------------------------------------------


def _cliente_de_combos(monkeypatch, cuerpo, estado=200):
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    pedidos: list[tuple[str, bytes]] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidos.append((str(peticion.url), peticion.content))
        return httpx.Response(estado, json=cuerpo)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32
    return c, pedidos


def test_los_combos_no_cuelgan_del_prefijo_de_rutas(monkeypatch):
    """Todo lo demás del sitio va bajo `ADIR_nnn`. Estos NO, y está medido: con el prefijo
    devuelven 404.

    Es la clase de detalle que se pierde al reusar el ayudante de siempre, y el síntoma sería
    un 404 que se lee como "no hay tribunales".
    """
    c, pedidos = _cliente_de_combos(
        monkeypatch, [{"COD_CORTE": "46", "GLS_CORTE": "C.A. de Concepción"}]
    )
    c.listar_cortes()

    url = pedidos[0][0]
    assert url.endswith("/combosJSON/leeCorte.php"), url
    assert "ADIR_" not in url, f"la consulta se hizo bajo el prefijo y ahí devuelve 404: {url}"


def test_el_listado_de_tribunales_manda_el_codigo_de_la_competencia_pedida(monkeypatch):
    """Los códigos difieren entre competencias: pedir los de civil con el código de laboral
    devolvería una lista plausible y equivocada, y quien buscara con esos números no
    encontraría la causa."""
    c, pedidos = _cliente_de_combos(
        monkeypatch, [{"COD_TRIBUNAL": "163", "GLS_TRIBUNAL": "3º Juzgado Civil de Concepción"}]
    )
    tribunales = c.listar_tribunales("civil", 46)

    cuerpo = pedidos[0][1].decode()
    assert f"codCompetencia={COMPETENCIAS['civil'].codigo}" in cuerpo, cuerpo
    assert "codCorte=46" in cuerpo, cuerpo
    assert [(t.codigo, t.nombre) for t in tribunales] == [(163, "3º Juzgado Civil de Concepción")]


@pytest.mark.parametrize("competencia", ["suprema", "apelaciones", "familia"])
def test_una_competencia_sin_tribunales_utiles_se_rechaza_sin_gastar_peticion(
    competencia, monkeypatch
):
    """No es sólo que la competencia no exista: es que la pregunta no tiene sentido.

    Medido el 20 de agosto de 2026 sobre la corte 46: suprema devuelve `null` porque ES la
    corte y no tiene tribunales debajo, y apelaciones devuelve 118 juzgados de PRIMERA
    instancia, que no son con qué se busca ahí. Devolver esa lista invitaría a usarla como si
    fuera `tribunal`, y la búsqueda no encontraría nada.
    """
    c, pedidos = _cliente_de_combos(monkeypatch, [])
    with pytest.raises(EstructuraInesperada, match="no se acota por tribunal"):
        c.listar_tribunales(competencia, 46)
    assert not pedidos, "no debe salir ninguna petición para una competencia sin tribunales"


def test_un_listado_de_cortes_vacio_levanta_en_vez_de_publicarse(monkeypatch):
    """Siempre hay cortes. Una lista vacía se leería como que no las hay, y quien la reciba
    concluiría que no puede buscar en apelaciones."""
    c, _ = _cliente_de_combos(monkeypatch, [])
    with pytest.raises(EstructuraInesperada, match="vac"):
        c.listar_cortes()


def test_una_respuesta_que_no_es_una_lista_levanta(monkeypatch):
    """Si la plataforma pasa a responder un objeto de error con HTTP 200, iterarlo daría sus
    claves como si fueran tribunales."""
    c, _ = _cliente_de_combos(monkeypatch, {"error": "sesion expirada"})
    with pytest.raises(EstructuraInesperada, match="en vez de una lista"):
        c.listar_tribunales("civil", 46)


def test_un_listado_de_tribunales_vacio_levanta_en_vez_de_publicarse(monkeypatch):
    """Toda corte tiene tribunales debajo. La lista vacía se leería como que esa corte no tiene
    ninguno, y quien la reciba concluiría que el tribunal que busca no existe.

    Pasa también si la plataforma renombra `COD_TRIBUNAL`: el filtro descartaría todas las
    filas y el resultado sería idéntico a una corte sin tribunales.
    """
    c, _ = _cliente_de_combos(monkeypatch, [{"OTRO_NOMBRE": "163", "GLS_TRIBUNAL": "x"}])
    with pytest.raises(EstructuraInesperada, match="vino vacío"):
        c.listar_tribunales("civil", 46)


def test_el_detalle_de_una_causa_exhortada_trae_sus_piezas(monkeypatch):
    """E-468-2026 es el otro lado del exhorto: la causa que otro tribunal abrió acá.

    Sus dos paneles del exhorto dicen cosas opuestas y las dos importan. `exhortos` viene
    vacío porque esta causa no despachó ninguno, y `piezas_exhorto` trae los seis trámites que
    el tribunal de origen mandó junto con el exhorto.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    exhortada = (FIXTURES / "detalle_causa_civil.html").read_text(encoding="utf-8")
    listado = (FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8")

    def transporte(peticion: httpx.Request) -> httpx.Response:
        if "consultaRit" in str(peticion.url):
            return httpx.Response(200, text=listado)
        return httpx.Response(200, text=exhortada)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    detalle = c.detalle_causa("E", 468, 2026, tribunal=163)

    assert detalle.causa_es_exhorto is True
    assert detalle.piezas_exhorto is not None, "esta causa ES un exhorto: no puede venir nulo"
    assert len(detalle.piezas_exhorto) == 6
    assert detalle.exhortos == [], (
        "el panel de exhortos despachados existe y esta causa no despacha ninguno: eso es una "
        "lista vacía, y no se confunde con las piezas que sí trae"
    )


def test_una_causa_que_no_es_exhorto_se_distingue_de_una_competencia_sin_el_panel(monkeypatch):
    """El contrato que esta lectura vino a resolver.

    En `piezas_exhorto` el nulo puede significar dos cosas: que la competencia no publica el
    panel, o que ESTA causa no es un exhorto. Meter las dos en el mismo nulo borra la
    distinción que el resto del modelo protege, así que la nombra `causa_es_exhorto`: acá es
    falso, o sea la causa no lo es, y no que civil no informe.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    apremio = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")
    paginas = [_pagina(range(1, 2), total=1, ultima=True), principal, principal, apremio]
    pedidos: list[str] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidos.append(str(peticion.url))
        return httpx.Response(200, text=paginas[min(len(pedidos) - 1, len(paginas) - 1)])

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    detalle = c.detalle_causa("C", 9001, 2026, tribunal=162)

    assert detalle.causa_es_exhorto is False, (
        "C-1156-2026 despacha un exhorto pero no es uno, y la cabecera lo dice"
    )
    assert detalle.piezas_exhorto is None, (
        "la lista vacía se leería como que el tribunal de origen no mandó ninguna pieza, y acá "
        "no hay tribunal de origen: esta causa no es un exhorto"
    )
    assert detalle.exhortos, "el otro lado sí está: esta causa despacha E-875-2026"


def test_la_pregunta_del_exhorto_no_se_responde_en_una_competencia_sin_medir(monkeypatch):
    """Sin el guardia, leer la cabecera de cobranza reventaría la lectura entera, y con una
    respuesta inventada diría que ninguna causa de cobranza es un exhorto.

    `causa_es_exhorto` en nulo es la respuesta honesta: la pregunta no está medida acá.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    listado = (FIXTURES / "busqueda_rit_cobranza.html").read_text(encoding="utf-8")
    cobranza = (FIXTURES / "detalle_cobranza.html").read_text(encoding="utf-8")

    def transporte(peticion: httpx.Request) -> httpx.Response:
        if "consultaRit" in str(peticion.url):
            return httpx.Response(200, text=listado)
        return httpx.Response(200, text=cobranza)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    detalle = c.detalle_causa("C", 9999, 2019, competencia="cobranza", tribunal=1200)

    assert detalle.causa_es_exhorto is None
    assert detalle.piezas_exhorto is None
    assert detalle.liquidaciones, "y el resto de la lectura sigue funcionando"


# -- documentos ------------------------------------------------------------------


def _pdf(flujo: bytes, con_fuente: bool = True) -> bytes:
    """Un PDF mínimo pero VÁLIDO, con su tabla de referencias cruzadas bien calculada.

    Se arma acá y no se guarda como fixture por dos razones. La primera es que no hay ninguno
    real que guardar: este proyecto todavía no le pidió un documento a la plataforma, e
    inventar una fixture "real" sería afirmar algo que no se midió. La segunda es que lo que
    estos tests distinguen es una propiedad del archivo (que tenga o no texto extraíble) y así
    se controla exactamente, sin depender de qué trajo un PDF cualquiera.
    """
    fuente = b"/Resources<</Font<</F1 5 0 R>>>>" if con_fuente else b"/Resources<<>>"
    objetos = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R" + fuente + b">>",
        b"<</Length " + str(len(flujo)).encode() + b">>stream\n" + flujo + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    salida = bytearray(b"%PDF-1.4\n")
    desplazamientos = []
    for i, cuerpo in enumerate(objetos, start=1):
        desplazamientos.append(len(salida))
        salida += str(i).encode() + b" 0 obj" + cuerpo + b"endobj\n"
    xref = len(salida)
    salida += b"xref\n0 " + str(len(objetos) + 1).encode() + b"\n0000000000 65535 f \n"
    for d in desplazamientos:
        salida += f"{d:010d} 00000 n \n".encode()
    salida += b"trailer<</Size " + str(len(objetos) + 1).encode() + b"/Root 1 0 R>>\n"
    salida += b"startxref\n" + str(xref).encode() + b"\n%%EOF\n"
    return bytes(salida)


def _pdf_mixto() -> bytes:
    """Dos páginas: la primera con texto, la segunda una imagen.

    Es lo normal en un expediente que agrega anexos escaneados a resoluciones digitales, y es
    el caso que un recorrido que corta en la primera página con texto no puede distinguir de
    un PDF enteramente digital.
    """
    con_texto = b"BT /F1 12 Tf 20 100 Td (RESOLUCION) Tj ET"
    sin_texto = b"0 0 100 100 re f"
    objetos = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R 4 0 R]/Count 2>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 5 0 R"
        b"/Resources<</Font<</F1 7 0 R>>>>>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 6 0 R/Resources<<>>>>",
        b"<</Length " + str(len(con_texto)).encode() + b">>stream\n" + con_texto + b"\nendstream",
        b"<</Length " + str(len(sin_texto)).encode() + b">>stream\n" + sin_texto + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    salida = bytearray(b"%PDF-1.4\n")
    desplazamientos = []
    for i, cuerpo in enumerate(objetos, start=1):
        desplazamientos.append(len(salida))
        salida += str(i).encode() + b" 0 obj" + cuerpo + b"endobj\n"
    xref = len(salida)
    salida += b"xref\n0 " + str(len(objetos) + 1).encode() + b"\n0000000000 65535 f \n"
    for d in desplazamientos:
        salida += f"{d:010d} 00000 n \n".encode()
    salida += b"trailer<</Size " + str(len(objetos) + 1).encode() + b"/Root 1 0 R>>\n"
    salida += b"startxref\n" + str(xref).encode() + b"\n%%EOF\n"
    return bytes(salida)


PDF_CON_TEXTO = _pdf(b"BT /F1 12 Tf 20 100 Td (RESOLUCION) Tj ET")
PDF_ESCANEADO = _pdf(b"0 0 100 100 re f", con_fuente=False)
PDF_MIXTO = _pdf_mixto()


def _cliente_de_documentos(respuesta: httpx.Response) -> tuple[PjudClient, list[httpx.Request]]:
    pedidas: list[httpx.Request] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidas.append(peticion)
        return respuesta

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32
    return c, pedidas


def test_la_tabla_de_documentos_es_la_que_emiten_las_respuestas_reales():
    """`DOCUMENTOS` dice con qué parámetro se pide cada documento, y eso NO se puede escribir
    de memoria: son cinco competencias que nombran lo mismo de siete maneras distintas.

    Pedir un documento con el nombre de parámetro de otra competencia no falla con un error:
    la plataforma responde una página, y una página guardada como PDF se ve como un documento.
    Por eso el guardia deriva la tabla entera de las fixtures y la compara, en las dos
    direcciones: una ruta que el sitio emite y la tabla no tiene es un documento que este
    servidor no puede entregar, y una que la tabla tiene y el sitio no emite es una inventada.
    """
    from mcp_pjud.client import DOCUMENTOS

    emitidas: dict[str, dict[str, str]] = {}
    for fixture in sorted(FIXTURES.glob("*.html")):
        html = fixture.read_text(encoding="utf-8")
        for formulario in re.finditer(
            r'<form[^>]*action="[^"]*?(\w+)/documentos/([\w.-]+\.php)"[^>]*>(.*?)</form>',
            html,
            re.S,
        ):
            modulo, ruta, cuerpo = formulario.groups()
            nombres = re.findall(r"""name=['"](\w+)['"]""", cuerpo)
            assert nombres, f"{fixture.name}: {ruta!r} ya no muestra con qué parámetro se pide"
            emitidas.setdefault(modulo, {})[ruta] = nombres[0]

    assert len(emitidas) >= 5, f"las fixtures dejaron de traer formularios: {sorted(emitidas)}"
    assert emitidas == DOCUMENTOS, (
        "la tabla de documentos del cliente ya no es la que emiten las respuestas guardadas.\n"
        f"Emiten: {emitidas}\nLa tabla dice: {DOCUMENTOS}"
    )


def test_una_ruta_que_la_plataforma_no_emite_se_rechaza_antes_de_consultar():
    """`documento_ruta` llega desde el modelo, así que es texto que este servidor no controla.

    Sin la lista blanca, la herramienta deja de entregar documentos de una causa y pasa a ser
    un proxy capaz de pedir cualquier `.php` del sitio bajo la sesión de este cliente, con su
    contacto en el User-Agent. Se rechaza sin gastar una petición.

    La tercera ruta de la lista es la trampa que una tabla plana no atraparía: existe, pero en
    otra competencia. Pedirla bajo el prefijo de civil es pedir una ruta que no existe.
    """
    c = _sin_red()
    for ruta in ("../../consultaUnificada.php", "docuInventado.php", "docCausaSuprema.php"):
        with pytest.raises(ValueError, match="no es una de las que el detalle"):
            c.documento(ruta, "referencia-cualquiera", "civil")


def test_una_competencia_sin_documentos_medidos_se_rechaza_antes_de_consultar():
    """`penal` no emite un solo formulario de descarga en su detalle. Armarle una ruta por
    analogía con civil devolvería una página de error, no un archivo."""
    c = _sin_red()
    with pytest.raises(ValueError, match="ninguna ruta de documentos"):
        c.documento("docuN.php", "referencia-cualquiera", "penal")


def test_el_documento_se_pide_con_el_parametro_que_esa_ruta_usa():
    """Cada competencia nombra el parámetro a su manera, y la ruta cuelga de su propio módulo.

    Sin esto, pedir el documento de una actuación de suprema con el nombre de civil manda
    `dtaDoc` donde el sitio espera `valorFile`, y lo que vuelve no es el documento.
    """
    c, pedidas = _cliente_de_documentos(
        httpx.Response(200, content=PDF_CON_TEXTO, headers={"content-type": "application/pdf"})
    )

    c.documento("docCausaSuprema.php", "ref-123", "suprema")

    url = pedidas[-1].url
    assert url.path.endswith("/ADIR_1/suprema/documentos/docCausaSuprema.php"), (
        f"la ruta se armó mal: {url}"
    )
    assert dict(url.params) == {"valorFile": "ref-123"}, (
        f"suprema pide el documento con `valorFile` y se mandó {dict(url.params)}"
    )


def test_un_pdf_con_texto_se_declara_con_capa_de_texto():
    c, _ = _cliente_de_documentos(
        httpx.Response(200, content=PDF_CON_TEXTO, headers={"content-type": "application/pdf"})
    )

    doc = c.documento("docuN.php", "ref-123")

    assert doc.capa_de_texto is True
    assert doc.paginas == 1
    assert doc.tamano_bytes == len(PDF_CON_TEXTO)
    assert doc.contenido == PDF_CON_TEXTO, "el documento tiene que llegar tal cual"


def test_un_pdf_sin_capa_de_texto_se_declara_escaneo_y_se_entrega_igual():
    """Detectarlo es barato y transcribirlo es lo que no corresponde.

    El documento se entrega igual: decir que es un escaneo no es negarse a darlo.
    """
    c, _ = _cliente_de_documentos(
        httpx.Response(200, content=PDF_ESCANEADO, headers={"content-type": "application/pdf"})
    )

    doc = c.documento("docuN.php", "ref-123")

    assert doc.capa_de_texto is False
    assert doc.contenido == PDF_ESCANEADO, "un escaneo se entrega igual, sólo que declarado"


def test_un_pdf_que_no_se_puede_abrir_no_se_declara_escaneo():
    """Es el falso positivo de esta herramienta, y es de los que no se notan.

    "No pude abrir el archivo" y "es un escaneo" son cosas distintas. Con `not capa_de_texto`
    en vez de `capa_de_texto is False`, un PDF cifrado o truncado se informaría como escaneo,
    o sea el servidor afirmaría sobre el documento algo que nunca midió. Es la misma familia
    de error que la lista vacía de la regla 4, con la diferencia de que acá la afirmación
    suena razonable.
    """
    truncado = PDF_CON_TEXTO[:120]
    assert truncado.startswith(b"%PDF-"), "tiene que pasar el control de magia para medir esto"
    c, _ = _cliente_de_documentos(
        httpx.Response(200, content=truncado, headers={"content-type": "application/pdf"})
    )

    doc = c.documento("docuN.php", "ref-123")

    assert doc.capa_de_texto is None, (
        "no se pudo abrir, así que no se sabe: FALSO acá sería declarar un escaneo que nadie midió"
    )
    assert doc.problema_al_leer, "hay que decir por qué no se pudo abrir"
    assert doc.contenido == truncado, "no poder describirlo no es no tenerlo"


def test_una_respuesta_que_no_es_pdf_no_se_entrega_como_documento():
    """La referencia caduca con la sesión, así que ésta es la respuesta que de verdad va a
    llegar cuando alguien guarde una y la use mañana.

    Y llega con HTTP 200. Entregarla en base64 produce un archivo que se ve como un documento
    y es una página de error, y quien lo reciba no tiene cómo notarlo.
    """
    aviso = '<html><script>swal("Aviso", "La sesion ha expirado");</script></html>'
    c, _ = _cliente_de_documentos(
        httpx.Response(200, text=aviso, headers={"content-type": "text/html"})
    )

    with pytest.raises(EstructuraInesperada) as levantada:
        c.documento("docuN.php", "ref-vencida")

    mensaje = str(levantada.value)
    assert "La sesion ha expirado" in mensaje, (
        f"el aviso es lo único que distingue una referencia vencida de un cambio del sitio, "
        f"y no viajó: {mensaje}"
    )
    assert "detalle" in mensaje, f"el mensaje tiene que decir qué hacer: {mensaje}"


def test_el_umbral_de_lo_embebido_no_gasta_mas_que_una_respuesta_de_texto():
    """El número no está medido contra ningún PDF, porque no hay ninguno medido: es una
    decisión, y lo que este guardia ata es su ARITMÉTICA contra el techo que la justifica.

    Sin esto, subir `LIMITE_EMBEBIDO` a un número cómodo dejaría todo verde y el ebook entero
    viajaría dentro de la respuesta.
    """
    from mcp_pjud.client import CARACTERES_DE_UNA_RESPUESTA, LIMITE_EMBEBIDO

    en_base64 = -(-LIMITE_EMBEBIDO // 3) * 4
    assert en_base64 <= CARACTERES_DE_UNA_RESPUESTA, (
        f"{LIMITE_EMBEBIDO} bytes son {en_base64} caracteres en base64, y el techo que este "
        f"servidor ya acepta gastar de una vez son {CARACTERES_DE_UNA_RESPUESTA}"
    )


def test_un_pdf_mixto_no_se_declara_entero_digital(monkeypatch):
    """Un expediente que mezcla resoluciones digitales con anexos escaneados es lo normal.

    Cortar en la primera página con texto hacía que una sola declarara todo el archivo
    digital, y quien leyera eso daría por transcribible un documento del que una parte son
    imágenes. Es el falso negativo de siempre, repartido por página.
    """
    from mcp_pjud.client import _describir_pdf

    paginas, con_texto, problema = _describir_pdf(PDF_MIXTO)
    assert problema is None, problema
    assert paginas == 2, paginas
    assert con_texto == 1, (
        f"se extrajo texto de {con_texto} de {paginas} páginas, y el documento es mixto"
    )


# -- georreferencia ------------------------------------------------------------------


def test_la_georreferencia_se_pide_a_la_ruta_de_su_competencia(monkeypatch):
    """Cada competencia tiene su propio modal, y pedirle a la de civil una referencia de
    laboral no da un error claro: da una página que no es la que se pidió."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    pedidas: list[tuple[str, bytes]] = []
    cuerpo = (FIXTURES / "georreferencia_civil.html").read_text(encoding="utf-8")

    def transporte(peticion: httpx.Request) -> httpx.Response:
        pedidas.append((str(peticion.url), peticion.content))
        return httpx.Response(200, text=cuerpo)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    c.georreferencia("REF-1", "laboral")

    url, contenido = pedidas[0]
    assert "laboral/modal/geoReferenciaLaboral.php" in url, url
    assert b"valGeoRef=REF-1" in contenido, contenido


def test_pedir_la_georreferencia_de_una_competencia_que_no_la_publica_no_gasta_peticion(
    monkeypatch,
):
    """Suprema no publica la columna en su Historia, así que nunca va a haber una referencia
    que pedir. Se rechaza antes de consultar en vez de armar una ruta por analogía."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    salieron = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        salieron.append(str(peticion.url))
        return httpx.Response(200, text="")

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    with pytest.raises(EstructuraInesperada, match="no publica la columna"):
        c.georreferencia("REF-1", "suprema")
    assert not salieron, "no debe salir ninguna petición para una competencia sin la columna"


def test_una_competencia_sin_historia_medida_no_se_rechaza_como_si_no_publicara(monkeypatch):
    """Penal y Suprema se rechazan igual, pero por razones distintas y no se pueden decir con
    la misma frase. De Suprema está medido que su Historia no trae la columna; de Penal no hay
    Historia medida, así que afirmar que no la publica sería publicar un negativo que nadie
    verificó, con la ruta declarada al lado."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    salieron = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        salieron.append(str(peticion.url))
        return httpx.Response(200, text="")

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    with pytest.raises(EstructuraInesperada) as e:
        c.georreferencia("REF-1", "penal")
    dicho = str(e.value)
    assert "no está medida" in dicho, "el rechazo de penal debe decir que no se midió"
    assert "no publica la columna" not in dicho, (
        "penal no tiene Historia medida: decir que no publica la columna afirma una medición "
        "que no existe"
    )
    assert not salieron, "no debe salir ninguna petición"


def test_la_referencia_de_georreferencia_llega_desde_la_actuacion():
    """El circuito completo sin red: la actuación trae con qué pedir su georreferencia.

    Sin esto la herramienta existe y no hay de dónde sacar su parámetro, que es el mismo hueco
    que tenía `tiene_documento` antes de traer la referencia.
    """
    from mcp_pjud.parser import parse_historia

    detalle = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    con_geo = [a for a in parse_historia(detalle) if a.georreferenciado]
    assert con_geo, "la fixture dejó de traer actuaciones georreferenciadas"
    assert all(a.georreferencia_referencia for a in con_geo), (
        "una actuación dice tener georreferencia y no dice con qué pedirla"
    )
    referencias = [a.georreferencia_referencia for a in con_geo]
    assert len(set(referencias)) == len(referencias), (
        f"dos actuaciones comparten referencia de georreferencia: {referencias}"
    )
