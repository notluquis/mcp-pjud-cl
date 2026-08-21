"""Tests del parser contra HTML real de la Oficina Judicial Virtual.

El fixture es E-468-2026 del 3º Juzgado Civil de Concepción: un exhorto con la
secuencia completa de actuaciones (búsquedas negativas, certificación positiva,
notificación exitosa y requerimiento ficto), todas con formato de fecha doble.
"""

import re
from datetime import date, time
from pathlib import Path

import pytest
from lxml import html as H

from mcp_pjud.client import MODULOS
from mcp_pjud.parser import (
    COMPETENCIAS,
    Competencia,
    EstructuraInesperada,
    actuaciones_receptor,
    causa_es_exhorto,
    parse_cuadernos,
    parse_exhortos,
    parse_georreferencia,
    parse_historia,
    parse_liquidaciones,
    parse_litigantes,
    parse_materias,
    parse_notificaciones,
    parse_piezas_exhorto,
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
    Devolver una lista vacía haría creer que no hubo actuaciones.

    El mensaje cambió al pasar la validación de pertenencia a posición: ahora dice cuántas
    columnas llegaron contra cuántas se esperaban, porque quitar una desplaza a todas las
    siguientes y eso es lo que hay que reportar, no cuál falta.
    """
    sin_georref = _historia("").replace("<th>Georref.</th>", "")
    with pytest.raises(EstructuraInesperada, match="columnas y se esperaban"):
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
    competencia, así que el parser siempre miraba `historiaCiv`.

    Se usa `penal`, la única que sigue sin historia mapeada. Ya se reapuntó dos veces, de
    `cobranza` a `laboral` y ahora acá, cada vez que la anterior pasó a estar medida: un test
    cuyo caso de prueba desaparece porque el código mejoró se reapunta, no se borra.

    Y penal no está sin mapear por descuido. Se pidió su detalle y `historiaPen` vino con
    encabezados y CERO filas, igual que sus otros tres paneles. Declarar sus columnas sin una
    sola fila real sería escribir un mapa que nada comprobó.
    """
    with pytest.raises(EstructuraInesperada, match="No está verificado"):
        actuaciones_receptor("<html></html>", "", "penal")


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
    assert civil.panel == "historiaCiv"
    assert "georref" in civil.columnas
    assert "georref." in civil.encabezados


def test_el_panel_declarado_es_el_identificador_completo_y_no_un_sufijo():
    """El código anteponía `historia` al sufijo declarado, y eso no generaliza.

    Los paneles reales son `historiaCiv`, `historiaCob`, `movimientosSup`, `movimientosApe` y
    `movimientoLab`: dos familias de nombre distintas, y una de ellas en singular mientras las
    otras van en plural. Con el esquema de prefijo, mapear suprema habría buscado
    `historiamovimientosSup` y no habría encontrado nada, que es la falla silenciosa de
    siempre: un panel que no está devuelve vacío, y vacío se lee como que no hubo actuaciones.
    """
    for nombre, spec in COMPETENCIAS.items():
        if spec.historia is None:
            continue
        assert not spec.historia.panel.startswith("historiahistoria"), (
            f"{nombre} declara un panel con el prefijo duplicado: volvió el esquema de sufijo"
        )
        assert spec.historia.panel[0].islower(), (
            f"{nombre} declara {spec.historia.panel!r}, que parece un sufijo y no un "
            "identificador completo"
        )


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


@pytest.mark.parametrize("centinela", ["31/12/1969", "01/01/1970"])
def test_el_cero_renderizado_como_fecha_no_se_devuelve_como_fecha(centinela):
    """Medido en `diligenciaCob`: una diligencia de embargo cumplida traía `31/12/1969`.

    Es el epoch de Unix visto desde una zona al oeste de Greenwich, o sea el valor cero
    impreso como fecha. Devolverlo sería peor que devolver nulo: alguien computaría un plazo
    desde 1969. Es el error del proyecto con el signo invertido: no falta un dato, sobra uno
    que tiene forma de dato.
    """
    from mcp_pjud.parser import _fecha

    assert _fecha(centinela) is None
    # Y una fecha real del mismo entorno sigue funcionando.
    assert _fecha("31/03/2026") == date(2026, 3, 31)


SUPREMA = (FIXTURES / "busqueda_rit_suprema.html").read_text(encoding="utf-8")
APELACIONES = (FIXTURES / "busqueda_rit_apelaciones.html").read_text(encoding="utf-8")


def test_el_listado_de_suprema_se_lee_con_los_indices_declarados():
    """Suprema pone el tipo de recurso donde las demás ponen el tribunal.

    Es la segunda celda en las dos, así que un mapa corrido no revienta: devuelve
    "(Civil) Apelación Protección" en el campo del tribunal y "Corte Suprema" en el del tipo
    de recurso. Las dos cosas se ven plausibles y ninguna es correcta.
    """
    (causa,) = parse_resultados(SUPREMA, "suprema")
    assert causa.rol == "999999-2020"
    assert causa.tipo_recurso == "(Civil) Apelación Protección"
    assert causa.tribunal == "Corte Suprema"
    assert causa.fecha_ingreso == "12/11/2020"
    assert causa.estado == "Fallada"
    assert causa.competencia == "suprema"
    # Suprema no publica ubicación: es la diferencia con apelaciones.
    assert causa.ubicacion is None


def test_en_apelaciones_el_rol_lleva_el_libro_y_sin_el_no_identifica_la_causa():
    """El mismo número de rol y año son TRES causas distintas, una por libro.

    Medido sobre este listado: 9999-2019 devuelve un Exhorto, una Civil y una Protección, con
    caratulados y fechas distintos. O sea "rol 1504-2019 de la Corte de Concepción" no
    identifica nada por sí solo, y verificar una cita por número y año sin comparar el libro y
    el caratulado puede dar por confirmada una causa que no es la citada.
    """
    causas = parse_resultados(APELACIONES, "apelaciones")
    assert [c.rol for c in causas] == [
        "Exhorto-9999-2019",
        "Civil-9999-2019",
        "Protección-9999-2019",
    ]
    assert len({c.caratulado for c in causas}) == 3, "tres libros, tres causas distintas"
    assert all(c.tribunal == "C.A. de Concepción" for c in causas)
    # La ubicación es la columna que sólo apelaciones publica, y dice dónde está el expediente.
    assert [c.ubicacion for c in causas] == [
        "Corte apelaciones",
        "Primera Instancia",
        "Corte apelaciones",
    ]
    assert all(c.tipo_recurso is None for c in causas)


def test_leer_apelaciones_con_el_mapa_de_suprema_no_revienta_y_miente():
    """La dirección peligrosa es la del listado ancho leído con el mapa angosto.

    Apelaciones trae ocho celdas y suprema declara hasta la sexta, así que el mapa de suprema
    entra sin faltar ninguna celda: no hay error, y "C.A. de Concepción" sale en el campo del
    tipo de recurso mientras el caratulado sale en el del tribunal. Todo se ve plausible.

    Al revés sí revienta, y eso es lo correcto: suprema trae siete celdas y apelaciones declara
    hasta la séptima, o sea necesita ocho. Que una dirección falle ruidosamente y la otra no es
    exactamente por qué el contraste de abajo tiene que existir.
    """
    propio = parse_resultados(APELACIONES, "apelaciones")[0]
    ajeno = parse_resultados(APELACIONES, "suprema")[0]
    assert propio.tribunal == "C.A. de Concepción"
    assert ajeno.tribunal != propio.tribunal, (
        "los mapas de suprema y apelaciones tienen que producir lecturas distintas, o estos "
        "tests no prueban que los índices importen"
    )
    assert ajeno.tipo_recurso == "C.A. de Concepción", (
        "con el mapa de suprema, la corte cae en el campo del tipo de recurso"
    )

    with pytest.raises(EstructuraInesperada, match="celdas"):
        parse_resultados(SUPREMA, "apelaciones")


# -- las historias de suprema, apelaciones y laboral ----------------------------
#
# Las tres se midieron el 17 de agosto de 2026 pidiendo el detalle de una causa real. Sin estas
# fixtures, "el panel se llama así y sus columnas son éstas" es una afirmación que CI no puede
# desmentir, y las tres tablas salieron de UNA respuesta cada una.

DETALLE_SUPREMA = (FIXTURES / "detalle_suprema.html").read_text(encoding="utf-8")
DETALLE_APELACIONES = (FIXTURES / "detalle_apelaciones.html").read_text(encoding="utf-8")
DETALLE_LABORAL = (FIXTURES / "detalle_laboral.html").read_text(encoding="utf-8")


def test_la_historia_de_suprema_trae_la_sala_que_resolvio():
    """Suprema publica la sala, y es parte de cómo se cita un fallo.

    Recortarla para que la fila calzara con la forma de civil habría entregado la actuación sin
    el dato que permite identificarla. Tampoco trae `Etapa` ni `Georref.`, así que este caso
    ejercita las dos columnas que el mapeo tuvo que dejar de dar por sentadas.
    """
    actuaciones = parse_historia(DETALLE_SUPREMA, "", "suprema")
    assert len(actuaciones) == 8
    sentencia = next(a for a in actuaciones if a.tramite == "Sentencia")
    assert sentencia.sala == "Tercera, CONSTITUCIONAL"
    assert sentencia.desc_tramite == "CONFIRMA SENTENCIA APELADA"
    assert sentencia.correlativo
    assert sentencia.estado == "Bloqueado"
    assert sentencia.etapa == "", "suprema no publica etapa, y vacío no es un valor inventado"
    assert sentencia.georreferenciado is False, (
        "suprema no publica la columna: falso significa que no hay dato, no que no esté "
        "georreferenciada"
    )


def test_la_historia_de_apelaciones_nombra_sus_columnas_distinto():
    """Llama `Descripción` a lo que civil llama `Desc. Trámite` y `Fecha` a `Fec. Trámite`.

    Y su georreferencia se escribe `Georeferencia`, sin punto y con otra ortografía. Compartir
    la lista blanca de encabezados de civil habría hecho fallar la lectura de una respuesta
    perfectamente válida.
    """
    actuaciones = parse_historia(DETALLE_APELACIONES, "", "apelaciones")
    assert len(actuaciones) == 3
    assert [a.folio for a in actuaciones] == ["3", "2", "1"]
    assert actuaciones[0].sala == "Presidencia"
    assert actuaciones[0].fecha_registro is not None


def test_la_historia_de_laboral_pone_estado_donde_civil_pone_foja():
    actuaciones = parse_historia(DETALLE_LABORAL, "", "laboral")
    assert len(actuaciones) == 26
    assert actuaciones[0].estado == "Firmado"
    assert actuaciones[0].foja is None, "laboral no publica foja"
    assert actuaciones[0].etapa


def test_ninguna_de_las_tres_publica_actuaciones_de_receptor():
    """Es la razón por la que las tres declaran `receptor=False`, y conviene tenerlo medido.

    En las tres respuestas la palabra receptor no aparece ni una vez, y ninguna fila trae la
    fecha doble que corre los plazos. Si mañana alguna empieza a publicarlas, esto se cae y hay
    que revisar la tabla en vez de seguir devolviendo una lista vacía.
    """
    for competencia, detalle in (
        ("suprema", DETALLE_SUPREMA),
        ("apelaciones", DETALLE_APELACIONES),
        ("laboral", DETALLE_LABORAL),
    ):
        assert "receptor" not in detalle.lower(), f"{competencia} ahora menciona al receptor"
        actuaciones = parse_historia(detalle, "", competencia)
        assert not [a for a in actuaciones if a.es_actuacion_receptor]
        assert not [a for a in actuaciones if a.fecha_diligencia], (
            f"{competencia} ahora publica fecha de diligencia: hay que revisar la tabla"
        )


def test_leer_suprema_con_el_mapa_de_apelaciones_no_pasa_en_silencio():
    """Los dos paneles se llaman distinto, así que el mapa ajeno no encuentra dónde leer.

    Es el modo de falla que importa: buscar un panel que no está devuelve vacío, y vacío se lee
    como que la causa no tiene actuaciones.
    """
    with pytest.raises(EstructuraInesperada, match="movimientosApe"):
        parse_historia(DETALLE_SUPREMA, "", "apelaciones")
    with pytest.raises(EstructuraInesperada, match="movimientosSup"):
        parse_historia(DETALLE_APELACIONES, "", "suprema")


def test_la_marca_de_rol_con_libro_calza_con_lo_que_publican_las_fixtures():
    """La bandera dice si el rol lleva el libro adelante, y eso es medible.

    Sin esto, el guardia del esquema MCP sólo comprueba que las competencias marcadas se
    nombren: marcar apelaciones como si no llevara libro lo dejaba verde, y con eso el modelo
    volvería a mandar una letra donde el número de rol se repite entre libros.

    Se compara contra los listados reales, que es de donde salió la bandera.
    """
    listados = {
        "civil": "busqueda_rit_civil",
        "laboral": "busqueda_rit_laboral",
        "cobranza": "busqueda_rit_cobranza",
        "suprema": "busqueda_rit_suprema",
        "apelaciones": "busqueda_rit_apelaciones",
    }
    for competencia, archivo in listados.items():
        html_ = (FIXTURES / f"{archivo}.html").read_text(encoding="utf-8")
        causas = parse_resultados(html_, competencia)
        assert causas, f"la fixture de {competencia} no trae causas"

        # Un libro es un prefijo de más de una letra antes del primer guion: `Exhorto-1504-2019`
        # contra `C-1156-2026`, que es la letra del tipo de causa.
        prefijos = [(c.rol or "").split("-")[0] for c in causas]
        con_libro = all(len(p) > 1 and not p.isdigit() for p in prefijos)

        assert con_libro == COMPETENCIAS[competencia].rol_con_libro, (
            f"{competencia} declara rol_con_libro="
            f"{COMPETENCIAS[competencia].rol_con_libro} y sus roles reales son {prefijos}"
        )


# -- las notificaciones ---------------------------------------------------------

NOTIF_CIVIL = (FIXTURES / "detalle_civil_notificaciones.html").read_text(encoding="utf-8")
NOTIF_COBRANZA = (FIXTURES / "detalle_cobranza.html").read_text(encoding="utf-8")


def test_cobranza_publica_las_dos_fechas_y_difieren():
    """Es la única de las tres que separa la fecha de notificación de la del trámite.

    Y difieren de verdad: en una notificación por carta se midieron tres días entre una y otra.
    Es la misma forma que la fecha doble de la Historia, con otro nombre, y confundirlas cuesta
    lo mismo.
    """
    notificaciones = parse_notificaciones(NOTIF_COBRANZA, "cobranza")
    assert len(notificaciones) == 16

    carta = next(n for n in notificaciones if n.tipo == "carta")
    assert carta.fecha_notificacion is not None
    assert carta.fecha_tramite is not None
    assert carta.fecha_notificacion != carta.fecha_tramite, (
        "la carta medida tenía tres días entre notificación y trámite"
    )
    assert carta.fecha_notificacion > carta.fecha_tramite


def test_donde_no_se_publica_la_fecha_de_notificacion_va_nula_y_no_copiada():
    """Civil y laboral publican UNA fecha, la de trámite.

    Copiarla en el campo de notificación produciría un dato con forma de medición que nadie
    midió. Nulo dice "esta competencia no lo informa", que es lo único cierto.
    """
    for competencia, detalle in (("civil", NOTIF_CIVIL), ("laboral", DETALLE_LABORAL)):
        notificaciones = parse_notificaciones(detalle, competencia)
        assert notificaciones, f"{competencia} no trajo notificaciones"
        assert all(n.fecha_notificacion is None for n in notificaciones), (
            f"{competencia} no publica la fecha de notificación y alguna vino con valor"
        )
        assert any(n.fecha_tramite is not None for n in notificaciones)


def test_las_notificaciones_de_civil_traen_el_rol_y_el_tipo_de_via():
    notificaciones = parse_notificaciones(NOTIF_CIVIL, "civil")
    assert len(notificaciones) == 3
    assert notificaciones[0].rol
    assert notificaciones[0].tipo == "mail"
    assert notificaciones[0].estado == "Realizada"
    assert notificaciones[0].tipo_parte.startswith("AB")


def test_laboral_no_publica_el_tipo_de_via():
    """Su panel es el más corto de los tres: sin rol y sin tipo de notificación."""
    notificaciones = parse_notificaciones(DETALLE_LABORAL, "laboral")
    assert all(n.tipo is None for n in notificaciones)
    assert all(n.rol is None for n in notificaciones)
    assert {n.estado for n in notificaciones} >= {"Realizada", "Pendiente"}

    # Y las dos columnas contiguas no están cruzadas. Sin esto el test pasaba igual con
    # `tipo_parte` y `nombre` intercambiados, porque ninguna de las aserciones de arriba los
    # mira: quedaba un nombre de persona en el campo de la calidad procesal.
    assert all(n.tipo_parte.rstrip(".").replace(".", "").isupper() for n in notificaciones), (
        "la calidad procesal es una sigla como 'AB.DTE.'; si trae un nombre, las columnas "
        "están cruzadas"
    )
    assert any(" " in n.nombre for n in notificaciones), (
        "el nombre de la persona notificada lleva espacios; una sigla no"
    )


def test_leer_las_notificaciones_con_el_mapa_de_otra_competencia_no_pasa_en_silencio():
    """Los tres paneles se llaman distinto, y cobranza además lo escribe en singular."""
    with pytest.raises(EstructuraInesperada, match="notificacionCob"):
        parse_notificaciones(NOTIF_CIVIL, "cobranza")
    with pytest.raises(EstructuraInesperada, match="notificacionesCiv"):
        parse_notificaciones(NOTIF_COBRANZA, "civil")


def test_una_competencia_sin_notificaciones_medidas_se_rechaza():
    with pytest.raises(EstructuraInesperada, match="No está verificado"):
        parse_notificaciones(DETALLE_SUPREMA, "suprema")


def test_un_panel_de_notificaciones_vacio_devuelve_lista_y_no_levanta():
    """Acá una lista vacía SÍ es una respuesta, al revés que en la Historia.

    Toda causa tiene al menos el folio de ingreso, así que una historia sin filas es anómala.
    Una causa sin ninguna notificación practicada es corriente: tres de las cuatro causas
    civiles medidas traen el panel vacío. Levantar ahí convertiría lo normal en un error.
    """
    vacio = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    assert parse_notificaciones(vacio, "civil") == []


# -- la liquidación del crédito -------------------------------------------------


def test_las_liquidaciones_de_cobranza_traen_monto_y_fecha():
    """Es la pregunta que da sentido a un juicio de cobro y que no se contestaba.

    La causa medida acumula tres liquidaciones sucesivas: la más reciente es la vigente y las
    anteriores son el historial. No se suman, y por eso la fecha de cada una importa tanto como
    el monto.
    """
    liquidaciones = parse_liquidaciones(NOTIF_COBRANZA, "cobranza")
    assert len(liquidaciones) == 3

    montos = [liq.monto for liq in liquidaciones]
    assert montos == [24563365, 12680528, 4481885]

    fechas = [liq.fecha for liq in liquidaciones]
    assert None not in fechas, "toda liquidación medida trae fecha"
    assert fechas == sorted(fechas, reverse=True), "vienen de la más nueva a la más vieja"
    assert liquidaciones[0].monto_publicado == "$24.563.365.-"
    assert all(liq.estado == "Firmado" for liq in liquidaciones)


def test_el_monto_se_conserva_tambien_como_lo_publica_el_sitio():
    """Se entregan los dos: el número para calcular y el texto para comparar.

    El expediente muestra `$24.563.365.-`, y es contra eso que alguien va a contrastar. Dejar
    sólo el entero obligaría a reconstruir el formato para verificar, y ahí es donde se cuela
    un error de tres órdenes de magnitud.
    """
    liquidaciones = parse_liquidaciones(NOTIF_COBRANZA, "cobranza")
    for liq in liquidaciones:
        assert liq.monto_publicado.startswith("$")
        assert liq.monto is not None
        assert str(liq.monto) == liq.monto_publicado.strip("$.-").replace(".", "")


@pytest.mark.parametrize(
    ("publicado", "esperado"),
    [
        ("$24.563.365.-", 24563365),
        ("$1.000.-", 1000),
        ("$0.-", 0),
        ("", None),
        ("sin monto", None),
        # Una coma significaría decimales donde se midió que no los hay, o un separador
        # distinto. Las dos lecturas difieren en tres órdenes de magnitud, así que no se
        # adivina: se devuelve nulo y queda el texto publicado.
        ("$1.234,56", None),
    ],
)
def test_el_monto_no_se_adivina_cuando_no_tiene_la_forma_medida(publicado, esperado):
    from mcp_pjud.parser import _monto

    assert _monto(publicado) == esperado


def test_una_competencia_que_no_liquida_se_rechaza():
    """Cobranza es la única con el panel. En las demás la lista vacía se leería como que no
    hay deuda liquidada, y eso es distinto de que la competencia no lo publique."""
    with pytest.raises(EstructuraInesperada, match="no publica liquidaciones"):
        parse_liquidaciones(NOTIF_CIVIL, "civil")


# -- litigantes y materias ------------------------------------------------------


def test_los_litigantes_se_leen_en_las_cinco_competencias():
    """Civil llama `Participante` a lo que las otras cuatro llaman `Sujeto`.

    Es la razón de que haya cinco constantes y no una: si compartieran encabezados, la lectura
    de civil fallaría contra una respuesta perfectamente válida.
    """
    esperado = {
        ("civil", DETALLE): 5,
        ("cobranza", NOTIF_COBRANZA): 4,
        ("laboral", DETALLE_LABORAL): 4,
        ("suprema", DETALLE_SUPREMA): 7,
        ("apelaciones", DETALLE_APELACIONES): 1,
    }
    for (competencia, detalle), cuantos in esperado.items():
        litigantes = parse_litigantes(detalle, competencia)
        assert len(litigantes) == cuantos, f"{competencia} trajo {len(litigantes)}"
        assert all(x.sujeto and x.nombre for x in litigantes), (
            f"en {competencia} hay litigantes sin calidad procesal o sin nombre"
        )


def test_laboral_publica_dos_columnas_que_ninguna_otra_trae():
    """Agrega `Est.` y `Abog. Defensor` ADELANTE, así que corre todo lo demás dos lugares.

    Leerlo con el mapa de las otras cuatro pondría el estado en el campo del sujeto y el
    abogado en el del RUT: cuatro campos plausibles y todos equivocados.
    """
    laboral = parse_litigantes(DETALLE_LABORAL, "laboral")
    assert all(x.abogado_defensor is not None for x in laboral)
    assert {x.abogado_defensor for x in laboral} <= {"Sí", "No"}
    assert all(x.rut and "-" in x.rut for x in laboral), (
        "el RUT quedó corrido: las columnas de laboral no están donde el mapa dice"
    )

    civil = parse_litigantes(DETALLE, "civil")
    assert all(x.abogado_defensor is None for x in civil), "civil no publica esa columna"


def test_las_materias_dicen_que_se_litiga():
    materias = parse_materias(DETALLE_LABORAL, "laboral")
    assert len(materias) == 9
    glosas = {m.glosa for m in materias}
    assert "Despido injustificado" in glosas
    assert all(m.codigo.startswith("L") for m in materias)
    assert all(m.fecha_termino is not None for m in materias)


def test_las_materias_de_una_competencia_que_no_las_publica_se_rechazan():
    """Sólo laboral tiene el panel. En las demás la lista vacía se leería como que la causa
    no tiene materias, que es distinto de que la competencia no las publique."""
    with pytest.raises(EstructuraInesperada, match="no publica materias"):
        parse_materias(DETALLE, "civil")


def test_leer_los_litigantes_con_el_mapa_de_otra_competencia_no_pasa_en_silencio():
    with pytest.raises(EstructuraInesperada, match="litigantesCiv"):
        parse_litigantes(DETALLE_LABORAL, "civil")
    with pytest.raises(EstructuraInesperada, match="litigantesLab"):
        parse_litigantes(DETALLE, "laboral")


def test_penal_no_tiene_litigantes_medidos():
    with pytest.raises(EstructuraInesperada, match="No está verificado"):
        parse_litigantes(DETALLE, "penal")


def test_un_panel_de_litigantes_sin_filas_no_se_publica_como_causa_sin_partes():
    """Toda causa tiene partes: es lo que la hace una causa.

    Un panel con encabezados y cero filas es una respuesta truncada o una estructura que
    cambió. Devolver la lista vacía publicaría "esta causa no tiene partes", que no existe, y
    es la misma anomalía que la Historia ya rechaza.
    """
    import re as _re

    vaciado = _re.sub(
        r'(<div[^>]*id="litigantesCiv".*?<table.*?</thead>).*?(</table>)',
        r"\1\2",
        DETALLE,
        flags=_re.S,
    )
    assert vaciado != DETALLE, "la fixture no se pudo vaciar: el test no probaría nada"

    with pytest.raises(EstructuraInesperada, match="ninguna fila"):
        parse_litigantes(vaciado, "civil")


# -- exhortos ----------------------------------------------------------------------


def test_el_exhorto_dice_a_qué_causa_del_otro_tribunal_hay_que_ir():
    """Un exhorto abre una causa NUEVA en el tribunal destino, y las actuaciones de la
    diligencia viven allá.

    Sin `rol_destino` y `tribunal_destino` la respuesta diría que hay un exhorto y no dónde
    buscarlo, que es la mitad inútil del dato: quien compute un plazo por una diligencia
    exhortada tiene que ir al otro expediente.
    """
    exhortos = parse_exhortos(C1156_PRINCIPAL, "civil")

    assert len(exhortos) == 1
    e = exhortos[0]
    assert e.rol_origen == "C-1156-2026"
    assert e.rol_destino == "E-875-2026"
    assert e.tribunal_destino == "1º Juzgado Civil de Chillán"
    assert e.tipo == "Exhorto"
    assert e.estado == "Generado"
    assert e.fecha_orden == date(2026, 3, 18)
    assert e.fecha_ingreso == date(2026, 3, 18)


def test_una_causa_sin_exhortos_devuelve_lista_vacía_y_no_levanta():
    """Cero exhortos es una respuesta, no un fallo: la mayoría de las causas no despacha
    ninguno.

    Por eso este panel NO lleva el guardia de cero filas que sí llevan los litigantes, donde
    una causa sin partes no existe. Está medido sobre las cuatro respuestas civiles guardadas:
    dos traen el panel con encabezados y ninguna fila.
    """
    assert parse_exhortos(DETALLE, "civil") == []


@pytest.mark.parametrize("competencia", ["cobranza", "laboral", "suprema", "apelaciones"])
def test_los_exhortos_de_una_competencia_sin_medir_se_rechazan(competencia):
    """Leerlos con el mapa de civil devolvería el tribunal destino en el campo del tipo: se ve
    plausible y es falso. Sólo civil está medida."""
    with pytest.raises(EstructuraInesperada, match="No está verificado"):
        parse_exhortos(
            (FIXTURES / "detalle_cobranza.html").read_text(encoding="utf-8"), competencia
        )


# -- piezas del exhorto ------------------------------------------------------------


def test_las_piezas_traen_la_tramitación_que_el_tribunal_de_origen_despachó():
    """E-468-2026 ES un exhorto, y sus seis piezas son lo que la causa de origen mandó junto
    con él: lo que el tribunal exhortado tuvo a la vista.

    El mapa es posicional y este panel es el único con una columna `Cuaderno` al medio, así
    que reusar el de la Historia correría las nueve columnas y la fecha caería en la foja.
    """
    piezas = parse_piezas_exhorto(DETALLE, "civil")

    assert piezas is not None
    assert len(piezas) == 6

    mandamiento = next(p for p in piezas if p.folio == "1")
    assert mandamiento.cuaderno == "2", "el cuaderno es el de la causa de ORIGEN"
    assert mandamiento.etapa == "Mandamiento"
    assert mandamiento.tramite == "Actuación"
    assert mandamiento.desc_tramite == "Mandamiento"
    assert mandamiento.fecha_registro == date(2025, 12, 23)
    assert mandamiento.foja == "1"
    assert mandamiento.documento_ruta == "docuS.php"
    assert mandamiento.documento_referencia == "referencia-ficticia-031"

    # Una de las seis no trae documento: la celda es un icono `fa-ban`, sin formulario ni
    # enlace. Decir que sí lo trae y no cuál es la mitad inútil del dato.
    exhortese = next(p for p in piezas if p.desc_tramite == "Exhórtese")
    assert exhortese.tiene_documento is False
    assert exhortese.documento_referencia is None


def test_una_causa_que_no_es_exhorto_devuelve_nulo_y_no_lista_vacía():
    """Los dos silencios dicen cosas distintas.

    Lista vacía significaría "esta causa es un exhorto y el tribunal de origen no le mandó
    ninguna pieza". Lo que pasa en C-1156-2026 es otra cosa: la pregunta no aplica, porque no
    es un exhorto sino la causa que despacha uno.
    """
    assert parse_piezas_exhorto(C1156_PRINCIPAL, "civil") is None
    assert parse_piezas_exhorto(C1156_APREMIO, "civil") is None


def test_si_la_causa_es_un_exhorto_lo_dice_la_cabecera():
    """Los dos lados del exhorto se ven desde causas distintas: la que lo ordena trae
    `exhortosCiv`, la que lo recibe trae `piezasExhortoCiv` y no trae el otro."""
    assert causa_es_exhorto(DETALLE, "civil") is True
    assert causa_es_exhorto(C1156_PRINCIPAL, "civil") is False


def test_un_panel_renombrado_no_se_lee_como_que_la_causa_no_es_un_exhorto():
    """El modo de falla que decide el contrato de este panel.

    Deducir "no es un exhorto" de que `piezasExhortoCiv` no esté ata la afirmación a que la
    plataforma no renombre un `id`. El día que lo renombre, la respuesta no diría "no pude
    leerlo": diría que la causa no es un exhorto, y las seis piezas desaparecerían sin error.
    La cabecera sigue diciendo `Proc.: Exhorto`, así que se levanta.
    """
    renombrado = DETALLE.replace('id="piezasExhortoCiv"', 'id="piezasExhortoCivil"')
    assert renombrado != DETALLE, "la fixture no se pudo deformar: el test no probaría nada"

    assert causa_es_exhorto(renombrado, "civil") is True
    with pytest.raises(EstructuraInesperada, match="no trae el panel"):
        parse_piezas_exhorto(renombrado, "civil")


def test_el_panel_en_una_causa_que_la_cabecera_no_declara_exhorto_levanta():
    """La contradicción no se resuelve en silencio porque las dos salidas pierden datos:
    creerle a la cabecera tira piezas que están ahí, y creerle al panel inventa un exhorto
    donde el sitio dice que no lo hay."""
    injertado = C1156_PRINCIPAL.replace(
        '<div class="tab-content"',
        '<div id="piezasExhortoCiv"></div><div class="tab-content"',
        1,
    )
    assert injertado != C1156_PRINCIPAL, "la fixture no se pudo deformar"

    with pytest.raises(EstructuraInesperada, match="igual trae el panel"):
        parse_piezas_exhorto(injertado, "civil")


def test_una_cabecera_sin_el_procedimiento_levanta_en_vez_de_responder_que_no():
    """El rótulo `Proc.` es la única fuente de la respuesta. Si no está, "no es un exhorto" no
    es una lectura conservadora: es una afirmación que nadie midió."""
    sin_rotulo = DETALLE.replace("<strong>Proc.:</strong>", "<strong>Procedimiento:</strong>")
    assert sin_rotulo != DETALLE, "la fixture no se pudo deformar"

    with pytest.raises(EstructuraInesperada, match=r"no publica 'Proc\.'"):
        causa_es_exhorto(sin_rotulo, "civil")


def test_la_errata_del_sitio_es_la_que_se_calza_y_no_la_ortografía_correcta():
    """Los encabezados del panel dicen `Támite`, `Desc. Támite` y `Fec. Támite`, sin la erre.

    Se calza con lo que la plataforma emite. Si algún día la corrigen, esto tiene que levantar
    y no devolver vacío: es el mismo mapa posicional de nueve columnas, y una lista vacía se
    leería como que el tribunal de origen no despachó nada.
    """
    corregido = DETALLE.replace("T&aacute;mite", "Tr&aacute;mite")
    assert corregido != DETALLE, "la fixture no se pudo deformar"

    with pytest.raises(EstructuraInesperada, match="támite"):
        parse_piezas_exhorto(corregido, "civil")


def test_la_fecha_doble_de_una_pieza_no_se_colapsa_en_una_sola():
    """`Fec. Támite` es la misma columna que la `Fec. Trámite` de la Historia, con el nombre
    mal escrito, así que puede traer las dos fechas.

    Las seis piezas medidas traen una sola, y por eso el guardia va sobre una deformación:
    quedarse con la primera es confundir el registro con la diligencia, que es el error que
    este proyecto existe para no cometer.
    """
    con_doble = DETALLE.replace("<td>23/12/2025</td>", "<td>23/12/2025 (19/12/2025)</td>")
    assert con_doble != DETALLE, "la fixture no se pudo deformar"

    piezas = parse_piezas_exhorto(con_doble, "civil")
    assert piezas is not None
    mandamiento = next(p for p in piezas if p.folio == "1")
    assert mandamiento.fecha_registro == date(2025, 12, 23)
    assert mandamiento.fecha_diligencia == date(2025, 12, 19)


@pytest.mark.parametrize("competencia", ["cobranza", "laboral", "suprema", "apelaciones"])
def test_las_piezas_de_una_competencia_sin_medir_se_rechazan(competencia):
    """Sólo civil está medida. Responder que la causa no es un exhorto sin haber medido qué
    pone su cabecera descarta en silencio las piezas que el tribunal de origen despachó."""
    cobranza = (FIXTURES / "detalle_cobranza.html").read_text(encoding="utf-8")

    with pytest.raises(EstructuraInesperada, match="No está verificado"):
        parse_piezas_exhorto(cobranza, competencia)
    with pytest.raises(EstructuraInesperada, match="No está verificado"):
        causa_es_exhorto(cobranza, competencia)


def test_el_estado_de_la_parte_laboral_no_se_pierde_por_venir_como_icono():
    """La columna `Est.` de laboral no trae texto: trae `<i class="fa fa-check-square-o">`.

    Leerla con `text_content()` daba cadena vacía, que se normalizaba a nulo, y el nulo ya
    significa "esta competencia no publica el dato". O sea el dato existía y se informaba como
    ausente: el falso negativo de siempre, en un campo chico.

    Se devuelve la clase sin interpretar. Hay UN solo valor observado en las cuatro filas
    medidas, así que traducirlo a "vigente" o "notificado" sería inventar el mapa.
    """
    partes = parse_litigantes(
        (FIXTURES / "detalle_laboral.html").read_text(encoding="utf-8"), "laboral"
    )
    assert partes, "la fixture laboral dejó de traer litigantes"
    assert all(p.estado == "fa-check-square-o" for p in partes), (
        f"estados leídos: {[p.estado for p in partes]}"
    )
    assert all("fa-lg" not in (p.estado or "") for p in partes), (
        "`fa-lg` es el tamaño del icono, no el estado"
    )


def test_donde_la_competencia_no_publica_el_estado_de_la_parte_va_nulo():
    """Civil no tiene la columna, y ahí el nulo SÍ significa "acá no se informa". Es la
    distinción que el arreglo de arriba no puede borrar."""
    partes = parse_litigantes(DETALLE, "civil")
    assert partes, "la fixture civil dejó de traer litigantes"
    assert all(p.estado is None for p in partes)


def test_una_causa_laboral_sin_materias_no_se_publica_como_que_no_litiga_nada():
    """La materia es QUÉ se litiga, y es lo que el tribunal registra al ingresar la causa.

    Encabezados y cero filas es una respuesta truncada o una estructura que cambió. Devolver
    la lista vacía publicaría "esta causa no litiga nada", que no existe.
    """
    doc = H.fromstring((FIXTURES / "detalle_laboral.html").read_text(encoding="utf-8"))
    panel = doc.xpath('//*[@id="materiasLab"]')[0]
    filas = panel.xpath(".//tbody/tr")
    assert filas, "la fixture laboral dejó de traer materias y el recorte no prueba nada"
    for fila in filas:
        fila.getparent().remove(fila)

    with pytest.raises(EstructuraInesperada, match="ninguna fila"):
        parse_materias(H.tostring(doc, encoding="unicode"), "laboral")


def test_un_icono_de_estado_irreconocible_levanta_en_vez_de_volver_nulo():
    """Es el mismo falso negativo, una capa más abajo.

    Si el sitio cambia el icono por algo sin clase `fa-`, o lo deja vacío, devolver `None`
    diría "esta competencia no publica el estado" cuando sí lo publica. La columna existe: que
    no se pueda leer es una estructura que cambió, no un dato ausente.
    """
    doc = H.fromstring((FIXTURES / "detalle_laboral.html").read_text(encoding="utf-8"))
    iconos = doc.xpath('//*[@id="litigantesLab"]//tbody//i')
    assert iconos, "la fixture laboral dejó de traer el icono de estado"
    for icono in iconos:
        icono.set("class", "glyphicon glyphicon-ok")

    with pytest.raises(EstructuraInesperada, match="estado de la parte"):
        parse_litigantes(H.tostring(doc, encoding="unicode"), "laboral")


@pytest.mark.parametrize(
    ("competencia", "fixture"),
    [
        ("civil", "c1156_principal.html"),
        ("cobranza", "detalle_cobranza.html"),
        ("laboral", "detalle_laboral.html"),
        ("apelaciones", "detalle_apelaciones.html"),
        ("suprema", "detalle_suprema.html"),
    ],
)
def test_la_actuacion_dice_cual_documento_tiene_y_no_solo_que_tiene_uno(competencia, fixture):
    """`tiene_documento` decía que HAY documento y no CUÁL, y con eso no se puede pedir.

    Va sobre las CINCO competencias y no sólo civil, porque la primera versión buscaba el
    campo `dtaDoc`, que es el nombre de civil, y devolvía nulo en las otras cuatro con
    `tiene_documento` en verdadero: el mismo falso negativo que vino a arreglar, reintroducido.
    Cada competencia lo nombra a su manera (`valorRef`, `valorDoc`, `valorFile`) y usa su
    propia ruta, así que se lee del formulario y no de una tabla escrita a mano.

    Laboral trae además una fila que abre el documento con un modal de JavaScript en vez de un
    formulario, y ahí la referencia viaja como argumento.
    """
    html_detalle = (FIXTURES / fixture).read_text(encoding="utf-8")
    actuaciones = parse_historia(html_detalle, competencia=competencia)

    con_doc = [a for a in actuaciones if a.tiene_documento]
    assert con_doc, f"la fixture de {competencia} dejó de traer actuaciones con documento"

    sin_referencia = [a.folio for a in con_doc if not a.documento_referencia]
    assert not sin_referencia, (
        f"en {competencia} hay folios que dicen tener documento y no dicen cuál: {sin_referencia}"
    )
    # No basta con que traiga ALGO, y se supo rompiéndolo: una versión de esto sacaba `"form"`
    # del `onclick` que envía el formulario y lo entregaba como referencia. Las fixtures están
    # anonimizadas con un prefijo conocido, así que un valor que no lo lleve es basura.
    basura = [
        a.documento_referencia
        for a in con_doc
        if "referencia-" not in (a.documento_referencia or "")
    ]
    assert not basura, (
        f"en {competencia} la referencia del documento no salió del sitio: {basura[:3]}"
    )
    for a in actuaciones:
        if not a.tiene_documento:
            assert a.documento_referencia is None


def test_dos_actuaciones_no_comparten_la_referencia_de_su_documento():
    """Si todas devolvieran la misma, se estaría leyendo la de otra actuación y entregando el
    documento equivocado, que se ve plausible y es falso."""
    con_doc = [a for a in parse_historia(C1156_PRINCIPAL) if a.tiene_documento]
    referencias = [a.documento_referencia for a in con_doc]
    assert len(set(referencias)) == len(referencias), f"referencias repetidas: {referencias}"


def test_el_onclick_que_envia_el_formulario_no_se_lee_como_una_referencia():
    """Las filas que traen formulario llevan `$(this).closest("form").submit()` en el enlace.

    La primera versión del respaldo aceptaba cualquier llamada dentro del `onclick`, y de ahí
    sacaba `"form"` como si fuera la referencia del documento. Un valor plausible y falso, que
    es peor que no traer ninguno.

    En la práctica no se alcanzaba, porque el formulario responde antes, así que esto es
    defensa en profundidad y se prueba donde sí se alcanza: en la función.
    """
    from mcp_pjud.parser import _documento_de_la_celda

    celda = H.fromstring(
        """<td><a href="#" onclick='$(this).closest("form").submit();'>x</a></td>"""
    )
    assert _documento_de_la_celda(celda) == (None, None)


def test_el_documento_que_abre_un_modal_deja_la_ruta_nula_y_no_inventada():
    """Laboral trae una fila que abre el documento con un modal en vez de un formulario, y ahí
    la referencia viaja como argumento.

    La ruta queda nula a propósito: el nombre de la función de JavaScript no es un endpoint, y
    a cuál llama no está medido. Devolverlo como ruta sería adivinar.
    """
    from mcp_pjud.parser import _documento_de_la_celda

    celda = H.fromstring("""<td><a onclick="textoDemandaLaboral('REF-9');">x</a></td>""")
    assert _documento_de_la_celda(celda) == (None, "REF-9")


def test_el_certificado_de_envio_no_se_entrega_como_si_fuera_la_resolucion():
    """Varias competencias traen el certificado en la misma fila, con el campo `dtaCert`.

    Confundirlos entregaría el certificado de envío como si fuera la resolución: dos documentos
    distintos, y el que importa para un plazo es la resolución.
    """
    from mcp_pjud.parser import _documento_de_la_celda

    celda = H.fromstring(
        """<td><form action="x/docCertificadoEscrito.php">
        <input type="hidden" name="dtaCert" value="CERT"></form></td>"""
    )
    assert _documento_de_la_celda(celda) == (None, None)


def test_una_causa_exhortada_sin_piezas_no_se_publica_como_que_no_le_mandaron_nada():
    """Un exhorto existe porque el tribunal de origen despachó algo.

    Las seis piezas medidas incluyen `Ordena despachar mandamiento` y `Exhórtese`, o sea los
    actos que lo crearon. Cero filas ahí es una respuesta truncada, y la lista vacía se leería
    como que el tribunal de origen no mandó ninguna pieza, que en un exhorto no existe.
    """
    doc = H.fromstring(DETALLE)
    panel = doc.xpath('//*[@id="piezasExhortoCiv"]')[0]
    filas = panel.xpath(".//tbody/tr")
    assert filas, "la fixture dejó de traer piezas y el recorte no prueba nada"
    for fila in filas:
        fila.getparent().remove(fila)

    with pytest.raises(EstructuraInesperada, match="ninguna fila"):
        parse_piezas_exhorto(H.tostring(doc, encoding="unicode"), "civil")


def test_el_falso_de_georreferenciado_no_significa_lo_mismo_en_todas_las_competencias():
    """Suprema no publica la columna, así que su `false` es "no hay dónde mirar".

    En civil, en cambio, `false` significa que la actuación NO se georreferenció, que es lo
    que el art. 9 inc. 3 de la Ley 20.886 vuelve relevante. Afirmar lo segundo donde sólo vale
    lo primero es exactamente la clase de dato plausible y falso que este proyecto persigue.
    """
    assert "georref" in COMPETENCIAS["civil"].historia.columnas
    assert "georref" not in COMPETENCIAS["suprema"].historia.columnas, (
        "si suprema pasa a publicar la columna, el contrato del campo hay que reescribirlo"
    )

    suprema = parse_historia(
        (FIXTURES / "detalle_suprema.html").read_text(encoding="utf-8"), competencia="suprema"
    )
    assert suprema, "la fixture de suprema dejó de traer actuaciones"
    assert all(not a.georreferenciado for a in suprema), (
        "en suprema el campo sólo puede ser falso, y por ausencia de columna"
    )


# -- georreferencia ------------------------------------------------------------------

GEO = (FIXTURES / "georreferencia_civil.html").read_text(encoding="utf-8")
GEO_VACIA = (FIXTURES / "georreferencia_vacia.html").read_text(encoding="utf-8")


def test_la_georreferencia_trae_la_unica_hora_del_proyecto():
    """Las dos fechas de la Historia son del día. Ésta viene del aparato con que se tomó la
    coordenada, así que es una tercera fuente sobre cuándo ocurrió la diligencia.

    Perder la hora al leerla sería quedarse con lo que ya se tenía.
    """
    g = parse_georreferencia(GEO)

    assert g.existe
    assert (g.latitud, g.longitud) == (-11.1111111, -22.2222222)
    assert g.precision_metros == 26.68
    assert g.fecha_dispositivo == date(2026, 3, 31)
    assert g.hora_dispositivo == time(10, 34)
    assert g.intentos == 1


def test_una_actuacion_sin_georreferencia_se_distingue_de_no_haber_preguntado():
    """Medido: de las seis actuaciones georreferenciadas de C-1156-2026, una abre un panel que
    responde que no existe ninguna.

    Vuelve como dato y no como error, porque un error se leería como que no se pudo consultar,
    y eso llevaría a reintentar contra la plataforma por algo que ya respondió.
    """
    g = parse_georreferencia(GEO_VACIA)

    assert g.existe is False
    assert g.latitud is None
    assert g.fecha_dispositivo is None


def test_un_panel_con_coordenadas_y_sin_fecha_levanta():
    """Entregar la ubicación sin cuándo se tomó ni con qué margen es la mitad del dato, y es la
    mitad que no permite contrastar un plazo."""
    sin_texto = re.sub(r"\*Fecha dispositivo.*?\*Intentos: &nbsp;1", "", GEO, flags=re.S)
    assert sin_texto != GEO

    with pytest.raises(EstructuraInesperada, match="fecha del dispositivo"):
        parse_georreferencia(sin_texto)


def test_un_panel_sin_coordenadas_y_sin_el_aviso_levanta():
    """Si el sitio deja de emitir latitud y longitud y tampoco dice que no hay georreferencia,
    devolver una georreferencia sin coordenadas se leería como que la diligencia no se ubicó."""
    sin_coords = GEO.replace('id="latitud"', 'id="otro"').replace('id="longitud"', 'id="otro2"')

    with pytest.raises(EstructuraInesperada, match="latitud y"):
        parse_georreferencia(sin_coords)


def test_una_fecha_de_dispositivo_imposible_levanta_en_vez_de_volver_nula():
    """`31-02-2026` tiene el formato correcto y no es una fecha.

    Devolverla en nulo publicaría `existe=true` sin fecha, y ésa es justamente la tercera fuente
    por la que esta herramienta existe: sin ella no hay con qué contrastar la que corre los
    plazos, y el nulo se leería como que el sitio no la publica.
    """
    with pytest.raises(EstructuraInesperada, match="no es una fecha"):
        parse_georreferencia(GEO.replace("31-03-2026", "31-02-2026"))


def test_la_georreferencia_solo_se_ofrece_donde_puede_existir():
    """`penal` no tiene panel de Historia medido y `suprema` no publica la columna, así que para
    las dos no puede existir una referencia que pedir.

    La lista salía escrita a mano y dejaba a `penal` anunciada como opción válida y siempre en
    error, que es lo mismo que el modelo atribuye a la plataforma.
    """
    from mcp_pjud.client import GEORREFERENCIA

    for nombre, spec in COMPETENCIAS.items():
        publica = spec.historia is not None and "georref" in spec.historia.columnas
        assert (nombre in GEORREFERENCIA) == publica or nombre not in MODULOS, (
            f"{nombre!r} publica la columna={publica} y se ofrece={nombre in GEORREFERENCIA}"
        )
    assert "penal" not in GEORREFERENCIA
    assert "suprema" not in GEORREFERENCIA
    assert "civil" in GEORREFERENCIA
