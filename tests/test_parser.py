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
    audio_de_la_causa,
    causa_es_exhorto,
    parse_anexos,
    parse_audios,
    parse_causa_de_origen,
    parse_cuadernos,
    parse_diligencias,
    parse_escritos_pendientes,
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


# -- las diligencias del ministro de fe -----------------------------------------


def test_las_diligencias_de_cobranza_se_leen_enteras():
    """El panel donde cobranza guarda de verdad al ministro de fe.

    Nueve columnas y un mapa posicional: las aserciones van campo por campo y no sobre la
    cantidad de filas, porque dos columnas contiguas intercambiadas no cambian el largo de
    nada. `destinatario` y `responsable` son justo ese par, y confundirlas pondría a quien
    practica la diligencia en el lugar de quien la recibe.
    """
    (diligencia,) = parse_diligencias(NOTIF_COBRANZA, "cobranza")

    assert diligencia.estado == "cumplida"
    assert diligencia.tipo == "Oficios Varios 3"
    assert diligencia.destinatario == "No Asignado"
    assert diligencia.rit == "C-208-2019"
    # El RUC va ceroizado en la fixture, como en el resto: su cuerpo de seis dígitos también
    # tenía forma de RUT y pasaba por debajo del guardia.
    assert diligencia.ruc == "00- 0-0000000-0"

    # El nombre real no se escribe acá: la fixture trae el de una persona natural. Se comprueba
    # la FORMA, que es lo que distingue la celda del responsable de la de al lado.
    assert diligencia.responsable is not None, "cobranza sí publica la columna"
    assert " " in diligencia.responsable, (
        "el responsable es el nombre de una persona y lleva espacios; si trae 'No Asignado' o "
        "una fecha, las columnas están corridas"
    )
    assert diligencia.responsable != diligencia.destinatario


def test_la_fecha_epoch_de_una_diligencia_vuelve_nula_y_no_como_fecha():
    """El test que importa de este panel, y por eso pasa por `parse_diligencias` entera.

    La fila medida está `cumplida` y su columna de fecha dice `31/12/1969`: el epoch de Unix
    visto desde una zona al oeste de Greenwich, o sea el valor cero renderizado, no una
    diligencia practicada ese día. Entregarlo tal cual haría computar un plazo desde 1969.

    Las dos aserciones van juntas a propósito: el nulo NO significa que la diligencia no se
    practicó, y sin el estado al lado se leería justo así.
    """
    (diligencia,) = parse_diligencias(NOTIF_COBRANZA, "cobranza")

    assert diligencia.fecha_tramite is None, (
        "el epoch se devolvió como fecha real, y alguien computaría un plazo desde 1969"
    )
    assert diligencia.estado == "cumplida", (
        "la diligencia SÍ se practicó: la fecha nula dice que el sitio no publicó ninguna, no "
        "que no haya ocurrido"
    )


def test_un_panel_de_diligencias_vacio_devuelve_lista_y_no_levanta():
    """Igual que en notificaciones y liquidaciones: acá la lista vacía SÍ es una respuesta.

    De cinco causas de cobranza medidas, sólo una trae filas en este panel, así que la causa
    sin ninguna diligencia es lo corriente y no lo anómalo. Levantar ahí convertiría lo normal
    en un error, que es la mitad de la regla 4 que se olvida.

    No hay fixture con el panel vacío, así que se le quita la única fila a la real: lo que se
    prueba es el contrato del parser, no una respuesta que nadie capturó.
    """
    doc = H.fromstring(NOTIF_COBRANZA)
    tabla = doc.xpath('//*[@id="diligenciaCob"]//table')[0]
    for fila in tabla.xpath(".//tr"):
        if fila.xpath("./td"):
            fila.getparent().remove(fila)
    sin_filas = H.tostring(doc, encoding="unicode")
    assert "diligenciaCob" in sin_filas, "se borró el panel entero y no sólo su fila"

    assert parse_diligencias(sin_filas, "cobranza") == []


def test_una_competencia_sin_el_panel_de_diligencias_se_rechaza():
    """Cobranza es la única con el panel medido. En las demás la lista vacía se leería como que
    el ministro de fe no practicó ninguna diligencia, que es otra cosa."""
    with pytest.raises(EstructuraInesperada, match="no publica el panel de diligencias"):
        parse_diligencias(NOTIF_CIVIL, "civil")


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


