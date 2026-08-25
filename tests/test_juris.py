"""Tests del buscador de fallos. Sin red: las fixtures son respuestas reales anonimizadas."""

import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest

from mcp_pjud.juris import (
    BUSCADORES,
    INDISPENSABLES,
    PALABRAS_DE_LA_CASACION,
    JurisClient,
    Sentencia,
    _lista,
    buscadores_que_publican,
    parse_sentencias,
)
from mcp_pjud.parser import EstructuraInesperada, PlataformaRechaza

from .conftest import CARACTERES_DE_UNA_SENTENCIA

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


def test_el_desglose_va_en_nulo_donde_cuenta_el_indice_entero():
    """El mismo campo decía dos cosas distintas según el buscador.

    Medido el 25 de agosto de 2026: en suprema, una consulta de 2 coincidencias desglosa 2. En
    apelaciones, una de 28 visibles desglosa 5.295.308, o sea el índice completo. La
    descripción del campo dice "todas las COINCIDENCIAS", así que ahí estaría diciendo que la
    búsqueda coincidió con cinco millones.

    Es la misma decisión que ya rige para `coincidencias` y `ocultas`: donde el número cuenta
    el corpus, va en nulo.
    """
    from mcp_pjud.juris import BUSCADORES

    por_consulta = sorted(n for n, b in BUSCADORES.items() if b.coincidencias_por_consulta)
    del_corpus = sorted(n for n, b in BUSCADORES.items() if not b.coincidencias_por_consulta)
    assert por_consulta, "ningún buscador cuenta por consulta"
    assert del_corpus, "ninguno cuenta el corpus, así que este guardia no distingue nada"

    r = parse_sentencias(AMPLIA, buscador=del_corpus[0])
    assert r.condiciones_de_publicacion is None, (
        f"en {del_corpus[0]} el desglose cuenta el índice entero y se entrega igual: "
        f"{r.condiciones_de_publicacion}"
    )
    assert r.coincidencias is None, "y su cuenta de coincidencias ya iba en nulo por lo mismo"


def test_desglosa_todas_las_coincidencias_por_condicion_de_publicacion():
    """El desglose es la partición COMPLETA: suma `coincidencias`, no `ocultas`.

    Presentarlo como "por qué están ocultas" haría leer las 232.021 'Publicable' como
    retenidas, que es exactamente lo contrario de lo que son.
    """
    r = parse_sentencias(AMPLIA)
    assert r.condiciones_de_publicacion is not None, (
        "el desglose vino en nulo en un buscador donde la cuenta SÍ es de la consulta"
    )
    assert r.condiciones_de_publicacion["Reservado restringido"] == 6677
    assert r.condiciones_de_publicacion["Anonimizadas"] == 20924


def test_cada_campo_de_la_sentencia_sale_del_campo_solr_que_le_toca():
    """Cinco campos se podían anular sin que la suite lo notara, encontrados con mutación.

    `anonimizada` es el que más pesa: dice qué versión del fallo se entregó, y en falso permite
    reproducir nombres de personas naturales que la versión anonimizada suprime. Los otros
    cuatro son los que hacen útil una cita verificada: sin `url` no hay a dónde ir a mirarla, y
    sin `resultado_recurso` la sentencia no dice si el recurso se acogió.
    """
    s = parse_sentencias(AMPLIA).sentencias[0]
    assert s.rol == "34546-2025"
    assert s.url == "https://juris.pjud.cl/busqueda/pagina_detalle_sentencia/?k=ficticia1"
    assert s.resultado_recurso == "ACOGIDO RECURSO DE QUEJA (M)"
    assert s.redactor == "Ministro no Identificado"
    assert s.anonimizada is False, (
        "el campo dice qué versión se entregó: en falso se pueden reproducir nombres que la "
        "versión anonimizada suprime"
    )


def test_el_desglose_es_la_particion_entera_y_no_le_falta_el_ultimo_tramo():
    """La suma es la prueba de que la partición está completa, y nadie la comprobaba.

    Encontrado con testing de mutación: recortar el recorrido en un par dejaba fuera la última
    condición y la suite seguía verde, porque los dos únicos valores comprobados estaban en el
    medio. Con un tramo menos el desglose sigue pareciendo razonable y ya no suma.
    """
    r = parse_sentencias(AMPLIA)
    assert r.condiciones_de_publicacion is not None, "el desglose vino en nulo"
    assert sum(r.condiciones_de_publicacion.values()) == r.coincidencias
    assert "Reservadas por motivos distintos a protección datos personales" in (
        r.condiciones_de_publicacion
    ), "el último tramo del desglose se cayó del recorrido"

    # Una condición con UNA coincidencia es una condición, y la fixture de la cita trae
    # exactamente eso: exigir más de una la borraría del desglose.
    assert parse_sentencias(CITA).condiciones_de_publicacion == {
        "Con interes jurisprudencial, no anonimizable": 1
    }


def test_una_condicion_en_cero_no_entra_al_desglose():
    """Cero no es un tramo: es una categoría que el buscador declara y esta consulta no toca.

    Publicarla haría leer un desglose con filas que no aportan, y en una respuesta que se usa
    para decidir si falta algo, cada fila de más es ruido sobre el dato que importa.
    """
    datos = json.loads(AMPLIA)
    datos["condition_pub_sf"]["counts"].extend(["Categoría que esta consulta no toca", 0])

    condiciones = parse_sentencias(json.dumps(datos)).condiciones_de_publicacion
    assert condiciones is not None, "el desglose vino en nulo"
    assert "Categoría que esta consulta no toca" not in condiciones
    assert 0 not in condiciones.values()


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


