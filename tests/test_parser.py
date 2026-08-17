"""Tests del parser contra HTML real de la Oficina Judicial Virtual.

El fixture es E-468-2026 del 3º Juzgado Civil de Concepción: un exhorto con la
secuencia completa de actuaciones (búsquedas negativas, certificación positiva,
notificación exitosa y requerimiento ficto), todas con formato de fecha doble.
"""

from datetime import date, time
from pathlib import Path

import pytest
from lxml import html as H

from mcp_pjud.parser import (
    COMPETENCIAS,
    Competencia,
    EstructuraInesperada,
    actuaciones_receptor,
    parse_cuadernos,
    parse_historia,
    parse_resultados,
)

FIXTURES = Path(__file__).parent / "fixtures"
DETALLE = (FIXTURES / "detalle_causa_civil.html").read_text(encoding="utf-8")
# C-1156-2026, el caso que originó el proyecto: tiene cuaderno de apremio.
C1156_PRINCIPAL = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
C1156_APREMIO = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")


def test_extrae_todas_las_filas_de_historia():
    assert len(parse_historia(DETALLE)) == 12


def test_filtra_solo_actuaciones_de_receptor():
    recep = actuaciones_receptor(DETALLE)
    assert len(recep) == 8
    assert all("Actuación Receptor" in a.tramite for a in recep)


def test_la_fecha_de_diligencia_no_es_la_de_registro():
    """El corazón del proyecto.

    El folio 10 se registró el 22/06 pero la notificación se practicó el 17/06.
    Quien tome la fecha de registro pierde cinco días de plazo.
    """
    folio10 = next(a for a in actuaciones_receptor(DETALLE) if a.folio == "10")
    assert folio10.fecha_diligencia == date(2026, 6, 17)
    assert folio10.fecha_registro == date(2026, 6, 22)
    assert folio10.fecha_diligencia != folio10.fecha_registro


def test_extrae_la_hora_desde_la_descripcion():
    folio10 = next(a for a in actuaciones_receptor(DETALLE) if a.folio == "10")
    assert folio10.hora_diligencia == time(14, 25)


def test_conserva_la_descripcion_literal():
    folio10 = next(a for a in actuaciones_receptor(DETALLE) if a.folio == "10")
    assert folio10.desc_tramite == ("NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:17/06/2026 14:25")


def test_cubre_los_cuatro_tipos_de_diligencia():
    descripciones = " | ".join(a.desc_tramite for a in actuaciones_receptor(DETALLE))
    for tipo in (
        "NOTIFICACIÓN DE DEMANDA (Búsqueda negativa)",
        "NOTIFICACIÓN DE DEMANDA (Exitosa)",
        "CERTIFICACIÓN BÚSQUEDAS (Búsqueda positiva)",
        "Requerimiento de Pago (Ficto)",
    ):
        assert tipo in descripciones


def test_sin_discrepancia_cuando_ambas_fuentes_coinciden():
    assert not any(a.discrepancia_fechas for a in actuaciones_receptor(DETALLE))


def test_expone_georreferencia():
    """Su ausencia puede ser jurídicamente relevante (art. 9 inc. 3 Ley 20.886),
    así que el campo se expone siempre, nunca se omite del output."""
    recep = actuaciones_receptor(DETALLE)
    assert all(isinstance(a.georreferenciado, bool) for a in recep)
    assert all(a.georreferenciado for a in recep)


# --- cuadernos: el detalle muestra uno solo a la vez ----------------------------


def test_detecta_los_cuadernos_de_la_causa():
    cuadernos = parse_cuadernos(C1156_PRINCIPAL)
    assert [c.nombre for c in cuadernos] == [
        "1 - Principal",
        "2 - Apremio Ejecutivo Obligación de Dar",
    ]
    assert all(c.referencia for c in cuadernos)


def test_causa_con_un_solo_cuaderno():
    assert [c.nombre for c in parse_cuadernos(DETALLE)] == ["0 - Principal"]