def test_las_piezas_de_exhorto_tambien_leen_su_columna_de_anexo():
    """El mismo canal, en el panel de al lado, y arreglarlo para un llamador y no para el otro
    es peor que no haberlo arreglado.

    El panel de piezas declara la columna `anexo` igual que la Historia. Ninguna de las seis
    piezas de E-468-2026 la trae llena, así que se rellena una sobre la fixture real: si el
    parser no mira esa columna, el campo sale falso con el enlace puesto.
    """
    piezas = parse_piezas_exhorto(DETALLE, "civil")
    assert piezas is not None
    assert not any(p.tiene_anexo for p in piezas), (
        "si la fixture empieza a traer anexos, este test se reescribe contra el dato real"
    )

    arbol = H.fromstring(DETALLE)
    panel = COMPETENCIAS["civil"].piezas_exhorto
    tabla = arbol.get_element_by_id(panel.panel)
    columna = panel.columnas.index("anexo")
    primera = next(tr for tr in tabla.iter("tr") if len(tr.findall("td")) > columna)
    # Misma forma que las dos celdas de anexo reales de `c1156_apremio`.
    enlace = H.fromstring(
        '<a data-toggle="modal" href="#modalAnexoSolicitudCivil" '
        "onclick=\"anexoSolicitudCivil('referencia-de-prueba');\">anexo</a>"
    )
    primera.findall("td")[columna].append(enlace)

    rellenas = parse_piezas_exhorto(H.tostring(arbol, encoding="unicode"), "civil")
    assert rellenas is not None
    assert sum(p.tiene_anexo for p in rellenas) == 1, (
        "la columna `Anexo` de las piezas no se está leyendo"
    )


def test_un_folio_con_anexo_no_se_agota_en_su_documento_principal():
    """El anexo es un SEGUNDO archivo, y el folio ya entregaba el primero.

    Los dos folios con anexo del cuaderno de apremio de C-1156-2026 son escritos que traen su
    `docuN.php`. O sea el peligro no era que la fila pasara por vacía: era peor. Quien pidiera
    `documento_ruta` recibía un PDF real y quedaba creyendo que tenía el folio completo,
    mientras el anexo seguía ahí sin que nada lo nombrara. Un documento entregado tapa mejor lo
    que falta que una fila en blanco.
    """
    con_anexo = [a for a in parse_historia(C1156_APREMIO) if a.tiene_anexo]
    assert len(con_anexo) == 2, "el cuaderno de apremio trae dos folios con anexo"
    assert all(a.documento_ruta for a in con_anexo), (
        "los dos traen documento principal, que es lo que hacía invisible al anexo"
    )
    assert all(a.tramite == "Escrito" for a in con_anexo)


def test_donde_la_competencia_no_publica_la_columna_el_anexo_es_falso_por_ausencia():
    """Mismo contrato que `georreferenciado`, y por el mismo motivo: falso significa ausente
    sólo donde hay columna. En `penal` no hay Historia medida, así que no se sabe."""
    assert COMPETENCIAS["penal"].historia is None, (
        "si penal pasa a tener Historia medida, el contrato del campo hay que reescribirlo"
    )
    civiles = parse_historia(C1156_APREMIO)
    assert any(a.tiene_anexo for a in civiles), "civil sí publica la columna"
    assert any(not a.tiene_anexo for a in civiles), "y no todos los folios traen anexo"


# -- la causa de la Corte de Apelaciones de la que subió el recurso ------------------


def test_la_causa_de_suprema_dice_de_qué_causa_de_apelaciones_viene():
    """Cierra la arista hacia abajo, igual que el exhorto la cierra hacia el lado.

    Sin esto el detalle de una causa de la Corte Suprema dice que hubo una apelación y no dice
    dónde está la causa apelada, que es donde vive todo lo que pasó antes de llegar acá.
    """
    origen = parse_causa_de_origen(DETALLE_SUPREMA, "suprema")

    assert origen is not None
    assert origen.corte == "C.A. DE CONCEPCIÓN"
    assert origen.libro == "Protección"
    assert origen.recurso == "(Civil) Apelación Protección"

    # El sitio lo publica con espacios alrededor del guion, y se entrega partido en enteros
    # porque es así como lo piden las búsquedas de este servidor.
    assert "14988 - 2020" in DETALLE_SUPREMA, "la fixture dejó de traer el rol espaciado"
    assert origen.rol == 14988
    assert origen.anio == 2020