def test_un_total_menor_que_su_propia_pagina_se_levanta():
    """Si `numFound` viniera por debajo de las sentencias que lo acompañan, la resta daría
    negativo y el tope en cero la publicaría como lista completa. Es una respuesta rota, y
    leerla como completa es el falso negativo que este campo vino a cerrar."""
    datos = json.loads(PARCIAL)
    datos["response"]["numFound"] = 2
    with pytest.raises(EstructuraInesperada, match="menor que su propia página"):
        parse_sentencias(json.dumps(datos))


def test_una_cita_completa_no_declara_recorte():
    """El otro lado del guardia: si vino todo lo visible, no hay nada que advertir."""
    assert parse_sentencias(CITA).no_entregadas == 0


def test_el_recorte_se_declara_donde_ocultas_viene_en_nulo():
    """`ocultas` es nulo en todos los buscadores menos `suprema`, así que ahí `no_entregadas`
    es la única señal de que la lista es un subconjunto."""
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


CIVILES = (FIXTURES / "juris_civiles.json").read_text(encoding="utf-8")


def test_el_buscador_de_civiles_trae_el_juzgado_y_el_rol_con_su_letra():
    """Medido el 23-08-2026. Dos cosas lo separan de los otros tres, y las dos importan para
    verificar una cita.

    Su rol SÍ lleva la letra del tipo de causa (`C-528-2025`), al revés que laborales, donde
    pedir el 364 de 2020 devuelve el `O-364-2020` que es otra causa. Y su origen es un juzgado,
    no una corte, así que `corte_origen` cambia de significado aunque el campo del modelo sea
    el mismo.
    """
    r = parse_sentencias(CIVILES, "civiles")

    assert r.visibles == 38757
    assert [s.rol for s in r.sentencias][:2] == ["C-528-2025", "C-1455-2022"]
    assert r.sentencias[0].corte_origen == "1º Juzgado de Letras de Osorno"
    fecha = r.sentencias[0].fecha_sentencia
    assert fecha is not None, "la fecha es indispensable: sin ella la cita no se puede verificar"
    assert fecha.isoformat() == "2026-08-17"


def test_en_civiles_el_desglose_cuenta_el_corpus_y_no_la_consulta():
    """Medido con dos consultas: 954.129 para una búsqueda con 38.757 coincidencias y el mismo
    número para un rol imposible con cero.

    Por eso `ocultas` viene en nulo: informar la resta sería dar por medido que ese número
    cuenta esta consulta, y cuenta el índice entero.
    """
    r = parse_sentencias(CIVILES, "civiles")

    assert r.coincidencias is None
    assert r.ocultas is None
    assert r.no_entregadas == 38754, "las visibles que esta página no trajo siguen contándose"


COBRANZA = (FIXTURES / "juris_cobranza.json").read_text(encoding="utf-8")
SALUD = (FIXTURES / "juris_salud.json").read_text(encoding="utf-8")


def test_salud_es_el_unico_de_los_juzgados_con_la_forma_de_suprema():
    """Cinco de los seis verificados traen el juzgado y nada más. Salud CS trae corte, sala,
    tipo de recurso, resultado y el rol de la causa de apelaciones: es un compendio de la Corte
    Suprema, no de un juzgado.

    Leerlo con el mapa de cobranza dejaría esos cinco campos vacíos sin que nada lo diga.
    """
    salud = parse_sentencias(SALUD, "salud").sentencias[0]

    assert salud.sala == "TERCERA, CONSTITUCIONAL"
    assert salud.tipo_recurso == "(CIVIL) APELACIÓN PROTECCIÓN"
    assert salud.corte_origen == "C.A. de San Miguel"
    assert salud.rol_corte_apelaciones == "767-2025"

    cobranza = parse_sentencias(COBRANZA, "cobranza").sentencias[0]
    assert cobranza.corte_origen == "Jdo. Cob. Laboral y Previsional de Santiago"
    assert not cobranza.sala, "cobranza no publica sala: el campo va vacío y no inventado"


def test_una_ruta_que_sirve_la_pagina_de_otro_buscador_se_levanta(monkeypatch):
    """Medido el 23-08-2026: pedir `Compendio_Extranjeria`, que no existe, devolvió 200 con la
    página de Cobranza, con su identificador y sus campos.

    Sin comprobar el identificador eso es indistinguible de haber consultado el buscador que se
    pidió: la respuesta tiene la forma correcta y los resultados son de otro corpus.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    pagina_de_otro = '<input name="_token" value="tok"><script>id_buscador_activo = 269</script>'

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=pagina_de_otro))
    )

    with pytest.raises(EstructuraInesperada, match="sirviendo la página de otro buscador"):
        c.abrir_sesion("suprema")


def test_el_identificador_relleno_con_ceros_sigue_siendo_el_mismo(monkeypatch):
    """El patrón captura dígitos, y `0528` es el mismo buscador que `528`.

    Comparando cadenas, un cambio de formato del sitio se leería como que la ruta empezó a
    servir otro buscador: el guardia saltaría por algo que no tiene que ver con el dato.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    con_ceros = '<input name="_token" value="tok"><script>id_buscador_activo = 0528</script>'

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=con_ceros))
    )
    c.abrir_sesion("suprema")

    assert c._id_buscador == "0528", "se guarda tal cual vino, que es lo que la petición usa"


FAMILIA = (FIXTURES / "juris_familia.json").read_text(encoding="utf-8")


def test_en_familia_la_plataforma_ya_entrega_el_caratulado_anonimizado():
    """Las tres sentencias medidas llegan con el caratulado literalmente en `ANONIMIZADO`.

    Es la razón por la que este buscador se expone y el de penales no: acá lo que la plataforma
    publica no identifica a las partes, que en familia suelen ser niños.
    """
    r = parse_sentencias(FAMILIA, "familia")

    assert r.visibles == 59880
    assert {s.caratulado for s in r.sentencias} == {"ANONIMIZADO"}
    assert all(s.anonimizada for s in r.sentencias)
    assert all("anonimizada" in s.condicion_publicacion for s in r.sentencias)
    # Su origen es un juzgado, como en civiles y laborales: leerlo con el campo de corte de
    # suprema dejaría el único dato que ubica la causa en vacío, sin que nada lo diga.
    assert r.sentencias[0].corte_origen == "Juzgado de Familia Copiapó"


