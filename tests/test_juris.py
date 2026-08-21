"""Tests del buscador de fallos. Sin red: las fixtures son respuestas reales anonimizadas."""

import json
from pathlib import Path

import httpx
import pytest

from mcp_pjud.juris import (
    BUSCADORES,
    INDISPENSABLES,
    JurisClient,
    parse_sentencias,
)
from mcp_pjud.parser import EstructuraInesperada, PlataformaRechaza

FIXTURES = Path(__file__).parent / "fixtures"
AMPLIA = (FIXTURES / "juris_busqueda_amplia.json").read_text(encoding="utf-8")
CITA = (FIXTURES / "juris_cita_unica.json").read_text(encoding="utf-8")
PARCIAL = (FIXTURES / "juris_pagina_parcial.json").read_text(encoding="utf-8")


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


def test_una_pagina_parcial_lo_declara_aunque_no_haya_nada_reservado():
    """El falso negativo que `ocultas` no cubre: 400 visibles, nada reservado, y la llamada
    trae tres. Leer sólo `ocultas` da cero y se entiende como lista completa."""
    r = parse_sentencias(PARCIAL)
    assert r.ocultas == 0, "la fixture debe tener el recorte SIN nada reservado detrás"
    assert (r.visibles, len(r.sentencias)) == (400, 3)
    assert r.no_entregadas == 397


def test_una_cita_completa_no_declara_recorte():
    """El otro lado del guardia: si vino todo lo visible, no hay nada que advertir."""
    assert parse_sentencias(CITA).no_entregadas == 0


def test_el_recorte_se_declara_donde_ocultas_viene_en_nulo():
    """`ocultas` es nulo en dos de los tres buscadores, así que ahí `no_entregadas` es la
    única señal de que la lista es un subconjunto."""
    r = parse_sentencias(PARCIAL, "laborales")
    assert r.ocultas is None
    assert r.no_entregadas == 397


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
    c._buscador_de_la_sesion = "suprema"
    return c


def test_buscar_sin_criterios_se_rechaza_antes_de_consultar():
    """Sin criterio el buscador devuelve el índice entero. Eso no es una búsqueda."""
    with pytest.raises(ValueError, match="al menos un criterio"):
        _sin_red().buscar()


def test_un_buscador_no_verificado_se_rechaza():
    """Cada buscador declara sus propios campos Solr. Exponer los no medidos devolvería
    campos vacíos en vez de un error.

    Se prueba con un nombre que no existe en vez de con uno de los nueve pendientes: la lista
    de verificados crece, y un test que nombre uno concreto se cae al verificarlo, que es
    justo cuando no debería.
    """
    assert "compendio_extranjeria" not in BUSCADORES
    with pytest.raises(ValueError, match="no verificado"):
        _sin_red().abrir_sesion("compendio_extranjeria")


def test_cada_buscador_declara_los_campos_indispensables():
    """Sin rol y fecha no se puede verificar una cita, que es para lo que existe esto."""
    for nombre, b in BUSCADORES.items():
        for campo in INDISPENSABLES:
            assert campo in b.campos, f"{nombre} no declara el campo {campo!r}"


def test_apelaciones_identifica_sus_sentencias_con_otro_campo_que_suprema():
    """Es la razón concreta por la que esto es una tabla y no un parser.

    Un cliente que asumiera los campos de Suprema devolvería el rol vacío en Apelaciones sin
    que nada reviente, o sea una cita que no dice a qué sentencia corresponde.
    """
    assert BUSCADORES["suprema"].campos["rol"] == "rol_era_sup_s"
    assert BUSCADORES["apelaciones"].campos["rol"] == "rol_era_ape_s"
    # Y en Laborales el origen es un juzgado, no una corte.
    assert BUSCADORES["laborales"].campos["corte_origen"] == "gls_juz_s"


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
    c._buscador_de_la_sesion = "suprema"
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


# -- el texto completo, que se pide aparte ----------------------------------------