def test_el_libro_sale_del_panel_y_no_de_la_cabecera_de_la_causa():
    """El panel repite la forma de la cabecera, con la misma clase `table-titulos`, y las dos
    publican un `Libro` con valores distintos.

    La cabecera dice `Civil / 135500 - 2020`, que es la causa que se está mirando; el panel
    dice `Protección`, que es el libro de la causa de la que viene. Buscar el rótulo suelto en
    el documento devuelve el primero, o sea la causa equivocada, y se ve perfectamente bien.
    """
    assert "<strong>Libro :</strong> Civil / 135500 - 2020" in DETALLE_SUPREMA, (
        "la cabecera dejó de publicar su propio Libro: este test ya no cubre la colisión"
    )

    origen = parse_causa_de_origen(DETALLE_SUPREMA, "suprema")

    assert origen is not None
    assert origen.libro == "Protección"


@pytest.mark.parametrize(
    ("competencia", "fixture"),
    [("civil", "detalle_causa_civil.html"), ("laboral", "detalle_laboral.html")],
)
def test_una_competencia_que_no_publica_el_panel_devuelve_nulo(competencia, fixture):
    """El nulo tiene un solo significado acá: esta competencia no publica el panel.

    Sólo suprema lo trae, porque sólo ahí la causa subió desde una Corte de Apelaciones.
    """
    detalle = (FIXTURES / fixture).read_text(encoding="utf-8")

    assert parse_causa_de_origen(detalle, competencia) is None


def test_el_panel_vacío_levanta_en_vez_de_devolver_una_causa_de_origen_sin_datos():
    """La decisión de contrato de este panel, y por qué es levantar.

    Los cuatro rótulos son UN dato, la identidad de una causa: un rol sin corte no ubica nada,
    porque el mismo número existe en las diecisiete. Un objeto con los campos en nulo afirma
    que hay una causa de origen, no dice cuál, y se lee como que el sitio no publica el dato.
    Es la mitad inútil y encima es la que se ve bien.

    El estado vacío tampoco está medido: el sitio trae un aviso `No Existen Registros.` para
    este panel, y en la única respuesta guardada viene oculto JUNTO con los cuatro datos, así
    que no hay con qué distinguir "esta causa no subió de una corte" de "la estructura cambió".
    """
    panel = DETALLE_SUPREMA.index('id="corteApelaciones"')
    tabla = DETALLE_SUPREMA.index("<table", panel)
    fin = DETALLE_SUPREMA.index("</table>", tabla) + len("</table>")
    # Queda el panel con su aviso y sin tabla, que es exactamente la forma en que esta misma
    # respuesta trae `primeraInstancia`.
    vacío = DETALLE_SUPREMA[:tabla] + DETALLE_SUPREMA[fin:]
    assert vacío != DETALLE_SUPREMA, "la fixture no se pudo deformar: el test no probaría nada"

    with pytest.raises(EstructuraInesperada, match="no publica"):
        parse_causa_de_origen(vacío, "suprema")


def test_al_panel_le_falta_un_rótulo_y_levanta_igual():
    """Mismo criterio que el panel vacío, con el modo de falla al revés: acá el sitio sigue
    diciendo de qué corte viene y deja de decir con qué rol.

    Entregar la corte sin el rol es peor que no entregar nada: una corte tramita miles de
    causas, así que el dato no acota nada y sí parece completo.
    """
    sin_rol = DETALLE_SUPREMA.replace("<strong>Rol Ing: </strong>", "<strong>Ingreso: </strong>")
    assert sin_rol != DETALLE_SUPREMA, "la fixture no se pudo deformar"

    with pytest.raises(EstructuraInesperada, match="rol ing"):
        parse_causa_de_origen(sin_rol, "suprema")