def test_el_buscador_de_penales_no_se_ofrece():
    """Se midió el 23-08-2026 y queda fuera POR DECISIÓN, no por no saber leerlo.

    Es la misma razón por la que el detalle de las causas penales no se expone: sus caratulados
    llegan con el nombre del imputado cuando el fallo está marcado como no anonimizable. Que el
    dato sea consultable en la plataforma no obliga a republicarlo desde acá.
    """
    assert "penales" not in BUSCADORES
    assert "penal" not in BUSCADORES

    c = JurisClient("test@example.cl")
    with pytest.raises(ValueError, match="no verificado"):
        c.buscar(todas="homicidio", buscador="penales")


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


def test_cambiar_de_buscador_reabre_la_sesion(monkeypatch):
    """La sesión es de UN buscador, y consultarla con otro devuelve el corpus del primero.

    Encontrado con testing de mutación: la condición que decide si hay que reabrir se podía
    cambiar por una que sólo reabre cuando NO hay token, o sea nunca después de la primera
    búsqueda. Con la sesión de suprema abierta, una búsqueda en `civiles` habría contestado con
    sentencias de suprema, y nada en la respuesta lo diría.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    abiertos: list[str] = []
    c = JurisClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=AMPLIA))
    )
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"

    def abrir(self, buscador="suprema"):
        # El doble deja el estado como lo deja la real: sin eso, la segunda consulta al mismo
        # buscador volvería a reabrir y el test no podría distinguir "reabre cuando cambia" de
        # "reabre siempre", que son cosas distintas y la segunda gasta una petición de más.
        abiertos.append(buscador)
        self._buscador_de_la_sesion = buscador

    monkeypatch.setattr(JurisClient, "abrir_sesion", abrir)

    c.buscar(todas="notificación", buscador="suprema")
    assert abiertos == [], "la sesión de suprema ya estaba abierta"

    c.buscar(todas="notificación", buscador="civiles")
    assert abiertos == ["civiles"], (
        f"cambiar de buscador tiene que reabrir la sesión, y con el nombre pedido: {abiertos}"
    )

    c.buscar(todas="notificación", buscador="civiles")
    assert abiertos == ["civiles"], "seguir en el mismo buscador no reabre: sería una petición más"


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


def _campos_multipart(cuerpo: str) -> dict[str, str]:
    """Los campos de un cuerpo multipart, por nombre.

    Se parte a mano y no con una biblioteca a propósito: lo que se quiere fijar es el cuerpo
    EXACTO que sale a la red, y un parser tolerante taparía justo la diferencia que importa.
    """
    campos = {}
    for parte in cuerpo.split("--")[1:]:
        if 'name="' not in parte:
            continue
        nombre = parte.split('name="')[1].split('"')[0]
        campos[nombre] = parte.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0]
    return campos


def test_la_busqueda_manda_los_siete_campos_que_el_sitio_espera(monkeypatch):
    """El cuerpo entero, no sólo los filtros.

    Hasta acá el único test del cuerpo miraba `filtros` y dejaba los otros seis campos y las dos
    cabeceras sin fijar. Quien toque la paginación estaría cambiando el desplazamiento sin una
    sola red de seguridad, y el modo de falla de este endpoint no es un error: es una página de
    resultados que parece correcta y corresponde a otra consulta.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    visto = {}

    def transporte(req):
        visto["campos"] = _campos_multipart(req.content.decode("utf-8", "replace"))
        visto["cabeceras"] = dict(req.headers)
        return httpx.Response(200, text=CITA)

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"
    c.buscar(rol=34546, anio=2025, filas=20)

    assert set(visto["campos"]) == {
        "_token",
        "id_buscador",
        "filtros",
        "numero_filas_paginacion",
        "offset_paginacion",
        "orden",
        "personalizacion",
    }, "el sitio espera estos siete y ni uno más: con el juego completo de claves vacías da 500"
    # Contra lo que la sesión derivó, no contra el literal: así el guardia también dice que el
    # token que viaja es el de ESTA sesión y no uno de antes.
    assert visto["campos"]["_token"] == c._token
    assert visto["campos"]["id_buscador"] == c._id_buscador
    assert visto["campos"]["numero_filas_paginacion"] == "20"
    assert visto["campos"]["orden"] == "recientes"
    assert visto["campos"]["personalizacion"] == "false"
    assert visto["campos"]["offset_paginacion"] == "0", (
        "el desplazamiento va en cero mientras no esté medido: cambiarlo sin medir devuelve otra "
        "página de resultados sin que nada lo note"
    )
    assert visto["cabeceras"]["x-requested-with"] == "XMLHttpRequest"
    assert visto["cabeceras"]["referer"].endswith(BUSCADORES["suprema"].ruta)


