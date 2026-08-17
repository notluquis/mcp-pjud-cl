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
    # Sólo que exista. Antes se comprobaba el largo, que ataba el test al tamaño de los
    # identificadores reales de la plataforma y se cayó al anonimizarlos.
    assert c.referencia


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