def test_un_rol_que_no_es_un_rol_levanta_en_vez_de_entregarlo_en_nulo():
    """Un rol nulo se leería como que el sitio no lo publica, y sin él la causa apelada no se
    puede buscar: la búsqueda por rol exige número y año."""
    torcido = DETALLE_SUPREMA.replace("14988 - 2020", "Sin rol asignado")
    assert torcido != DETALLE_SUPREMA, "la fixture no se pudo deformar"

    with pytest.raises(EstructuraInesperada, match="no es un rol"):
        parse_causa_de_origen(torcido, "suprema")


def test_un_panel_renombrado_no_se_lee_como_que_la_causa_no_viene_de_una_corte():
    """El panel ausente es un estado REAL de la causa, y está medido: tres de dieciséis causas
    de suprema no lo traen, porque no subieron desde una Corte de Apelaciones.

    Por eso acá el nulo no es una salida silenciosa sino la respuesta. Lo que sí levanta es el
    panel presente y sin los cuatro rótulos, que es el caso que nunca se observó: ahí falta
    media identidad de otra causa y con media identidad no se ubica ninguna.

    El costo de haberlo elegido al revés era concreto: `obtener_detalle_causa` reventaba entero
    en casi una de cada cinco causas de suprema.
    """
    renombrado = DETALLE_SUPREMA.replace('id="corteApelaciones"', 'id="corteApelacionesSup"')
    assert renombrado != DETALLE_SUPREMA, "la fixture no se pudo deformar"

    assert parse_causa_de_origen(renombrado, "suprema") is None, (
        "una causa de suprema puede no traer el panel, y está medido: tres de dieciséis. "
        "Levantar ahí se lleva puesto el detalle entero de casi una de cada cinco"
    )


# -- anexos --------------------------------------------------------------------------

#: Cada panel medido con la ruta que lo entregó. Van juntos a propósito: leer uno con el mapa
#: de otro corre los campos, y ésa es justamente la confusión que estos tests cubren.
PANELES_ANEXO = {
    "anexoCausaCivil.php": "anexo_causa_civil.html",
    "anexoCausaSolicitudCivil.php": "anexo_solicitud_civil.html",
    "anexoEscritoLaboral.php": "anexo_escrito_laboral.html",
    "anexoRecursoApelaciones.php": "anexo_recurso_apelaciones.html",
    "escritoSuprema.php": "escrito_suprema.html",
}
ANEXOS_LAB = (FIXTURES / "anexo_escrito_laboral.html").read_text(encoding="utf-8")


def test_el_panel_de_anexos_entrega_con_que_pedir_cada_documento():
    """Medido el 22-08-2026 contra T-196-2026: dos anexos de un mismo escrito.

    Saber que hay anexo no sirve para traerlo. Lo que lo hace pedible es la ruta y la
    referencia del formulario de cada fila, y sin ellas la respuesta dice que existe algo sin
    decir cuál.
    """
    anexos = parse_anexos(ANEXOS_LAB, "anexoEscritoLaboral.php")

    assert [a.folio for a in anexos] == ["70", "71"]
    assert [a.descripcion for a in anexos] == ["Pasajes aéreos", "Comprobantes alojamientos"]
    assert all(a.fecha == date(2026, 8, 13) for a in anexos)
    assert all(a.documento_ruta == "docAnexoLaboral.php" for a in anexos)
    assert all(a.documento_referencia for a in anexos), (
        "sin la referencia del formulario el anexo se sabe que existe y no se puede pedir"
    )


@pytest.mark.parametrize(("ruta", "fixture"), sorted(PANELES_ANEXO.items()))
def test_cada_panel_medido_se_lee_con_su_propio_mapa(ruta, fixture):
    """Los cinco paneles medidos publican columnas distintas, y no son las mismas con otro
    nombre: civil trae tres y no publica folio, apelaciones agrega `Doc. Principal` adelante y
    suprema publica seis que no se parecen a ninguna.

    Lo que este test protege es que cada uno traiga LA DESCARGA, que es lo único que convierte
    "acá hay algo" en un documento que se puede pedir.
    """
    anexos = parse_anexos((FIXTURES / fixture).read_text(encoding="utf-8"), ruta)

    assert anexos, f"{fixture} dejó de traer filas"
    for a in anexos:
        assert a.descripcion, f"{ruta} devolvió un anexo sin descripción: no se sabe qué es"
        assert a.documento_ruta, f"{ruta} devolvió un anexo sin ruta: no se puede pedir"
        assert a.documento_referencia, f"{ruta} devolvió un anexo sin referencia"