def test_el_desplazamiento_viaja_y_la_pagina_siguiente_no_repite(monkeypatch):
    """Medido el 22 de agosto de 2026 contra el buscador de Corte Suprema: con desplazamiento
    0, 10 y 250, tres páginas SIN una sola sentencia repetida.

    Eso cierra el hueco que la documentación declaraba: la coincidencia 251 era inalcanzable
    porque el desplazamiento iba fijo en cero, no porque la plataforma no lo soportara.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    visto = {}

    def transporte(req):
        visto.update(_campos_multipart(req.content.decode("utf-8", "replace")))
        return httpx.Response(200, text=PARCIAL)

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(transporte))
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"
    r = c.buscar(todas="protección", filas=10, desplazamiento=250)

    assert visto["offset_paginacion"] == "250"
    assert r.desplazamiento == 250, "el resultado dice desde dónde empieza esta página"


def test_lo_no_entregado_descuenta_lo_que_ya_se_pidio():
    """`no_entregadas` es lo que queda DESPUÉS de esta página.

    Sin descontar el desplazamiento, la segunda página de una búsqueda de cuatrocientas
    coincidencias declararía como no entregadas casi todas, o sea diría que falta justo lo que
    la página anterior ya trajo.
    """
    primera = parse_sentencias(PARCIAL, "suprema")
    segunda = parse_sentencias(PARCIAL, "suprema", desplazamiento=100)

    assert primera.visibles == 400
    assert primera.no_entregadas == 397, "400 visibles menos las 3 de esta página"
    assert segunda.no_entregadas == 297, "y menos las 100 que quedaron atrás"
    assert segunda.desplazamiento == 100


def test_un_desplazamiento_negativo_se_rechaza_antes_de_consultar(monkeypatch):
    """No hay página menos uno, y pedirla gastaría una petición para recibir un error del
    servidor que no dice nada."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    salieron = []

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: (salieron.append(str(req.url)), httpx.Response(200, text=CITA))[1]
        )
    )
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"

    with pytest.raises(ValueError, match="desplazamiento"):
        c.buscar(todas="algo", desplazamiento=-1)
    assert not salieron


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
    c = _con_respuesta(_con_texto("X" * CARACTERES_DE_UNA_SENTENCIA))
    s = c.buscar(rol=34546, anio=2025).sentencias[0]
    assert "texto" not in s.model_dump(), "el texto completo no puede viajar en cada fila"
    # La extensión sí viaja: es lo que permite decidir si pedir el resto.
    assert s.palabras == 3881
    assert s.paginas == 13


def _con_dos_sentencias() -> str:
    """La misma respuesta con DOS documentos bajo el mismo rol.

    Sintético y dicho: las fixtures guardadas traen una sola. Lo que se sintetiza es la
    segunda fila, copiada de la primera con su resultado y su extensión cambiados, que es la
    forma medida en suprema: la casación de 3.646 palabras y la de reemplazo de 157.
    """
    d = json.loads(CITA)
    primera = d["response"]["docs"][0]
    # El rol de la fixture es otro, y la selección comprueba que lo que llega sea del rol
    # pedido: sin esto el doble sirve una causa distinta y el guardia mide esa otra cosa.
    primera["rol_era_sup_s"] = "1933-2025"
    primera["texto_sentencia"] = "Casación: considerando primero."
    primera["sent__word_count_i"] = 3646
    segunda = dict(primera)
    segunda["resultado_recurso_sup_s"] = "Sentencia de reemplazo"
    segunda["texto_sentencia"] = "Se confirma."
    segunda["sent__word_count_i"] = 157
    d["response"]["docs"] = [primera, segunda]
    d["response"]["numFound"] = 2
    return json.dumps(d, ensure_ascii=False)


def test_un_rol_con_dos_sentencias_no_se_resuelve_eligiendo_una(monkeypatch):
    """Medido en suprema, rol 1933-2025: la casación trae 3.646 palabras con el razonamiento y
    la de reemplazo 157 que sólo confirman.

    Con `filas=1` el buscador elegía, y devolvió la de 157 sin decir que existía otra. Quien
    verifique una cita se lleva un documento que se ve correcto y no contiene la doctrina.
    Es la misma decisión que ante dos causas homónimas: no se elige.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _con_respuesta(_con_dos_sentencias())

    with pytest.raises(ValueError, match="hay que decir cuál") as caida:
        c.texto(rol=1933, anio=2025)

    # Y el mensaje enumera con qué elegir, no sólo avisa que hay dos.
    dicho = str(caida.value)
    assert "3646 palabras" in dicho, f"el mensaje no dice la extensión de la primera: {dicho}"
    assert "157 palabras" in dicho, f"el mensaje no dice la extensión de la segunda: {dicho}"


def _paginando(cuerpo: str) -> JurisClient:
    """Un cliente cuyo doble RESPETA `filas` y `offset_paginacion`.

    Sin esto el doble devuelve la lista entera pase lo que pase, o sea se comporta como un
    buscador que ignora la paginación, y un selector que pidiera la página equivocada saldría
    verde igual.
    """
    d = json.loads(cuerpo)
    todos = d["response"]["docs"]

    def responder(peticion: httpx.Request) -> httpx.Response:
        crudo = peticion.content.decode(errors="replace")
        cuantas = re.search(r"numero_filas_paginacion\"\r?\n\r?\n(\d+)", crudo)
        desde = re.search(r"offset_paginacion\"\r?\n\r?\n(\d+)", crudo)
        assert cuantas, f"el formulario dejó de declarar cuántas filas pide: {crudo[:200]}"
        assert desde, f"el formulario dejó de declarar desde dónde: {crudo[:200]}"
        inicio = int(desde.group(1))
        d["response"]["docs"] = todos[inicio : inicio + int(cuantas.group(1))]
        return httpx.Response(200, text=json.dumps(d, ensure_ascii=False))

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(responder))
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"
    return c


def test_con_cual_se_entrega_la_sentencia_que_se_pidio(monkeypatch):
    """Y la segunda no es la primera: si el índice se ignorara, las dos devolverían lo mismo."""
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _paginando(_con_dos_sentencias())

    assert "Casación" in c.texto(rol=1933, anio=2025, cual=1).texto
    assert c.texto(rol=1933, anio=2025, cual=2).texto == "Se confirma."

    with pytest.raises(ValueError, match="entrega 2"):
        c.texto(rol=1933, anio=2025, cual=3)


def test_elegir_una_sentencia_no_descarga_las_anteriores(monkeypatch):
    """La herramienta existe para pedir fallos de a uno: una sentencia de trece páginas son
    veinticinco mil caracteres.

    Con `filas=cual`, pedir la número 250 descargaba también las 249 anteriores con su texto
    completo, o sea megabytes para devolver uno, y el riesgo de timeout justo acá. Se pide UNA
    fila desplazada hasta la elegida.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    formularios: list[str] = []
    d = json.loads(_con_dos_sentencias())

    def responder(peticion: httpx.Request) -> httpx.Response:
        formularios.append(peticion.content.decode(errors="replace"))
        d["response"]["docs"] = d["response"]["docs"][:1]
        return httpx.Response(200, text=json.dumps(d, ensure_ascii=False))

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(responder))
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"

    c.texto(rol=1933, anio=2025, cual=2)

    (formulario,) = formularios
    assert re.search(r"numero_filas_paginacion\"\r?\n\r?\n1\b", formulario), (
        f"se pidió más de una fila para devolver una sola: {formulario[:400]}"
    )
    assert re.search(r"offset_paginacion\"\r?\n\r?\n1\b", formulario), (
        f"no se desplazó hasta la sentencia elegida: {formulario[:400]}"
    )