def test_el_apremio_esconde_actuaciones_que_no_estan_en_el_principal():
    """El cuaderno de apremio del caso que originó el proyecto.

    Leer sólo el cuaderno que viene por defecto devuelve una respuesta completa en
    apariencia a la que le faltan el requerimiento de pago y el embargo: justo las
    diligencias que corren plazos en un juicio ejecutivo.
    """
    principal = {a.folio for a in actuaciones_receptor(C1156_PRINCIPAL)}
    apremio = actuaciones_receptor(C1156_APREMIO)

    descripciones = " | ".join(a.desc_tramite for a in apremio)
    assert "Requerimiento de Pago (Ficto)" in descripciones
    assert "EMBARGO (Exitosa)" in descripciones
    assert not principal & {a.folio for a in apremio}, "los folios no se solapan"


def test_la_actuacion_recuerda_su_cuaderno():
    acts = actuaciones_receptor(C1156_APREMIO, "2 - Apremio Ejecutivo Obligación de Dar")
    assert all(a.cuaderno == "2 - Apremio Ejecutivo Obligación de Dar" for a in acts)


def test_embargo_del_apremio_trae_fecha_de_diligencia_propia():
    embargo = next(a for a in actuaciones_receptor(C1156_APREMIO) if "EMBARGO" in a.desc_tramite)
    assert embargo.fecha_diligencia == date(2026, 3, 31)
    assert embargo.hora_diligencia == time(10, 34)


# --- casos sintéticos: lo que el fixture real no contiene ------------------------


def _historia(filas: str) -> str:
    return f"""<div id="historiaCiv"><table>
      <thead><tr><th>Folio</th><th>Doc.</th><th>Anexo</th><th>Etapa</th>
      <th>Tr&aacute;mite</th><th>Desc. Tr&aacute;mite</th><th>Fec. Tr&aacute;mite</th>
      <th>Foja</th><th>Georref.</th></tr></thead><tbody>{filas}</tbody></table></div>"""


def _fila(desc: str, fec: str, georref: str = "") -> str:
    return (
        f"<tr><td>1</td><td></td><td></td><td>Exhorto</td><td>Actuación Receptor</td>"
        f"<td>{desc}</td><td>{fec}</td><td>0</td><td>{georref}</td></tr>"
    )


def test_reporta_discrepancia_entre_las_dos_fuentes_de_fecha():
    doc = _historia(_fila("NOTIFICACIÓN Diligencia:15/06/2026 10:00", "22/06/2026 (17/06/2026)"))
    a = actuaciones_receptor(doc)[0]
    assert a.discrepancia_fechas
    assert a.fecha_diligencia == date(2026, 6, 17)  # gana la de Fec. Trámite


def test_el_parentesis_por_si_solo_da_la_fecha_de_diligencia():
    """Aísla la extracción del paréntesis de 'Fec. Trámite'.

    En el fixture real toda fila trae además 'Diligencia:' en la descripción, así que
    una regresión en el paréntesis quedaría tapada por ese fallback. Acá la descripción
    no trae fecha: si el paréntesis deja de leerse, esto se cae.
    """
    doc = _historia(_fila("CERTIFICACIÓN BÚSQUEDAS", "22/06/2026 (17/06/2026)"))
    a = actuaciones_receptor(doc)[0]
    assert a.fecha_diligencia == date(2026, 6, 17)
    assert a.fecha_registro == date(2026, 6, 22)


def test_georreferencia_ausente_se_reporta_como_false():
    a = actuaciones_receptor(_historia(_fila("NOTIFICACIÓN", "22/06/2026 (17/06/2026)")))[0]
    assert a.georreferenciado is False


def test_sin_parentesis_no_inventa_fecha_de_diligencia():
    a = actuaciones_receptor(_historia(_fila("CERTIFICACIÓN", "22/06/2026")))[0]
    assert a.fecha_registro == date(2026, 6, 22)
    assert a.fecha_diligencia is None