def test_leer_un_panel_con_el_mapa_de_otro_se_rechaza():
    """El mapeo es posicional. Con el mapa de laboral, el panel de civil pondría la fecha en el
    folio y la descripción en la fecha: tres columnas donde se esperan cuatro.

    Se rechaza en vez de leer lo que calce, porque una fila con los campos corridos no se ve
    rota: se ve como una fila con otros valores.
    """
    civil = (FIXTURES / "anexo_causa_civil.html").read_text(encoding="utf-8")

    with pytest.raises(EstructuraInesperada, match="columnas"):
        parse_anexos(civil, "anexoEscritoLaboral.php")


def test_una_ruta_de_anexo_sin_medir_no_se_lee_a_la_fuerza():
    """De las dieciocho rutas que el sitio nombra hay cinco medidas. Pedirle a este parser que
    lea otra sería elegirle un mapa por parecido, que es como la fecha termina en la celda de
    la descarga."""
    with pytest.raises(ValueError, match="No está medido"):
        parse_anexos(ANEXOS_LAB, "anexoRequieraseCobranza.php")


def test_un_panel_de_anexos_vacio_levanta_en_vez_de_devolver_lista():
    """Acá la lista vacía NO es un estado real de la causa, y ésa es la diferencia con las
    notificaciones y las liquidaciones.

    Este panel sólo se pide cuando la actuación trajo `anexo_referencia`, o sea cuando el sitio
    ya dijo que hay algo. Cero filas significa que la ruta cambió o que se pidió la
    equivocada, y está medido en este mismo canal: pedir el listado de audios por la ruta
    análoga a la de otro modal respondió 200 con la tabla vacía.
    """
    sin_filas = re.sub(r"<tbody>.*?</tbody>", "<tbody></tbody>", ANEXOS_LAB, flags=re.S)
    assert sin_filas != ANEXOS_LAB

    with pytest.raises(EstructuraInesperada, match="ninguna fila"):
        parse_anexos(sin_filas, "anexoEscritoLaboral.php")


def test_una_columna_insertada_en_el_panel_de_anexos_levanta():
    """El mapeo es posicional: con una columna de más, `Folio` cae en la celda de la descarga y
    el folio que se informa es el de otra cosa."""
    con_otra = ANEXOS_LAB.replace("<th>Folio</th>", "<th>Cuaderno</th><th>Folio</th>", 1)
    assert con_otra != ANEXOS_LAB

    with pytest.raises(EstructuraInesperada, match="columnas"):
        parse_anexos(con_otra, "anexoEscritoLaboral.php")


def test_la_ruta_del_anexo_sale_de_la_celda_y_no_de_la_competencia():
    """Civil abre dos paneles distintos, con parámetros distintos, desde la misma columna.

    Elegir la ruta por competencia serviría uno de los dos, y el otro recibiría la referencia
    del que no es. Eso no da error: da otro panel, que es la falla que no se nota.
    """
    civiles = [a for a in parse_historia(C1156_APREMIO) if a.tiene_anexo]
    assert len(civiles) == 2, "el cuaderno de apremio trae dos folios con anexo"
    assert all(a.anexo_ruta == "anexoCausaSolicitudCivil.php" for a in civiles), (
        f"la ruta no salió de la celda: {[a.anexo_ruta for a in civiles]}"
    )

    laborales = [a for a in parse_historia(DETALLE_LABORAL, competencia="laboral") if a.tiene_anexo]
    assert len(laborales) == 2, "la fixture de laboral trae dos folios con anexo"
    assert all(a.anexo_ruta == "anexoEscritoLaboral.php" for a in laborales)
    assert all(a.anexo_referencia for a in laborales)


