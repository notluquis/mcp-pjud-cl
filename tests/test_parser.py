"""Tests del parser contra HTML real de la Oficina Judicial Virtual.

El fixture es E-468-2026 del 3º Juzgado Civil de Concepción: un exhorto con la
secuencia completa de actuaciones (búsquedas negativas, certificación positiva,
notificación exitosa y requerimiento ficto), todas con formato de fecha doble.
"""

from datetime import date, time
from pathlib import Path

import pytest

from mcp_pjud.parser import (
    EstructuraInesperada,
    actuaciones_receptor,
    parse_cuadernos,
    parse_historia,
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
    assert folio10.desc_tramite == (
        "NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:17/06/2026 14:25"
    )


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
    embargo = next(
        a for a in actuaciones_receptor(C1156_APREMIO) if "EMBARGO" in a.desc_tramite
    )
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
