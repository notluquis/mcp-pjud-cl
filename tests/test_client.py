"""Tests del cliente. Sin red: los controles se prueban con dobles."""

from pathlib import Path

import httpx
import pytest

from mcp_pjud.client import INTERVALO_MINIMO, PjudBloqueado, PjudClient
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


def test_espera_entre_peticiones(monkeypatch):
    reloj = [100.0]
    dormido = []
    monkeypatch.setattr("mcp_pjud.client.time.monotonic", lambda: reloj[0])
    monkeypatch.setattr("mcp_pjud.client.time.sleep", dormido.append)

    c = PjudClient("test@example.cl")
    c._ultima = reloj[0] - 1.0  # pasó 1 s desde la última consulta
    c._esperar()

    assert dormido == [pytest.approx(INTERVALO_MINIMO - 1.0)]


def test_no_espera_si_ya_paso_el_intervalo(monkeypatch):
    monkeypatch.setattr("mcp_pjud.client.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: pytest.fail("no debía dormir"))

    c = PjudClient("test@example.cl")
    c._ultima = 100.0 - (INTERVALO_MINIMO + 1)
    c._esperar()


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


def test_sesion_sin_prefijo_derivable_se_detiene(monkeypatch):
    """Si el sitio cambia y ya no se puede derivar el prefijo, detenerse.
    Consultar rutas que ya no existen produciría falsos negativos."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _cliente(httpx.Response(200, text="<html>rediseñado</html>"))
    with pytest.raises(PjudBloqueado, match="prefijo"):
        c.abrir_sesion()


def test_competencia_no_verificada_se_rechaza():
    c = PjudClient("test@example.cl")
    with pytest.raises(ValueError, match="no implementada"):
        c._modulo("familia")


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
    assert parse_resultados(
        "<tr><td colspan='8'>No se han encontrado resultados con los datos ingresados.</td></tr>"
    ) == []


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
# "siguiente" trae el token de la página que viene. Medido: 251 resultados llegaron en
# tres páginas de 100, 100 y 51, sin solapamiento.


PAGINADA = (FIXTURES / "busqueda_paginada.html").read_text(encoding="utf-8")


def test_detecta_el_token_de_la_pagina_siguiente():
    from mcp_pjud.parser import siguiente_pagina, total_declarado

    assert siguiente_pagina(PAGINADA)
    assert total_declarado(PAGINADA) == 251


def test_ultima_pagina_no_tiene_siguiente():
    from mcp_pjud.parser import siguiente_pagina

    sin_control = (FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8")
    assert siguiente_pagina(sin_control) is None


def test_recorre_las_paginas_y_acumula(monkeypatch):
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    ultima = (FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8")
    entregadas = []

    def transporte(req: httpx.Request) -> httpx.Response:
        entregadas.append("pagina=" in req.content.decode())
        # Dos páginas con control de siguiente, y una final sin él.
        return httpx.Response(200, text=PAGINADA if len(entregadas) < 3 else ultima)

    c = PjudClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._adir, c._token = "ADIR_1", "0" * 32

    causas = c.buscar_por_rit("C", 1156, 2026)
    # 3 + 3 de las paginadas, más 1 de la última.
    assert len(causas) == 7
    # La primera petición va sin token; las siguientes lo llevan.
    assert entregadas == [False, True, True]


def test_el_tope_de_paginas_levanta_en_vez_de_recortar(monkeypatch):
    """Una lista recortada en silencio se leería como "no hay más resultados"."""
    from mcp_pjud.client import ResultadosTruncados

    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = PjudClient("test@example.cl")
    # Siempre hay una página más: sin tope, esto no terminaría nunca.
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=PAGINADA))
    )
    c._adir, c._token = "ADIR_1", "0" * 32

    with pytest.raises(ResultadosTruncados, match="tope de 3 páginas"):
        c.buscar_por_rit("C", 1156, 2026, paginas=3)
    assert c.truncado is True