def test_al_enumerar_no_falta_ninguna_ni_se_elige_a_ciegas(monkeypatch):
    """Un rol con TRES: el mensaje decía "tiene 3" y listaba dos.

    Medido en el repo: el rol 1504-2019 de apelaciones devuelve tres. Con el listado a medias,
    quien necesita la tercera no tiene su rótulo ni su extensión, o sea el selector obliga a
    elegir a ciegas justo donde más falta hace.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    base = d["response"]["docs"][0]
    d["response"]["docs"] = [
        {**base, "rol_era_sup_s": "1504-2019", "sent__word_count_i": n} for n in (900, 500, 100)
    ]
    d["response"]["numFound"] = 3
    todos = d["response"]["docs"]

    # El doble RESPETA `numero_filas_paginacion`: si sirviera siempre las tres, la primera
    # consulta ya traería todo y la segunda no se ejercitaría, que es justo lo que se prueba.
    def responder(peticion: httpx.Request) -> httpx.Response:
        cuerpo = peticion.content.decode(errors="replace")
        cuantas = re.search(r"numero_filas_paginacion\"\r?\n\r?\n(\d+)", cuerpo)
        assert cuantas, f"el formulario dejó de declarar cuántas filas pide: {cuerpo[:200]}"
        pedidas = int(cuantas.group(1))
        d["response"]["docs"] = todos[:pedidas]
        return httpx.Response(200, text=json.dumps(d, ensure_ascii=False))

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(responder))
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"

    with pytest.raises(ValueError, match="hay que decir cuál") as caida:
        c.texto(rol=1504, anio=2019)

    dicho = str(caida.value)
    for palabras in ("900 palabras", "500 palabras", "100 palabras"):
        assert palabras in dicho, f"el mensaje no enumera las tres opciones: {dicho}"


def test_al_enumerar_va_el_caratulado_y_no_solo_el_rotulo(monkeypatch):
    """En `laborales` el mapeo no declara `resultado_recurso` ni `tipo_recurso`.

    Sin el caratulado las opciones salían todas como "sin rótulo" y se distinguían sólo por el
    largo, y ahí el propio buscador mezcla causas distintas con el mismo número (`T-364-2020`
    contra `O-364-2020`): lo que las separa es justamente el caratulado.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    base = d["response"]["docs"][0]
    d["response"]["docs"] = [
        {**base, "caratulado_s": "PEREZ / EMPRESA UNO"},
        {**base, "caratulado_s": "SOTO / EMPRESA DOS"},
    ]
    d["response"]["numFound"] = 2
    c = _con_respuesta(json.dumps(d, ensure_ascii=False))

    with pytest.raises(ValueError, match="hay que decir cuál") as caida:
        c.texto(rol=364, anio=2020)

    dicho = str(caida.value)
    assert "PEREZ / EMPRESA UNO" in dicho, f"falta el caratulado de la primera: {dicho}"
    assert "SOTO / EMPRESA DOS" in dicho, f"falta el caratulado de la segunda: {dicho}"


def test_la_ambiguedad_se_decide_por_lo_que_la_plataforma_declara(monkeypatch):
    """Una respuesta que declara tres y trae una es la misma elección silenciosa, disfrazada.

    Con la ambigüedad decidida por cuántas filas llegaron, un truncamiento o un cambio de
    contrato devolvía esa única como si fuera la única que hay. Se decide por `visibles`, y si
    las filas no alcanzan para enumerar se levanta en vez de elegir.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    d["response"]["docs"][0]["rol_era_sup_s"] = "1933-2025"
    d["response"]["numFound"] = 3  # la plataforma declara tres y manda una

    c = _con_respuesta(json.dumps(d, ensure_ascii=False))

    with pytest.raises(EstructuraInesperada, match="no se pueden enumerar"):
        c.texto(rol=1933, anio=2025)


def test_una_reservada_bajo_el_mismo_rol_tambien_detiene(monkeypatch):
    """En suprema `ocultas` corresponde a la consulta, así que una visible más una reservada
    da `visibles == 1`.

    Entregar la visible la hace pasar por la única del rol, y si la cita que se fue a
    verificar es la reservada, lo que vuelve es otro fallo del mismo rol: verosímil y
    distinto. Es el mismo error que esta herramienta cerró para dos visibles.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    d["response"]["docs"][0]["rol_era_sup_s"] = "1933-2025"
    # Una visible en la página, y el recuento por condición de publicación declara dos: la
    # diferencia es la reservada, que es como la plataforma la publica.
    d["condition_pub_sf"] = {
        "numFound_sf": 2,
        "counts": ["Con interes jurisprudencial, no anonimizable", 1, "Reservada", 1],
    }
    c = _con_respuesta(json.dumps(d, ensure_ascii=False))

    with pytest.raises(PlataformaRechaza, match="reservada"):
        c.texto(rol=1933, anio=2025)