def test_fecha_imposible_no_revienta_la_fila():
    a = actuaciones_receptor(_historia(_fila("X", "31/02/2026 (30/02/2026)")))[0]
    assert a.fecha_diligencia is None
    assert a.fecha_registro is None


# --- fallo ruidoso: nunca devolver vacío ante estructura desconocida -------------


def test_sin_panel_historia_levanta_excepcion():
    with pytest.raises(EstructuraInesperada, match="historiaCiv"):
        parse_historia("<html><body><p>Sesión expirada</p></body></html>")


def test_panel_sin_tabla_levanta_excepcion():
    with pytest.raises(EstructuraInesperada, match="tabla"):
        parse_historia('<div id="historiaCiv"><p>vacío</p></div>')


def test_columna_faltante_levanta_excepcion():
    """Si el Poder Judicial renombra o quita una columna, hay que enterarse.
    Devolver una lista vacía haría creer que no hubo actuaciones."""
    sin_georref = _historia("").replace("<th>Georref.</th>", "")
    with pytest.raises(EstructuraInesperada, match="georref"):
        parse_historia(sin_georref)


def test_el_modelo_serializa_fechas_en_iso():
    """ISO 8601 y no DD/MM/AAAA: 06/09/2026 es ambiguo para quien lea el output."""
    doc = _historia(_fila("X Diligencia:09/06/2026 08:05", "12/06/2026 (09/06/2026)"))
    a = actuaciones_receptor(doc)[0]
    volcado = a.model_dump(mode="json")
    assert volcado["fecha_diligencia"] == "2026-06-09"
    assert volcado["hora_diligencia"] == "08:05:00"


# --- huecos detectados por testing de mutación ---------------------------------


def test_la_descripcion_sola_da_la_fecha_cuando_no_hay_parentesis():
    """Espejo de test_el_parentesis_por_si_solo_da_la_fecha_de_diligencia.

    Toda fila del fixture real trae las dos fuentes, así que ninguna ejercitaba el
    respaldo: cuando 'Fec. Trámite' viene sin paréntesis, la fecha debe salir del
    'Diligencia:' de la descripción. Un mutante que anulaba ese respaldo sobrevivía.
    """
    doc = _historia(_fila("EMBARGO (Exitosa) Diligencia:31/03/2026 10:34", "01/04/2026"))
    a = actuaciones_receptor(doc)[0]
    assert a.fecha_diligencia == date(2026, 3, 31)
    assert a.fecha_registro == date(2026, 4, 1)
    assert a.hora_diligencia == time(10, 34)
    assert not a.discrepancia_fechas


def test_detecta_si_el_folio_trae_documento():
    con_doc = '<form action="docuN.php"><input name="dtaDoc" value="x"></form>'
    fila = (
        f"<tr><td>1</td><td>{con_doc}</td><td></td><td>Exhorto</td>"
        f"<td>Actuación Receptor</td><td>X</td><td>22/06/2026</td><td>0</td><td></td></tr>"
    )
    assert actuaciones_receptor(_historia(fila))[0].tiene_documento is True


def test_sin_documento_se_reporta_como_false():
    a = actuaciones_receptor(_historia(_fila("X", "22/06/2026")))[0]
    assert a.tiene_documento is False


def test_hora_imposible_no_revienta_la_fila():
    """25:99 no es una hora. La fila igual debe entregar su fecha."""
    a = actuaciones_receptor(_historia(_fila("X Diligencia:31/03/2026 25:99", "01/04/2026")))[0]
    assert a.fecha_diligencia == date(2026, 3, 31)
    assert a.hora_diligencia is None


def test_tabla_con_encabezados_y_cero_filas_levanta_excepcion():
    """Esta forma la produce una respuesta truncada o HTML que lxml no recupera.

    Lo detectó Hypothesis: con ciertas entradas malformadas, lxml perdía las filas y el
    parser devolvía una lista vacía sin avisar. Esa es exactamente la falla silenciosa
    que el proyecto existe para evitar, así que ahora levanta.
    """
    with pytest.raises(EstructuraInesperada, match="ninguna fila"):
        parse_historia(_historia(""))