def test_el_nombre_del_modal_se_compara_completo_y_no_por_prefijo():
    """`anexoSolicitudCivil` es prefijo de `anexoSolicitudCivilSII`, que vive en OTRA ruta.

    Con una comparación por prefijo, un folio del SII devolvería la ruta del que no es, y
    pedirla no daría error: daría otro panel, con otros documentos, presentados como los de
    este folio. El sufijo `SII` no está medido, así que lo correcto es dejar la ruta en nulo.
    """
    del_sii = C1156_APREMIO.replace("anexoSolicitudCivil(", "anexoSolicitudCivilSII(")
    assert del_sii != C1156_APREMIO

    con_anexo = [a for a in parse_historia(del_sii) if a.tiene_anexo]
    assert len(con_anexo) == 2, "la columna sigue ofreciendo algo"
    assert all(a.anexo_ruta is None for a in con_anexo), (
        f"un modal sin medir devolvió la ruta de otro: {[a.anexo_ruta for a in con_anexo]}"
    )


# -- diligencias de laboral ------------------------------------------------------------

DILIGENCIAS_LAB = (FIXTURES / "diligencias_laboral.html").read_text(encoding="utf-8")
DILIGENCIAS_LAB_ENVIADA = (FIXTURES / "diligencias_laboral_enviada.html").read_text(
    encoding="utf-8"
)


def test_las_diligencias_de_laboral_no_tienen_la_forma_de_las_de_cobranza():
    """Donde cobranza publica `Destinatario` y `Responsable`, laboral publica `Referencia`, y
    la fecha va al final en vez de al medio.

    Leerla con el mapa de cobranza pondría 'Envío Automatico' en el destinatario y correría la
    fecha, que es el modo de falla que no se ve: la fila sale con otros valores, no rota.
    """
    diligencias = parse_diligencias(DILIGENCIAS_LAB, "laboral")

    assert len(diligencias) == 2
    primera = diligencias[0]
    assert primera.estado == "cumplida"
    assert primera.tipo == "Oficio Sala"
    assert primera.referencia == "Envío Automatico"
    assert primera.fecha_tramite == date(2023, 4, 20)
    assert primera.destinatario is None, "laboral no publica la columna"
    assert primera.responsable is None, "laboral tampoco publica ésta"


def test_una_diligencia_enviada_no_trae_el_documento_de_vuelta():
    """La ausencia del segundo documento es el dato: el oficio salió y todavía no vuelve.

    Está medido en los dos sentidos: la `cumplida` trae los dos documentos y la `enviada` sólo
    el de ida. Sin esta distinción, las dos se ven igual.
    """
    cumplida = parse_diligencias(DILIGENCIAS_LAB, "laboral")[0]
    enviada = parse_diligencias(DILIGENCIAS_LAB_ENVIADA, "laboral")[0]

    assert cumplida.documento_ida_ruta == "docDiligenciaIdaLaboral.php"
    assert cumplida.documento_vuelta_ruta == "docDiligenciaVueltaLaboral.php"
    assert cumplida.documento_ida_referencia
    assert cumplida.documento_vuelta_referencia

    assert enviada.estado == "enviada"
    assert enviada.documento_ida_ruta == "docDiligenciaIdaLaboral.php"
    assert enviada.documento_vuelta_ruta is None
    assert enviada.documento_vuelta_referencia is None


def test_leer_las_diligencias_de_laboral_con_el_mapa_de_cobranza_se_rechaza():
    """Dos guardias encadenados, y conviene ver los dos.

    El primero es el nombre del panel: `diligenciaCob` no existe en un detalle de laboral. El
    segundo es el que importa cuando el nombre sí calza, y por eso se fuerza: nueve columnas
    donde hay ocho, cortado por cantidad y posición antes de que ninguna fila salga con los
    campos corridos.
    """
    with pytest.raises(EstructuraInesperada, match="No existe el panel"):
        parse_diligencias(DILIGENCIAS_LAB, "cobranza")

    con_el_id_de_cobranza = DILIGENCIAS_LAB.replace('id="diligenciasLab"', 'id="diligenciaCob"')
    assert con_el_id_de_cobranza != DILIGENCIAS_LAB

    with pytest.raises(EstructuraInesperada, match="columnas"):
        parse_diligencias(con_el_id_de_cobranza, "cobranza")