def test_con_reservadas_tambien_se_enumeran_todas_las_visibles(monkeypatch):
    """La rama de reservadas corría ANTES de volver a pedirlas, así que listaba las dos filas
    que se habían traído para detectar la ambigüedad.

    Con tres visibles y una reservada, quien necesita la tercera seguía eligiendo a ciegas,
    justo cuando además hay una opción que no se ve.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    base = d["response"]["docs"][0]
    base["rol_era_sup_s"] = "1933-2025"
    todos = [{**base, "sent__word_count_i": n} for n in (900, 500, 100)]
    d["response"]["numFound"] = 3
    d["condition_pub_sf"] = {"numFound_sf": 4, "counts": ["Publicable", 3, "Reservada", 1]}

    def responder(peticion: httpx.Request) -> httpx.Response:
        crudo = peticion.content.decode(errors="replace")
        cuantas = re.search(r"numero_filas_paginacion\"\r?\n\r?\n(\d+)", crudo)
        assert cuantas, f"el formulario dejó de declarar cuántas filas pide: {crudo[:200]}"
        d["response"]["docs"] = todos[: int(cuantas.group(1))]
        return httpx.Response(200, text=json.dumps(d, ensure_ascii=False))

    c = JurisClient("test@example.cl")
    c._http = httpx.Client(transport=httpx.MockTransport(responder))
    c._token, c._id_buscador = "tok", "528"
    c._buscador_de_la_sesion = "suprema"

    with pytest.raises(PlataformaRechaza, match="reservada") as caida:
        c.texto(rol=1933, anio=2025)

    dicho = str(caida.value)
    for palabras in ("900 palabras", "500 palabras", "100 palabras"):
        assert palabras in dicho, f"no enumera las tres visibles: {dicho}"


def test_si_el_relleno_vuelve_truncado_no_se_enumera_a_medias(monkeypatch):
    """La segunda consulta también puede volver corta.

    Con tres visibles y una reservada, si el relleno trae una sola fila el mensaje de
    reservadas enumeraría esa página parcial: volvería a obligar a elegir sin ver todas las
    alternativas, que es lo que la enumeración existe para evitar.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    d["response"]["docs"][0]["rol_era_sup_s"] = "1933-2025"
    d["response"]["numFound"] = 3
    d["condition_pub_sf"] = {"numFound_sf": 4, "counts": ["Publicable", 3, "Reservada", 1]}
    # Devuelve SIEMPRE una fila, pidan las que pidan: el relleno vuelve truncado.
    c = _con_respuesta(json.dumps(d, ensure_ascii=False))

    with pytest.raises(EstructuraInesperada, match="no se pueden enumerar"):
        c.texto(rol=1933, anio=2025)


def test_al_enumerar_va_la_fecha_de_cada_sentencia(monkeypatch):
    """En `familia` el caratulado llega como ANONIMIZADO y no hay tipo ni resultado.

    Sin la fecha, las opciones quedaban en el mismo rol, el mismo caratulado y un número de
    palabras: elegir por extensión en vez de por lo que identifica una cita.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    base = d["response"]["docs"][0]
    base["rol_era_sup_s"] = "1933-2025"
    d["response"]["docs"] = [
        {**base, "fec_sentencia_sup_dt": "2025-03-25T00:00:00Z"},
        {**base, "fec_sentencia_sup_dt": "2025-04-10T00:00:00Z"},
    ]
    d["response"]["numFound"] = 2
    c = _con_respuesta(json.dumps(d, ensure_ascii=False))

    with pytest.raises(ValueError, match="hay que decir cuál") as caida:
        c.texto(rol=1933, anio=2025)

    dicho = str(caida.value)
    assert "2025-03-25" in dicho, f"falta la fecha de la primera: {dicho}"
    assert "2025-04-10" in dicho, f"falta la fecha de la segunda: {dicho}"


def test_si_llega_otra_causa_en_la_posicion_pedida_no_se_entrega(monkeypatch):
    """`cual` es una posición, y entre la enumeración y la selección el orden puede cambiar.

    No hay identificador estable medido en estos buscadores, así que lo que se puede
    comprobar es que lo que llegó siga siendo del rol pedido. Una sentencia de otra causa se
    lee como la que se fue a verificar, que es el peor resultado de esta herramienta.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(CITA)
    d["response"]["docs"][0]["rol_era_sup_s"] = "9999-2025"
    d["response"]["numFound"] = 2
    c = _con_respuesta(json.dumps(d, ensure_ascii=False))

    with pytest.raises(EstructuraInesperada, match="el listado cambió"):
        c.texto(rol=1933, anio=2025, cual=2)