def _con_respuesta(cuerpo: str) -> JurisClient:
    c = JurisClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=cuerpo))
    )
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"
    return c


def _con_texto(texto: str, anonimizada: int = 0, anon: str = "ANONIMIZADO") -> str:
    d = json.loads(CITA)
    d["response"]["docs"][0]["texto_sentencia"] = texto
    d["response"]["docs"][0]["texto_sentencia_anon"] = anon
    d["response"]["docs"][0]["sit_fallo_anonimizado_i"] = anonimizada
    d["response"]["docs"][0]["sent__word_count_i"] = 3881
    d["response"]["docs"][0]["sent__npages_i"] = 13
    return json.dumps(d, ensure_ascii=False)


def test_el_texto_no_viaja_en_la_busqueda(monkeypatch):
    """Una sentencia de trece páginas son unos 25.000 caracteres, medido. Diez por búsqueda
    serían 250.000, así que `Sentencia` lleva el preview y no el fallo."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _con_respuesta(_con_texto("X" * 25473))
    s = c.buscar(rol=34546, anio=2025).sentencias[0]
    assert "texto" not in s.model_dump(), "el texto completo no puede viajar en cada fila"
    # La extensión sí viaja: es lo que permite decidir si pedir el resto.
    assert s.palabras == 3881
    assert s.paginas == 13


def test_el_texto_completo_dice_de_cual_de_los_dos_campos_salio(monkeypatch):
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _con_respuesta(_con_texto("Santiago, a catorce de agosto."))
    t = c.texto(rol=34546, anio=2025)
    assert t.anonimizada is False
    assert t.fuente == "texto_sentencia"
    assert t.texto.startswith("Santiago")
    assert (t.palabras, t.paginas) == (3881, 13)


def test_un_fallo_anonimizado_entrega_la_version_anonimizada(monkeypatch):
    """Cuando el tribunal anonimizó el fallo, lo publicado es la otra columna. Entregar la
    primera devolvería el marcador `ANONIMIZADO` como si fuera el texto."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _con_respuesta(
        _con_texto("ANONIMIZADO", anonimizada=1, anon="Santiago, a catorce. NOMBRE SUPRIMIDO.")
    )
    t = c.texto(rol=34546, anio=2025)
    assert t.anonimizada is True
    assert t.fuente == "texto_sentencia_anon"
    assert "SUPRIMIDO" in t.texto


def test_pedir_el_texto_de_una_sentencia_reservada_no_devuelve_vacio(monkeypatch):
    """`ocultas` mayor que cero significa que existe y no se publica. Devolver una cadena
    vacía se leería como una sentencia sin contenido."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    d["response"]["docs"] = []
    d["response"]["numFound"] = 0
    d["condition_pub_sf"]["numFound_sf"] = 1
    c = _con_respuesta(json.dumps(d))
    with pytest.raises(PlataformaRechaza, match="reservada"):
        c.texto(rol=34546, anio=2025)


def test_pedir_el_texto_de_una_sentencia_inexistente_se_distingue_de_una_reservada(monkeypatch):
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    d["response"]["docs"] = []
    d["response"]["numFound"] = 0
    d["condition_pub_sf"]["numFound_sf"] = 0
    c = _con_respuesta(json.dumps(d))
    with pytest.raises(EstructuraInesperada, match="reservada"):
        c.texto(rol=34546, anio=2025)


def test_una_sentencia_sin_el_campo_de_texto_se_levanta(monkeypatch):
    """Devolver una cadena vacía se leería como una sentencia sin contenido, y una sentencia
    sin contenido no existe: si el campo falta, el buscador cambió."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _con_respuesta(_con_texto(""))
    with pytest.raises(EstructuraInesperada, match="texto_sentencia"):
        c.texto(rol=34546, anio=2025)


