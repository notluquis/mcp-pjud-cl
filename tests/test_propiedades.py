"""Pruebas basadas en propiedades del parser de fechas.

Los tests con ejemplos comprueban los casos que se nos ocurrieron. Estos comprueban
invariantes sobre entradas que nadie escribió a mano, que es donde aparecen los casos
que no se nos ocurrieron.

La invariante que más importa está en `test_nunca_inventa_una_fecha`: el parser jamás
debe devolver una fecha que no venga en la entrada. Inventar una fecha de diligencia es
peor que no devolver ninguna, porque una fecha inventada se computa como plazo.
"""

from datetime import date, time

from hypothesis import given, settings
from hypothesis import strategies as st

from mcp_pjud.parser import actuaciones_receptor, parse_historia

#: Sin plazo por ejemplo. Estas propiedades parsean HTML con lxml, y el plazo de 200 ms que
#: Hypothesis trae por defecto mide el reloj de la máquina y no la propiedad: en una corrida
#: con la máquina cargada uno de los ejemplos lo excedió, se reportó como propiedad
#: falsificada, y el caso guardado pasaba al reproducirlo. Un test que falla según la carga
#: enseña a desconfiar de la suite, que es peor que no tenerlo.
settings.register_profile("sin_plazo", deadline=None)
settings.load_profile("sin_plazo")

# Fechas dentro del rango que la plataforma puede devolver.
fechas = st.dates(min_value=date(1990, 1, 1), max_value=date(2099, 12, 31))
horas = st.times().map(lambda t: t.replace(second=0, microsecond=0))
# Texto libre para las celdas.
#
# Se excluyen `<>&"'` porque romperían el HTML de la fixture sintética, no el parser.
#
# Se excluyen también los sustitutos (categoría Cs), por una razón que conviene dejar
# escrita. Hypothesis los generó y descubrió que lxml perdía la fila y el parser devolvía
# una lista vacía sin avisar. Un sustituto no emparejado no puede llegar desde la
# plataforma, que sirve UTF-8, así que se sacan del generador. Pero la falla que
# destaparon sí era real y se arregló donde correspondía: `parse_historia` ahora levanta
# excepción cuando encuentra encabezados y cero filas, forma que también produce una
# respuesta truncada. Ver test_tabla_con_encabezados_y_cero_filas_levanta_excepcion.
texto = st.text(
    alphabet=st.characters(blacklist_characters="<>&\"'", blacklist_categories=("Cs",)),
    max_size=40,
)


def cl(f: date) -> str:
    """Formato chileno, como lo emite la plataforma."""
    return f"{f.day:02d}/{f.month:02d}/{f.year}"


def historia(desc: str, fec: str, georref: str = "") -> str:
    return f"""<div id="historiaCiv"><table>
      <thead><tr><th>Folio</th><th>Doc.</th><th>Anexo</th><th>Etapa</th>
      <th>Tr&aacute;mite</th><th>Desc. Tr&aacute;mite</th><th>Fec. Tr&aacute;mite</th>
      <th>Foja</th><th>Georref.</th></tr></thead><tbody>
      <tr><td>1</td><td></td><td></td><td>Exhorto</td><td>Actuación Receptor</td>
      <td>{desc}</td><td>{fec}</td><td>0</td><td>{georref}</td></tr>
      </tbody></table></div>"""


@given(registro=fechas, diligencia=fechas)
def test_el_parentesis_siempre_gana_sobre_la_descripcion(registro, diligencia):
    """Cuando 'Fec. Trámite' trae paréntesis, esa es la fecha de diligencia.

    Vale incluso si la descripción dice otra cosa: en ese caso se marca la
    discrepancia, pero la fecha entregada es la del paréntesis.
    """
    doc = historia("NOTIFICACIÓN", f"{cl(registro)} ({cl(diligencia)})")
    a = actuaciones_receptor(doc)[0]
    assert a.fecha_diligencia == diligencia
    assert a.fecha_registro == registro


@given(registro=fechas, dilig_parentesis=fechas, dilig_desc=fechas, hora=horas)
def test_la_discrepancia_se_marca_exactamente_cuando_difieren(
    registro, dilig_parentesis, dilig_desc, hora
):
    doc = historia(
        f"NOTIFICACIÓN Diligencia:{cl(dilig_desc)} {hora.hour:02d}:{hora.minute:02d}",
        f"{cl(registro)} ({cl(dilig_parentesis)})",
    )
    a = actuaciones_receptor(doc)[0]
    assert a.discrepancia_fechas == (dilig_parentesis != dilig_desc)


@given(registro=fechas, diligencia=fechas, hora=horas)
def test_nunca_inventa_una_fecha(registro, diligencia, hora):
    """La invariante que más importa.

    Toda fecha que el parser devuelve tiene que estar en la entrada. Una fecha de
    diligencia inventada se computa como plazo, y eso es peor que no devolver ninguna.
    """
    doc = historia(
        f"X Diligencia:{cl(diligencia)} {hora.hour:02d}:{hora.minute:02d}",
        f"{cl(registro)} ({cl(diligencia)})",
    )
    a = actuaciones_receptor(doc)[0]
    entrada = {registro, diligencia}
    assert a.fecha_diligencia in entrada
    assert a.fecha_registro in entrada


@given(desc=texto, fec=texto)
def test_nunca_revienta_con_texto_arbitrario(desc, fec):
    """Ante celdas con contenido inesperado, devolver la fila con fechas nulas.

    Lo que no puede pasar es que una fila rara haga caer toda la consulta: el resto de
    las actuaciones de la causa se perdería.
    """
    actuaciones = parse_historia(historia(desc, fec))
    assert len(actuaciones) == 1
    a = actuaciones[0]
    assert a.fecha_diligencia is None or isinstance(a.fecha_diligencia, date)
    assert a.hora_diligencia is None or isinstance(a.hora_diligencia, time)


@given(registro=fechas)
def test_sin_parentesis_no_hay_fecha_de_diligencia_salvo_que_la_traiga_la_descripcion(registro):
    a = actuaciones_receptor(historia("CERTIFICACIÓN", cl(registro)))[0]
    assert a.fecha_registro == registro
    assert a.fecha_diligencia is None


@given(diligencia=fechas, registro=fechas, hora=horas)
@settings(max_examples=50)
def test_la_hora_solo_sale_de_la_descripcion(diligencia, registro, hora):
    con_hora = historia(
        f"X Diligencia:{cl(diligencia)} {hora.hour:02d}:{hora.minute:02d}",
        f"{cl(registro)} ({cl(diligencia)})",
    )
    sin_hora = historia("X", f"{cl(registro)} ({cl(diligencia)})")
    assert actuaciones_receptor(con_hora)[0].hora_diligencia == hora
    assert actuaciones_receptor(sin_hora)[0].hora_diligencia is None