def test_un_indice_menor_que_uno_se_rechaza(monkeypatch):
    """`JurisClient` se usa también sin pasar por el protocolo, donde el esquema exige `ge=1`.

    Con `cual=0` el `or` lo convertía en 1 y entregaba la primera en silencio; con `cual=-1`
    indexaba desde el final y devolvía otra. El selector volvía a elegir por su cuenta.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _con_respuesta(_con_dos_sentencias())

    for malo in (0, -1):
        with pytest.raises(ValueError, match="empieza en 1"):
            c.texto(rol=1933, anio=2025, cual=malo)


def test_el_texto_se_pide_por_el_rol_y_el_anio_que_se_dieron(monkeypatch):
    """`texto` resuelve con una búsqueda, y el rol o el año se podían perder en el camino.

    Encontrado con testing de mutación. Sin rol, la búsqueda queda con el año solo y devuelve
    la primera sentencia de ese año: la herramienta entregaría el texto de OTRO fallo, con su
    caratulado y todo, a quien pidió verificar una cita. Es la peor forma del falso positivo
    para lo único que esta herramienta existe.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    pedidos: list[dict] = []
    c = _con_respuesta(_con_texto("Santiago, a catorce de agosto."))

    original = JurisClient.buscar

    def espiando(self, **kwargs):
        pedidos.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(JurisClient, "buscar", espiando)
    c.texto(rol=34546, anio=2025)

    # El diccionario entero y no campo por campo: así también cae un argumento de más, y el
    # buscador, que es el otro camino por el que la respuesta puede venir de otro corpus.
    assert len(pedidos) == 1, "una sola búsqueda: el texto viene en la misma respuesta"
    # `filas: 2` y no 1: con una sola, un rol con dos sentencias dejaba que el buscador
    # eligiera cuál. Lo que este test cuida sigue siendo que el rol y el año viajen.
    assert pedidos[0] == {"rol": 34546, "anio": 2025, "filas": 2, "buscador": "suprema"}

    # Y con otro buscador, para que fijar el nombre en el código no pase por bueno: con la
    # sesión en suprema, un `buscador` perdido acá devuelve el texto del corpus equivocado.
    monkeypatch.setattr(JurisClient, "abrir_sesion", lambda self, buscador="suprema": None)
    c._buscador_de_la_sesion = "civiles"
    c.texto(rol=34546, anio=2025, buscador="civiles")
    assert pedidos[-1]["buscador"] == "civiles"


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

    `response.numFound` son las VISIBLES y siguen a la consulta en todos los buscadores
    medidos, incluso donde la bandera es falsa: medirlo en apelaciones da 18 para un rol que
    existe y 0 para uno imposible, y de ahí se concluiría "es por consulta" justo donde no lo
    es. El campo que
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


def test_un_campo_que_el_buscador_no_declara_viene_en_nulo_y_no_vacio():
    """El mapa de cada buscador es lo que dice qué publica, y el lector lo ignoraba.

    `leer` hacía `d.get(campos.get(nombre, ""), "")`: sin entrada en el mapa consultaba la
    clave vacía y devolvía la cadena vacía. O sea "este buscador no publica el campo" y "lo
    publica y esta sentencia no lo trae" llegaban idénticos, que es el falso negativo de la
    regla 4 puesto en un campo en vez de en una lista.

    El que más duele es `ministros`: seis de los siete buscadores no lo declaran y llegaba
    como lista VACÍA, que según el contrato de este servidor significa "consta que no hay
    ninguno". Una sesión lo leyó así con el texto del fallo nombrando a los cinco de la sala.
    """
    cuerpo = json.dumps(json.loads(CITA))
    opcionales = ("sala", "tipo_recurso", "resultado_recurso", "rol_corte_apelaciones", "redactor")

    for campo in opcionales:
        publican = set(buscadores_que_publican(campo))
        assert publican, f"si nadie declarara {campo}, el campo sobraría en el modelo"
        assert publican != set(BUSCADORES), f"{campo} ya no distingue nada: lo declaran todos"
        for nombre in set(BUSCADORES) - publican:
            valor = getattr(parse_sentencias(cuerpo, nombre).sentencias[0], campo)
            assert valor is None, (
                f"{nombre} no declara {campo} y llegó {valor!r}: la cadena vacía se lee como "
                "que consta que está vacío"
            )

    # Y el dato sí llega donde lo hay: si el fixture no lo trajera, el bloque de arriba estaría
    # comprobando que un parser roto devuelve nulo en todas partes.
    en_suprema = parse_sentencias(cuerpo, "suprema").sentencias[0]
    con_dato = [c for c in opcionales if getattr(en_suprema, c)]
    assert con_dato, "el fixture no trae ninguno de estos campos y el guardia no prueba nada"

    # `ministros` va aparte: el vacío tampoco es respuesta donde el buscador SÍ declara el
    # campo. Medido contra la plataforma, el rol 1933-2025 en suprema lo trae vacío.
    d = json.loads(CITA)
    docs = d["response"]["docs"]
    assert _lista(docs[0]["sent__gls_int_firma_sup_s"]), "el fixture perdió los firmantes"
    assert parse_sentencias(json.dumps(d), "suprema").sentencias[0].ministros

    docs[0]["sent__gls_int_firma_sup_s"] = ""
    assert parse_sentencias(json.dumps(d), "suprema").sentencias[0].ministros is None, (
        "una lista vacía diría que no firmó nadie, y eso no lo dice ninguna sentencia"
    )
    for nombre in set(BUSCADORES) - set(buscadores_que_publican("ministros")):
        assert parse_sentencias(cuerpo, nombre).sentencias[0].ministros is None


def test_la_enumeracion_no_ofrece_una_extension_que_no_tiene():
    """El mensaje que existe para que se elija salía roto donde más se usa.

    `palabras` viene en nulo en los buscadores que no publican la extensión, y el rótulo lo
    interpolaba igual: "None palabras". Y eso ocurría justamente en apelaciones, que es donde
    más sentencias comparten rol (medido: trece bajo 2476-2023), o sea el buscador donde la
    detención se dispara más seguido.
    """
    from mcp_pjud.juris import _enumerar

    def sentencia(palabras):
        return Sentencia(
            rol="2476-2023",
            caratulado="UNA PARTE / OTRA",
            fecha_sentencia=date(2024, 12, 26),
            sala=None,
            tipo_recurso=None,
            resultado_recurso="REVOCADA",
            corte_origen="C.A. de Concepción",
            rol_corte_apelaciones=None,
            redactor=None,
            ministros=None,
            condicion_publicacion="Con interes jurisprudencial",
            anonimizada=False,
            url="https://example.invalid/x",
            palabras=palabras,
        )

    sin_extension = _enumerar([sentencia(None)])
    assert "None" not in sin_extension, sin_extension
    assert "palabras" not in sin_extension, "sin extensión no se nombra la extensión"

    con_extension = _enumerar([sentencia(PALABRAS_DE_LA_CASACION)])
    assert f"{PALABRAS_DE_LA_CASACION} palabras" in con_extension