def test_el_rol_de_laborales_no_lleva_la_letra_del_tipo_de_causa():
    """Medido: pedir el rol 364 del año 2020 devuelve `O-364-2020` aunque lo buscado sea
    `T-364-2020`. El campo del buscador no separa los tipos.

    Se fija acá porque es un falso positivo silencioso: una respuesta con el mismo número
    parece confirmar la cita y puede ser otra causa. Si alguien decide filtrar por tipo, este
    test es donde se documenta que el buscador no lo hace por él.
    """
    assert BUSCADORES["laborales"].campos["rol"] == "rol_era_sup_s"
    fuente = (Path(__file__).parents[1] / "src" / "mcp_pjud" / "juris.py").read_text(
        encoding="utf-8"
    )
    assert "NO lleva la letra del tipo de causa" in fuente, (
        "se borró la advertencia que registra que el rol de laborales no distingue tipos"
    )


# -- ocultas no significa lo mismo en todos los buscadores ------------------------


def test_ocultas_viene_en_nulo_donde_el_numero_cuenta_el_corpus():
    """Medido: en `laborales`, `numFound_sf` da 269.264 tanto para un rol que existe como para
    uno imposible, o sea es el tamaño del índice y no la consulta.

    Informar 269.256 ocultas para una consulta que encontró 8 haría ver cada resultado como
    una fracción de un universo oculto que no existe. Un campo que miente es peor que un campo
    ausente, así que viene en nulo.
    """
    assert BUSCADORES["suprema"].coincidencias_por_consulta is True
    assert BUSCADORES["laborales"].coincidencias_por_consulta is False
    # Apelaciones se midió igual y dio lo mismo: 5.290.009 para el rol que existe y para el
    # imposible. Estaba en falso por prudencia y resultó estar en falso por medición.
    assert BUSCADORES["apelaciones"].coincidencias_por_consulta is False

    d = json.loads(CITA)
    d["condition_pub_sf"]["numFound_sf"] = 269264
    cuerpo = json.dumps(d)

    en_suprema = parse_sentencias(cuerpo, "suprema")
    assert en_suprema.coincidencias == 269264
    assert en_suprema.ocultas == 269263

    en_laborales = parse_sentencias(cuerpo, "laborales")
    assert en_laborales.coincidencias is None, "no se informa lo que no está medido"
    assert en_laborales.ocultas is None, "nulo no es cero: es 'acá no se puede saber'"


def test_pedir_el_texto_donde_no_se_puede_saber_lo_dice(monkeypatch):
    """Sin resultados en `laborales` no prueba que la sentencia no exista, porque ahí no se
    puede distinguir de una reservada. El error tiene que decirlo en vez de afirmar."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    d["response"]["docs"] = []
    d["response"]["numFound"] = 0
    c = _con_respuesta(json.dumps(d))
    c._buscador_de_la_sesion = "laborales"
    with pytest.raises(EstructuraInesperada, match="no prueba que"):
        c.texto(rol=364, anio=2020, buscador="laborales")


def test_las_visibles_salen_de_response_y_las_coincidencias_del_desglose():
    """Son dos campos distintos y confundirlos lleva a la conclusión contraria.

    `response.numFound` son las VISIBLES y siguen a la consulta en los tres buscadores, incluso
    donde la bandera es falsa: medirlo en apelaciones da 18 para un rol que existe y 0 para uno
    imposible, y de ahí se concluiría "es por consulta" justo donde no lo es. El campo que
    decide es `condition_pub_sf.numFound_sf`, que ahí vale 5.290.009 en los dos casos.

    Este guardia los ata a su origen: si alguien intercambia las dos lecturas, `ocultas` pasa a
    restar contra el corpus y ninguno de los otros tests se entera.
    """
    d = json.loads(CITA)
    d["response"]["numFound"] = 7
    d["condition_pub_sf"]["numFound_sf"] = 31
    r = parse_sentencias(json.dumps(d), "suprema")

    assert r.visibles == 7, "las visibles salen de response.numFound"
    assert r.coincidencias == 31, "las coincidencias salen de condition_pub_sf.numFound_sf"
    assert r.ocultas == 24
