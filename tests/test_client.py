"""Tests del cliente. Sin red: los controles se prueban con dobles."""

import re
from pathlib import Path

import httpx
import pytest

from mcp_pjud.client import (
    INTERVALO_MINIMO,
    RAFAGA_MAXIMA,
    PjudBloqueado,
    PjudClient,
)
from mcp_pjud.parser import EstructuraInesperada, parse_resultados

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


def test_competencia_que_existe_pero_no_se_verifico_se_rechaza():
    """Saber leer una competencia y haberla probado son cosas distintas.

    `parser.COMPETENCIAS` sabe leer las seis; `MODULOS` dice cuáles se midieron. Exponer la
    primera lista como si fuera la segunda es adivinar, y una consulta mal armada devuelve
    vacío, que se lee como que la causa no existe.
    """
    c = PjudClient("test@example.cl")
    with pytest.raises(ValueError, match="no verificada"):
        c._modulo("penal")


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

    acts = c.actuaciones_receptor("C", 1156, 2026, tribunal=162)
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


def _fila(n: int) -> str:
    return (
        f"<tr><td align='center'><a onClick=\"detalleCausaCivil('ref-{n:03d}')\">"
        f"</a></td><td nowrap>C-{9000 + n}-2026</td><td>01/03/2026</td>"
        f"<td>PARTE FICTICIA/CONTRAPARTE FICTICIA</td>"
        f"<td nowrap>2º Juzgado Civil de Concepción</td></tr>"
    )


def _pagina(filas: range, total: int, ultima: bool, token: str = "") -> str:
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
    cuerpo = "".join(_fila(n) for n in filas)
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
    """De todo el listado sólo se usa la primera causa.

    Recorrer hasta el tope gastaría hasta nueve peticiones y cuarenta y cinco segundos
    contra la plataforma para descartarlas. El ritmo de consulta no es un parámetro de
    rendimiento acá.
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

    c.actuaciones_receptor("C", 1156, 2026, tribunal=162)
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


def test_pedir_actuaciones_de_una_competencia_sin_panel_mapeado_no_gasta_peticiones():
    """Cobranza sí tiene receptor y su panel `historiaCob` existe, pero sus columnas son
    otras: trae `Estado Firma` y no trae `Foja` ni `Georref.`. Leerla con el mapa de civil
    daría filas mal alineadas."""
    c = _sin_red()
    with pytest.raises(ValueError, match="No está verificado"):
        c.actuaciones_receptor("C", 208, 2019, competencia="cobranza")


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