# -- el listado, para las competencias que no son civil --------------------------


def test_una_fila_a_la_que_le_faltan_columnas_se_levanta():
    """Aceptarla rellenando con vacío haría pasar por causa sin tribunal lo que en realidad
    es un dato faltante: un cambio de estructura disfrazado de dato."""
    fila = "<tr><td><a onclick=\"detalleCausaLaboral('ref-1')\">ver</a></td><td>O-1-2018</td></tr>"
    with pytest.raises(EstructuraInesperada, match="celdas"):
        parse_resultados(fila, "laboral")


def test_una_fila_con_control_ilegible_se_levanta():
    """Saltarla en silencio pierde una causa dentro de un listado que devuelve las demás, y
    eso es peor que no devolver nada: la lista parece completa."""
    fila = '<tr><td><a onclick="detalleCausaCivil(variable)">ver</a></td><td>C-1-2026</td></tr>'
    with pytest.raises(EstructuraInesperada, match="no se puede leer"):
        parse_resultados(fila, "civil")


def test_leer_la_historia_de_una_competencia_sin_panel_verificado_se_levanta():
    """El guardia existía y era inalcanzable: `actuaciones_receptor` no reenviaba la
    competencia, así que el parser siempre miraba `historiaCiv`."""
    with pytest.raises(EstructuraInesperada, match="No está verificado"):
        actuaciones_receptor("<html></html>", "", "cobranza")


def test_las_columnas_de_cada_competencia_son_las_que_declara_el_sitio():
    """La tabla salió de los encabezados que `consultaUnificada.php` arma por competencia.

    Se fija acá para que reordenar un mapa sin medir contra el sitio se note: son índices, y
    un índice corrido devuelve el tribunal en el campo del caratulado sin que nada reviente.
    """
    assert COMPETENCIAS["laboral"].columnas == {
        "rol": 1,
        "tribunal": 2,
        "caratulado": 3,
        "fecha_ingreso": 4,
        "estado": 5,
    }
    assert COMPETENCIAS["cobranza"].columnas == {
        "rol": 1,
        "ruc": 2,
        "tribunal": 3,
        "caratulado": 4,
        "fecha_ingreso": 5,
        "estado": 6,
    }
    # Sólo estas dos exponen ministro de fe en todo el sitio.
    assert {k for k, v in COMPETENCIAS.items() if v.receptor} == {"civil", "cobranza"}


# -- los índices de columna, contra respuestas reales -----------------------------
#
# La tabla de `COMPETENCIAS` salió del JavaScript del sitio, o sea era una hipótesis. Estas
# fixtures son listados reales anonimizados: sin ellas, "verificado el 17 de agosto" es una
# afirmación que CI no puede desmentir, y si mañana la plataforma reordena una columna nada
# en el repositorio se entera.

LABORAL = (FIXTURES / "busqueda_rit_laboral.html").read_text(encoding="utf-8")
COBRANZA = (FIXTURES / "busqueda_rit_cobranza.html").read_text(encoding="utf-8")


def test_el_listado_laboral_se_lee_con_los_indices_declarados():
    (causa,) = parse_resultados(LABORAL, "laboral")
    assert causa.rol == "O-9999-2018"
    assert causa.tribunal.startswith("Juzgado de Letras del Trabajo")
    assert causa.caratulado.startswith("APELLIDO FICTICIO")
    assert causa.fecha_ingreso == "17/10/2018"
    assert causa.estado == "Cumplimiento"
    assert causa.competencia == "laboral"
    # Laboral no publica RUC: es la diferencia con cobranza y penal.
    assert causa.ruc is None


