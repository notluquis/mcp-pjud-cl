"""Tests del buscador de fallos. Sin red: las fixtures son respuestas reales anonimizadas."""

import json
from pathlib import Path

import httpx
import pytest

from mcp_pjud.juris import BUSCADORES, JurisClient, parse_sentencias
from mcp_pjud.parser import EstructuraInesperada

FIXTURES = Path(__file__).parent / "fixtures"
AMPLIA = (FIXTURES / "juris_busqueda_amplia.json").read_text(encoding="utf-8")
CITA = (FIXTURES / "juris_cita_unica.json").read_text(encoding="utf-8")


# -- lo que el buscador no muestra ----------------------------------------------
#
# Una consulta anónima recibe bastante menos de lo que hay indexado, y el sitio dejó de
# decirlo: los dos mensajes que lo avisaban siguen comentados en su JavaScript. Si el
# resultado no trae ese número, se lee como el universo completo.


def test_declara_cuantas_coincidencias_quedaron_ocultas():
    r = parse_sentencias(AMPLIA)
    assert r.visibles == 300005
    assert r.coincidencias == 1223925
    assert r.ocultas == 923920, "la diferencia tiene que llegar al modelo, no quedarse en el JSON"


def test_desglosa_todas_las_coincidencias_por_condicion_de_publicacion():
    """El desglose es la partición COMPLETA: suma `coincidencias`, no `ocultas`.

    Presentarlo como "por qué están ocultas" haría leer las 232.021 'Publicable' como
    retenidas, que es exactamente lo contrario de lo que son.
    """
    r = parse_sentencias(AMPLIA)
    assert r.condiciones_de_publicacion["Reservado restringido"] == 6677
    assert r.condiciones_de_publicacion["Anonimizadas"] == 20924


def test_una_cita_verificada_no_declara_ocultas():
    """El caso que importa: rol y año que existen, sin nada reservado detrás."""
    r = parse_sentencias(CITA)
    assert (r.visibles, r.coincidencias, r.ocultas) == (1, 1, 0)
    assert len(r.sentencias) == 1


def test_sin_el_total_del_indice_se_levanta_en_vez_de_afirmar_completitud():
    """Sin `numFound_sf` no se puede saber cuánto falta.

    Devolver la lista igual sería presentarla como completa sin fundamento, que es
    exactamente lo que este proyecto existe para no hacer.
    """
    d = json.loads(AMPLIA)
    del d["condition_pub_sf"]["numFound_sf"]
    with pytest.raises(EstructuraInesperada, match="numFound_sf"):
        parse_sentencias(json.dumps(d))


# -- campos de la sentencia ------------------------------------------------------


def test_la_fecha_queda_en_iso_y_no_en_el_formato_de_pantalla():
    """Su JS reescribe la fecha a DD-MM-AAAA para mostrarla. Quien consume esto es un
    programa: se conserva ISO 8601."""
    s = parse_sentencias(CITA).sentencias[0]
    assert s.fecha_sentencia is not None
    assert s.fecha_sentencia.isoformat() == "2026-08-14"


def test_extrae_los_datos_de_cita():
    s = parse_sentencias(CITA).sentencias[0]
    assert s.rol == "34546-2025"
    assert s.sala == "SEGUNDA, PENAL"
    assert s.corte_origen == "C.A. de Santiago"
    assert s.rol_corte_apelaciones == "706-2023"
    assert s.ministros == ["MINISTRA FICTICIA UNO", "MINISTRO FICTICIO DOS"]
    assert s.condicion_publicacion == "Con interes jurisprudencial, no anonimizable"


# -- fallo ruidoso ---------------------------------------------------------------


def test_una_respuesta_que_no_es_json_se_levanta():
    with pytest.raises(EstructuraInesperada, match="no devolvió JSON"):
        parse_sentencias("<html>mantención</html>")


def test_una_respuesta_sin_docs_se_levanta():
    with pytest.raises(EstructuraInesperada, match=r"response\.docs"):
        parse_sentencias('{"algo": "distinto"}')


# -- validación antes de consultar -----------------------------------------------


def _sin_red() -> JurisClient:
    c = JurisClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("no debía consultar"))
    )
    c._token, c._id_buscador = "tok", "528"
    return c


def test_buscar_sin_criterios_se_rechaza_antes_de_consultar():
    """Sin criterio el buscador devuelve el índice entero. Eso no es una búsqueda."""
    with pytest.raises(ValueError, match="al menos un criterio"):
        _sin_red().buscar()


def test_un_buscador_no_verificado_se_rechaza():
    """Cada buscador declara sus propios campos Solr. Exponer los no medidos devolvería
    campos vacíos en vez de un error."""
    assert "apelaciones" not in BUSCADORES
    with pytest.raises(ValueError, match="no verificado"):
        _sin_red().abrir_sesion("apelaciones")


def test_solo_se_envian_los_filtros_con_valor(monkeypatch):
    """Medido contra el sistema real: mandar el juego completo de claves vacías que arma su
    propio formulario hace que el servidor responda 500."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    enviados = {}

    def transporte(req):
        cuerpo = req.content.decode("utf-8", "replace")
        m = cuerpo.split('name="filtros"')[1].split("\r\n\r\n")[1].split("\r\n")[0]
        enviados.update(json.loads(m))
        return httpx.Response(200, text=CITA)

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._token, c._id_buscador = "tok", "528"
    c.buscar(rol=34546, anio=2025)

    assert enviados == {"rol": "34546", "era": "2025"}, "no deben viajar claves vacías"


def test_sesion_sin_token_derivable_se_levanta(monkeypatch):
    """Mismo criterio que el prefijo de rutas de la Oficina Judicial Virtual: si el sitio
    cambió, hay que enterarse en vez de consultar rutas muertas."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = JurisClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="<html>otro</html>"))
    )
    with pytest.raises(EstructuraInesperada, match="token de sesión"):
        c.abrir_sesion()


def test_sin_numFound_se_levanta_en_vez_de_contar_cero():
    """Con un valor por defecto, que el campo desaparezca produce `visibles = 0` junto a una
    lista de sentencias que sí llegó, y `ocultas` pasa a ser una resta contra cero: una cifra
    inventada con apariencia de medida."""
    d = json.loads(AMPLIA)
    del d["response"]["numFound"]
    with pytest.raises(EstructuraInesperada, match="numFound"):
        parse_sentencias(json.dumps(d))


@pytest.mark.parametrize("campo", ["rol_era_sup_s", "fec_sentencia_sup_dt"])
def test_una_sentencia_sin_lo_que_la_identifica_se_levanta(campo):
    """Una `Sentencia` con `rol=""` llegaría como cita verificada sin decir a qué sentencia
    corresponde, en una herramienta cuyo propósito es verificar citas."""
    d = json.loads(CITA)
    del d["response"]["docs"][0][campo]
    with pytest.raises(EstructuraInesperada, match=campo):
        parse_sentencias(json.dumps(d))
