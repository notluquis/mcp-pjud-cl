"""Qué pasa cuando la plataforma cambia una tabla.

`mutmut` muta el CÓDIGO. Nada mutaba la ENTRADA, y ahí está el modo de falla que importa: el
parser mapea las celdas por posición, así que un cambio de columnas en el sitio no rompe el
parseo, lo corre. Y una fila corrida no se ve rota: se ve como una fila con otros valores.

Cada caso de acá deforma una fixture real de una manera que la plataforma podría deformarla, y
exige `EstructuraInesperada`. La regla 4 dice fallo ruidoso, nunca lista vacía; esto es lo que
comprueba que la regla siga valiendo cuando el sitio se mueva.
"""

from pathlib import Path

import pytest
from lxml import html as L

from mcp_pjud.parser import (
    EstructuraInesperada,
    parse_diligencias,
    parse_historia,
    parse_liquidaciones,
    parse_notificaciones,
    parse_piezas_exhorto,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _historia(html_detalle: str, competencia: str):
    """`parse_historia` toma el CUADERNO como segundo posicional, no la competencia.

    Pasarle la competencia ahí dejaba `competencia="civil"` por defecto, así que los cuatro
    paneles no civiles levantaban por no encontrar `historiaCiv`, antes de mirar siquiera la
    deformación. Veinte aserciones de este archivo pasaban por la razón equivocada: el guardia
    no podía fallar, que es justo lo que este archivo existe para detectar en otros.
    """
    return parse_historia(html_detalle, competencia=competencia)


#: Cada panel mapeado, con la fixture que lo contiene y la función que lo lee.
PANELES = [
    ("historiaCiv", "detalle_causa_civil", "civil", _historia),
    ("historiaCob", "detalle_cobranza", "cobranza", _historia),
    ("movimientosSup", "detalle_suprema", "suprema", _historia),
    ("movimientosApe", "detalle_apelaciones", "apelaciones", _historia),
    ("movimientoLab", "detalle_laboral", "laboral", _historia),
    ("notificacionesCiv", "detalle_civil_notificaciones", "civil", parse_notificaciones),
    ("notificacionCob", "detalle_cobranza", "cobranza", parse_notificaciones),
    ("notificacionesLab", "detalle_laboral", "laboral", parse_notificaciones),
    ("liquidacionCob", "detalle_cobranza", "cobranza", parse_liquidaciones),
    # Nueve columnas y una sola fila medida, o sea el panel donde una columna insertada tiene
    # más margen para pasar inadvertida: no hay una segunda fila que se vea distinta.
    ("diligenciaCob", "detalle_cobranza", "cobranza", parse_diligencias),
    # Nueve columnas, con `Cuaderno` al medio: es el mapa posicional más ancho después de
    # la Historia, y el único con encabezados que traen una errata del sitio.
    ("piezasExhortoCiv", "detalle_causa_civil", "civil", parse_piezas_exhorto),
]

IDS = [f"{p}-{c}" for p, _, c, _ in PANELES]


def _fixture(nombre: str) -> str:
    return (FIXTURES / f"{nombre}.html").read_text(encoding="utf-8")


def _panel(doc, panel: str):
    """El div del panel.

    `doc` va sin anotar a propósito: `xpath` declara devolver una unión de listas, cadenas y
    números que el chequeador de tipos no puede estrechar, y anotarlo obligaría a un cast que
    no aporta nada a la prueba.
    """
    return doc.xpath(f'//*[@id="{panel}"]')[0]


def _tabla(doc, panel: str):
    return _panel(doc, panel).xpath(".//table")[0]


def _deformar(html_original: str, panel: str, como) -> str:
    """Aplica `como` a la tabla del panel y devuelve el HTML resultante."""
    doc = L.fromstring(html_original)
    como(_tabla(doc, panel))
    return L.tostring(doc, encoding="unicode")


@pytest.mark.parametrize(("panel", "fixture", "competencia", "leer"), PANELES, ids=IDS)
def test_una_columna_insertada_al_medio_no_pasa_en_silencio(panel, fixture, competencia, leer):
    """El caso que este archivo existe para cubrir.

    Si la plataforma agrega una columna, los encabezados que se exigían siguen estando y las
    filas traen una celda de más, así que ninguna comprobación por pertenencia se entera. El
    mapa posicional corre todos los campos posteriores: en la Historia eso deja
    `fecha_diligencia` en nulo y el `tramite` corrido, con lo que `actuaciones_receptor`
    devuelve lista vacía SIN error. El falso negativo aparece una capa por encima del guardia
    de cero filas.
    """

    def insertar(tabla) -> None:
        for fila in tabla.xpath(".//tr"):
            celdas = fila.xpath("./th | ./td")
            if len(celdas) < 3:
                continue
            nueva = L.Element(celdas[1].tag)
            nueva.text = "columna nueva del sitio"
            celdas[1].addnext(nueva)

    with pytest.raises(EstructuraInesperada):
        leer(_deformar(_fixture(fixture), panel, insertar), competencia)


@pytest.mark.parametrize(("panel", "fixture", "competencia", "leer"), PANELES, ids=IDS)
def test_dos_columnas_permutadas_no_pasan_en_silencio(panel, fixture, competencia, leer):
    """Peor que insertar, porque ni siquiera cambia la cantidad de celdas.

    Reordenar dos columnas deja todo del mismo largo y con los mismos encabezados presentes.
    Sin comparar posiciones, el parseo entrega los valores intercambiados y no hay nada que
    delate el problema.
    """

    def permutar(tabla) -> None:
        for fila in tabla.xpath(".//tr"):
            celdas = fila.xpath("./th | ./td")
            if len(celdas) < 3:
                continue
            celdas[1].addprevious(celdas[2])

    with pytest.raises(EstructuraInesperada):
        leer(_deformar(_fixture(fixture), panel, permutar), competencia)


@pytest.mark.parametrize(("panel", "fixture", "competencia", "leer"), PANELES, ids=IDS)
def test_un_encabezado_renombrado_no_pasa_en_silencio(panel, fixture, competencia, leer):
    def renombrar(tabla) -> None:
        for th in tabla.xpath(".//th"):
            th.text = "columna con otro nombre"

    with pytest.raises(EstructuraInesperada):
        leer(_deformar(_fixture(fixture), panel, renombrar), competencia)


@pytest.mark.parametrize(("panel", "fixture", "competencia", "leer"), PANELES, ids=IDS)
def test_el_panel_que_desaparece_no_pasa_en_silencio(panel, fixture, competencia, leer):
    """Un panel renombrado es lo más probable en un rediseño, y buscar un id que no está
    devuelve vacío, que se lee como que no hubo nada."""
    doc = L.fromstring(_fixture(fixture))
    _panel(doc, panel).set("id", f"{panel}Renombrado")

    with pytest.raises(EstructuraInesperada):
        leer(L.tostring(doc, encoding="unicode"), competencia)


@pytest.mark.parametrize(("panel", "fixture", "competencia", "leer"), PANELES, ids=IDS)
def test_una_columna_borrada_no_pasa_en_silencio(panel, fixture, competencia, leer):
    def borrar(tabla) -> None:
        for fila in tabla.xpath(".//tr"):
            celdas = fila.xpath("./th | ./td")
            if len(celdas) < 3:
                continue
            celdas[1].getparent().remove(celdas[1])

    with pytest.raises(EstructuraInesperada):
        leer(_deformar(_fixture(fixture), panel, borrar), competencia)