# -- escritos por resolver -------------------------------------------------------------

ESCRITOS = (FIXTURES / "escritos_civil.html").read_text(encoding="utf-8")


def test_los_escritos_por_resolver_son_la_cola_y_no_el_historial():
    """Medido el 22-08-2026 sobre una causa civil de dos días: dos escritos esperando proveído.

    Es lo que responde "¿ya me proveyeron?", que no es lo que responde la Historia: ahí el
    escrito aparece cuando YA fue resuelto.
    """
    escritos = parse_escritos_pendientes(ESCRITOS)

    assert [e.tipo for e in escritos] == ["Designación de Martillero", "Ingreso Exhorto"]
    assert all(e.fecha_ingreso == date(2026, 8, 20) for e in escritos)
    assert all(e.solicitante == "Demandante" for e in escritos)
    assert all(e.documento_ruta == "docuN.php" for e in escritos)
    assert all(e.documento_referencia for e in escritos), (
        "sin la referencia el escrito se sabe que existe y no se puede leer"
    )


def test_un_escrito_por_resolver_trae_con_que_pedir_sus_anexos():
    """Los escritos son la SEGUNDA fuente de una ruta de anexo, y la única de la de
    `anexoCausaSolEscritoCivil`: no cuelga de ningún folio de la Historia.

    Sin leer esta celda, un escrito que acompañó documentos se ve igual que uno que no.
    """
    con_anexo = [e for e in parse_escritos_pendientes(ESCRITOS) if e.tiene_anexo]

    assert len(con_anexo) == 1, "uno de los dos escritos medidos acompañó documentos"
    assert con_anexo[0].anexo_ruta == "anexoCausaSolEscritoCivil.php"
    assert con_anexo[0].anexo_referencia


def test_una_causa_sin_escritos_por_resolver_devuelve_lista_vacia():
    """Acá la lista vacía SÍ es una respuesta: no queda nada por proveer, que es el estado
    normal de una causa al día.

    Las cuatro fixtures viejas de civil lo traen vacío con escritos de sobra en su Historia,
    porque ya fueron resueltos. Levantar acá diría que la respuesta vino rota.
    """
    assert parse_escritos_pendientes(C1156_PRINCIPAL) == []
    assert parse_escritos_pendientes(DETALLE) == []


def test_una_competencia_sin_el_panel_medido_no_se_lee_con_el_mapa_de_civil():
    """En laboral el panel se llama `EscPendLab` y publica seis columnas donde civil trae
    cinco. Leerlo con este mapa correría el solicitante al tipo de escrito."""
    with pytest.raises(EstructuraInesperada, match="escritos por resolver"):
        parse_escritos_pendientes(DETALLE_LABORAL, competencia="laboral")


def test_una_columna_insertada_en_los_escritos_levanta():
    """El mapeo es posicional: con una columna de más, la fecha de ingreso cae en la celda del
    anexo y el tipo de escrito informa una fecha."""
    con_otra = ESCRITOS.replace("<th>Anexo</th>", "<th>Cuaderno</th><th>Anexo</th>", 1)
    assert con_otra != ESCRITOS

    with pytest.raises(EstructuraInesperada, match="columnas"):
        parse_escritos_pendientes(con_otra)


# -- audios de audiencia ---------------------------------------------------------------

AUDIOS = (FIXTURES / "listado_audio_laboral.html").read_text(encoding="utf-8")


def test_el_listado_de_audios_trae_el_tramo_de_cada_archivo_y_su_enlace():
    """Medido el 22-08-2026: once archivos para UNA audiencia preparatoria.

    El audio viene troceado por acto procesal, y el nombre del archivo es lo único que dice de
    qué tramo es: la columna `Fecha` viene vacía en los once. Perder el nombre al leerlo
    dejaría once archivos indistinguibles.
    """
    audios = parse_audios(AUDIOS)

    assert [a.numero for a in audios] == [str(n) for n in range(1, 12)]
    assert all(a.archivo.endswith(".mp3") for a in audios)
    assert audios[0].archivo.endswith("Inicio Aud 10.10, Indiv de las partes.mp3")
    assert audios[-1].archivo.endswith("Fin Aud 10.45.mp3")
    assert all(a.fecha is None for a in audios), (
        "la columna `Fecha` viene vacía en los once, y si empieza a traer algo hay que mirarlo"
    )
    assert all(a.descarga_url.startswith("https://") for a in audios), (
        "el enlace se entrega para abrirlo en un navegador: relativo no sirve"
    )
    assert len({a.descarga_url for a in audios}) == len(audios), (
        "dos archivos con el mismo enlace significan que la referencia no se está leyendo"
    )