def test_el_listado_de_cobranza_trae_ruc_y_lo_pone_donde_corresponde():
    """Cobranza intercala el RUC entre el rol y el tribunal. Un índice corrido devolvería el
    RUC en el campo del tribunal sin que nada reviente."""
    (causa,) = parse_resultados(COBRANZA, "cobranza")
    assert causa.rol == "C-9999-2019"
    assert causa.ruc == "00- 0-0000000-0"
    assert causa.tribunal.startswith("Jdo. de Letras del Trabajo")
    assert causa.caratulado.startswith("APELLIDO FICTICIO")
    assert causa.estado == "Concluido"


def test_leer_un_listado_con_el_mapa_de_otra_competencia_no_pasa_en_silencio():
    """El modo de falla que importa: cobranza tiene una columna más que laboral, así que
    leerlo con el mapa equivocado corre todos los campos un lugar."""
    con_mapa_ajeno = parse_resultados(COBRANZA, "laboral")[0]
    assert con_mapa_ajeno.tribunal != parse_resultados(COBRANZA, "cobranza")[0].tribunal, (
        "los mapas tienen que producir lecturas distintas, o el test no prueba nada"
    )
    # Y al revés no alcanza: laboral tiene menos celdas de las que cobranza declara.
    with pytest.raises(EstructuraInesperada, match="celdas"):
        parse_resultados(LABORAL, "cobranza")


def test_no_se_puede_declarar_el_panel_de_historia_sin_sus_columnas():
    """Las tres cosas viajan juntas en `Historia` a propósito.

    Antes el sufijo del panel estaba en la tabla y las columnas seguían clavadas a civil, así
    que poner `panel="Cob"` habría corrido las filas de cobranza por el mapa de nueve columnas
    de civil: `Estado Firma` en `foja`, la georreferencia leída de otra celda. Lo único que lo
    impedía era que civil exige el encabezado `georref.`, que cobranza no trae, o sea una
    protección accidental. Ahora es imposible por construcción.
    """
    # Se comprueba sobre la forma del tipo y no llamándolo mal: `ty` caza la llamada inválida
    # antes de que se ejecute, así que un test que la escriba rompe el chequeo de tipos.
    assert "panel" not in Competencia._fields, (
        "volvió a existir un campo `panel` suelto, que se puede declarar sin las columnas"
    )
    assert "historia" in Competencia._fields

    # Y la de civil declara las tres.
    civil = COMPETENCIAS["civil"].historia
    assert civil is not None
    assert civil.panel == "Civ"
    assert "georref" in civil.columnas
    assert "georref." in civil.encabezados


def test_la_georreferencia_se_lee_de_la_columna_que_declara_la_competencia():
    """Quedó una posición fija de civil donde debía ir el mapa de la competencia.

    En una tabla con las columnas en otro orden, `georreferenciado` habría salido de la celda
    equivocada sin que nada reviente, y en una tabla más corta habría dado `IndexError`. Es el
    campo cuya ausencia puede ser jurídicamente relevante (art. 9 inc. 3 Ley 20.886), así que
    leerlo de otra columna es de los errores peores que puede tener este parser.
    """
    from mcp_pjud.parser import _fila_a_actuacion

    # Un orden invertido respecto de civil: georref primero, folio al final.
    invertido = (
        "georref",
        "foja",
        "fec_tramite",
        "desc_tramite",
        "tramite",
        "etapa",
        "anexo",
        "doc",
        "folio",
    )
    celdas = H.fromstring(
        "<tr>"
        '<td><a href="#">geo</a></td><td>0</td><td>31/03/2026 (27/03/2026)</td>'
        "<td>EMBARGO</td><td>Actuación Receptor</td><td>Apremio</td><td></td><td></td>"
        "<td>12</td></tr>"
    ).xpath("./td")

    a = _fila_a_actuacion(celdas, "", invertido)
    assert a.folio == "12", "el folio salió de la columna equivocada"
    assert a.georreferenciado is True, "la georreferencia se leyó de una celda que no es la suya"