#: Lo que la plataforma devolvió en `facet_counts.facet_fields` para el rol 2476-2023 en
#: apelaciones, medido el 25 de agosto de 2026. Se copia con su ortografía a propósito: la
#: corte sin tilde y el libro mutilado son la razón por la que un valor tecleado no calza.
FACETAS_MEDIDAS = {
    "gls_corte_s": [
        "C.A. de Concepción",
        1,
        "C.A. de Iquique",
        1,
        "C.A. de Santiago",
        7,
        "C.A. de Talca",
        1,
        "C.A. de Valparaiso",
        3,
    ],
    "gls_libro_sup_s": ["AMPARO", 2, "CIVIL", 3, "PROTECCIN", 3],
    "gls_juez_ss": ["UN JUEZ", 4],
    "enfermedad_ss": ["UNA ENFERMEDAD", 2],
}


def _con_facetas() -> str:
    d = json.loads(CITA)
    d["facet_counts"] = {"facet_fields": dict(FACETAS_MEDIDAS)}
    return json.dumps(d)


def test_solo_se_leen_las_facetas_que_el_buscador_declara():
    """La respuesta trae todas y el mapa de cada buscador decide cuáles significan algo.

    Apelaciones no declara `gls_juez_ss` y la respuesta puede traerlo igual. Leer lo que llega
    en vez de lo que el buscador declara es el mismo error que `leer` hacía con los campos: la
    forma es correcta y el contenido pertenece a otro buscador.
    """
    r = parse_sentencias(_con_facetas(), "apelaciones")
    assert r.facetas is not None
    assert set(r.facetas) == {"corte_origen", "libro"}, r.facetas
    assert r.facetas["corte_origen"]["C.A. de Santiago"] == 7
    assert "C.A. de Valparaiso" in r.facetas["corte_origen"], "la ortografía se copia tal cual"
    assert "juez" not in r.facetas, "apelaciones no declara la faceta de juez"


def test_ninguna_faceta_publica_datos_de_salud_de_quien_recurre():
    """`enfermedad_ss` y `medicamento_ss` existen en el buscador de salud y NO se exponen.

    Un desglose acotado a un rol tiene una sola sentencia por valor, así que publica de qué
    está enferma y qué toma la persona que recurrió. Es el mismo criterio por el que este
    servidor no ofrece los buscadores penales ni el compendio de extranjería.
    """
    expuestos = {solr for b in BUSCADORES.values() for solr in b.facetas.values()}
    assert expuestos, "si no se expusiera ninguna faceta, este guardia sobraría"
    for prohibido in ("enfermedad_ss", "medicamento_ss"):
        assert prohibido not in expuestos, f"{prohibido} publica un dato de salud de un tercero"

    # Y que llegue en la respuesta no alcanza para que salga: se lee el mapa, no lo que vino.
    # Se comprueban las DOS grafías: con el mapa saltado, la clave que quedaría es la de Solr,
    # y buscar sólo el nombre nuestro dejaba pasar justamente ese defecto.
    for buscador in ("salud", "apelaciones"):
        salieron = set(parse_sentencias(_con_facetas(), buscador).facetas or {})
        assert salieron <= set(BUSCADORES[buscador].facetas), (
            f"{buscador} devolvió {sorted(salieron - set(BUSCADORES[buscador].facetas))}, que "
            "no declara: se está leyendo lo que llegó y no lo que el buscador publica"
        )


def test_filtrar_por_una_faceta_que_el_buscador_no_declara_falla_antes_de_consultar(monkeypatch):
    """Pedirla no da error en la plataforma: devuelve cero resultados.

    Medido el 25 de agosto de 2026 en apelaciones con `gls_inventado_s`: visibles 0, igual que
    una cita que no existe. Por eso se rechaza acá, y el mensaje dice cuáles sí declara.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    c = _con_respuesta(_con_facetas())
    c._buscador_de_la_sesion = "apelaciones"
    with pytest.raises(ValueError, match="no declara juez"):
        c.buscar(rol=2476, anio=2023, buscador="apelaciones", facetas={"juez": ["X"]})


def test_una_busqueda_con_facetas_que_vuelve_vacia_se_detiene(monkeypatch):
    """La lista vacía acá no prueba que la sentencia no exista: prueba que el valor no calzó.

    La plataforma publica `C.A. de Valparaiso` sin tilde y un libro como `PROTECCIN`, así que
    el valor escrito de memoria devuelve cero. Devolverlo como lista vacía es exactamente el
    falso negativo que la regla 4 existe para no producir.
    """
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)
    d = json.loads(_con_facetas())
    d["response"]["docs"] = []
    d["response"]["numFound"] = 0
    c = _con_respuesta(json.dumps(d))
    c._buscador_de_la_sesion = "apelaciones"

    with pytest.raises(EstructuraInesperada, match="NO prueba que no exista"):
        c.buscar(
            rol=2476,
            anio=2023,
            buscador="apelaciones",
            facetas={"corte_origen": ["C.A. de Valparaíso"]},
        )

    # Sin facetas, el mismo vacío SÍ es una respuesta: no hay valor que pueda no haber calzado.
    assert c.buscar(rol=2476, anio=2023, buscador="apelaciones").visibles == 0