def test_un_listado_de_audios_vacio_levanta_en_vez_de_devolver_lista():
    """Sólo se pide cuando la cabecera ofreció el enlace, o sea cuando el sitio ya dijo que hay
    grabación. Cero filas devueltas como lista se leen como "esta audiencia no se grabó"."""
    sin_filas = re.sub(r"<tbody>.*?</tbody>", "<tbody></tbody>", AUDIOS, flags=re.S)
    assert sin_filas != AUDIOS

    with pytest.raises(EstructuraInesperada, match="ninguna fila"):
        parse_audios(sin_filas)


def test_una_fila_de_audio_sin_enlace_levanta():
    """Entregarla igual diría que el archivo está disponible, y no habría con qué pedirlo."""
    sin_enlace = AUDIOS.replace("action=download", "action=otro")
    assert sin_enlace != AUDIOS

    with pytest.raises(EstructuraInesperada, match="enlace de descarga"):
        parse_audios(sin_enlace)


def test_el_correlativo_del_audio_va_en_un_th_dentro_de_la_fila():
    """El sitio pone el número en un `th`, no en un `td`, así que la cabecera declara cinco
    columnas y cada fila trae cuatro celdas.

    Descartar las filas por no alcanzar el largo de la cabecera, que es lo que hacen los demás
    paneles, dejaba el listado en cero: once archivos informados como ninguno.
    """
    doc = H.fromstring(AUDIOS)
    fila = next(tr for tr in doc.iter("tr") if tr.findall("td"))

    assert len(fila.findall("td")) == 4
    assert len(fila.findall("th")) == 1


def test_una_causa_sin_audiencia_grabada_no_inventa_referencia():
    """La cabecera de laboral ofrece el listado; la de civil no lo publica.

    Las dos vuelven como nulo y eso es correcto: el sitio no distingue "no hubo grabación" de
    "esta competencia no lo publica", así que inventar la diferencia sería afirmar de más.
    """
    assert audio_de_la_causa(DETALLE_LABORAL), "la fixture de laboral ofrece el listado"
    assert audio_de_la_causa(DETALLE) is None, "civil no publica el enlace de audios"


def test_el_modal_de_audio_se_compara_por_nombre_completo():
    """Mismo criterio que los anexos: la competencia medida es laboral, y un nombre que empiece
    igual puede ser otra ruta. Un prefijo devolvería la referencia de una competencia sin
    medir, y pedirla no da error sino otra página."""
    otra = DETALLE_LABORAL.replace("listadoAudioLaboral(", "listadoAudioLaboralAntiguo(")
    assert otra != DETALLE_LABORAL

    assert audio_de_la_causa(otra) is None


def test_un_modal_de_anexo_sin_medir_deja_la_ruta_en_nulo_y_el_anexo_en_verdadero():
    """El contrato de siempre: hay algo y este servidor no lo puede traer.

    Se comprueba con una función inventada sobre la fixture real, porque las cinco medidas
    cubren las cinco competencias con Historia y no queda ninguna sin medir que sirva de caso.
    Devolver la referencia igual sería nombrar como medido un panel que nadie miró.
    """
    otra = DETALLE_LABORAL.replace("anexoEscritoLaboral(", "anexoEscritoLaboralPendiente(")
    assert otra != DETALLE_LABORAL

    con_anexo = [a for a in parse_historia(otra, competencia="laboral") if a.tiene_anexo]
    assert len(con_anexo) == 2, "la columna sigue ofreciendo algo aunque el modal no esté medido"
    assert all(a.anexo_ruta is None and a.anexo_referencia is None for a in con_anexo)


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
