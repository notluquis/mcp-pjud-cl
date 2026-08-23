"""Qué pasa cuando la plataforma cambia una tabla.

`mutmut` muta el CÓDIGO. Nada mutaba la ENTRADA, y ahí está el modo de falla que importa: el
parser mapea las celdas por posición, así que un cambio de columnas en el sitio no rompe el
parseo, lo corre. Y una fila corrida no se ve rota: se ve como una fila con otros valores.

Cada caso de acá deforma una fixture real de una manera que la plataforma podría deformarla, y
exige `EstructuraInesperada`. La regla 4 dice fallo ruidoso, nunca lista vacía; esto es lo que
comprueba que la regla siga valiendo cuando el sitio se mueva.

Qué paneles se deforman NO se escribe acá: sale de `parser.COMPETENCIAS`, que es donde se
declaran. Este archivo sólo dice con qué fixture y con qué función se lee cada uno, y dos
guardias comparan las dos listas. La versión anterior enumeraba los paneles a mano y se quedó
corta tres veces seguidas: la última dejó doce de los veintitrés sin deformar, entre ellos los
cinco de litigantes, que son quiénes son parte en el juicio.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from lxml import html as L

from mcp_pjud import parser
from mcp_pjud.parser import (
    EstructuraInesperada,
    parse_causas_agregadas,
    parse_diligencias,
    parse_escritos_pendientes,
    parse_exhortos,
    parse_historia,
    parse_liquidaciones,
    parse_litigantes,
    parse_materias,
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


#: Con qué fixture y con qué función se lee cada panel, del `id` del panel a la terna.
#:
#: Esto NO declara qué paneles existen: `test_todo_panel_declarado_se_deforma` compara las
#: claves contra los `Panel` de `parser.COMPETENCIAS` y se pone rojo si falta alguno.
#:
#: La fixture elegida es una que trae FILAS, y no cualquiera que traiga el panel. Varios
#: paneles vienen vacíos en el detalle completo y con filas en un fragmento que el sitio sirve
#: aparte (`escritos_civil`, `diligencias_laboral`), y con el panel vacío las cuatro
#: deformaciones que tocan celdas alcanzan sólo la fila de encabezado: la prueba se debilita
#: sin que se note. El control de más abajo exige esa fila.
LECTURAS: dict[str, tuple[str, str, Callable[[str, str], object]]] = {
    "movimientosSup": ("detalle_suprema", "suprema", _historia),
    "litigantesSup": ("detalle_suprema", "suprema", parse_litigantes),
    "agregadosSup": ("detalle_suprema", "suprema", parse_causas_agregadas),
    "movimientosApe": ("detalle_apelaciones", "apelaciones", _historia),
    "litigantesApe": ("detalle_apelaciones", "apelaciones", parse_litigantes),
    "historiaCiv": ("detalle_causa_civil", "civil", _historia),
    "litigantesCiv": ("detalle_causa_civil", "civil", parse_litigantes),
    "notificacionesCiv": ("detalle_civil_notificaciones", "civil", parse_notificaciones),
    # El panel viene vacío en las dos respuestas civiles del detalle guardado y con una fila en
    # las dos de `C-1156`, así que la fixture sale de ahí.
    "exhortosCiv": ("c1156_principal", "civil", parse_exhortos),
    # Nueve columnas, con `Cuaderno` al medio: es el mapa posicional más ancho después de
    # la Historia, y el único con encabezados que traen una errata del sitio.
    "piezasExhortoCiv": ("detalle_causa_civil", "civil", parse_piezas_exhorto),
    "escritosCiv": ("escritos_civil", "civil", parse_escritos_pendientes),
    "movimientoLab": ("detalle_laboral", "laboral", _historia),
    "litigantesLab": ("detalle_laboral", "laboral", parse_litigantes),
    "materiasLab": ("detalle_laboral", "laboral", parse_materias),
    "liquidacionLab": ("detalle_laboral", "laboral", parse_liquidaciones),
    "notificacionesLab": ("detalle_laboral", "laboral", parse_notificaciones),
    "diligenciasLab": ("diligencias_laboral", "laboral", parse_diligencias),
    "EscPendLab": ("detalle_laboral", "laboral", parse_escritos_pendientes),
    "historiaCob": ("detalle_cobranza", "cobranza", _historia),
    "litigantesCob": ("detalle_cobranza", "cobranza", parse_litigantes),
    "liquidacionCob": ("detalle_cobranza", "cobranza", parse_liquidaciones),
    "notificacionCob": ("detalle_cobranza", "cobranza", parse_notificaciones),
    # Nueve columnas y una sola fila medida, o sea el panel donde una columna insertada tiene
    # más margen para pasar inadvertida: no hay una segunda fila que se vea distinta.
    "diligenciaCob": ("detalle_cobranza", "cobranza", parse_diligencias),
}

PANELES = [(panel, fixture, comp, leer) for panel, (fixture, comp, leer) in LECTURAS.items()]

IDS = [f"{p}-{c}" for p, _, c, _ in PANELES]


def _paneles_declarados() -> dict[str, str]:
    """Todo `Panel` que `COMPETENCIAS` declara, del `id` del panel a su competencia.

    Se itera la tupla entera en vez de nombrar los campos que pueden traer un `Panel`.
    `Competencia` ya declara diez y cada panel nuevo agrega otro, así que una lista de nombres
    de campo se quedaría corta por exactamente la misma razón por la que se quedó corta la
    lista de paneles que esto reemplaza.

    `causa_de_origen` queda afuera, y no por olvido: es un `str` con el `id` del panel porque
    ese panel no es una tabla de filas sino pares de rótulo y valor. No tiene encabezados que
    comparar ni mapeo posicional del que protegerse, así que estas cinco deformaciones no
    tienen qué deformar en él.
    """
    return {
        valor.panel: competencia
        for competencia, spec in parser.COMPETENCIAS.items()
        for valor in spec
        if isinstance(valor, parser.Panel)
    }


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


def _reescribir(html_original: str, cambiar) -> str:
    """Aplica `cambiar` al árbol y devuelve el HTML, exigiendo que algo haya cambiado.

    El `assert` sostiene todo lo demás. Una deformación que no deforma nada deja el caso verde
    sin haber probado nada, y se ve idéntica a una que sí funcionó: el `pytest.raises` de más
    abajo sólo diría que la lectura levantó, que es lo que ya hace con la fixture intacta si
    algo más está mal. Las cuatro deformaciones de celdas saltan las filas de menos de tres
    columnas, y un panel angosto o una fila que el sitio arme distinto las volvería inertes sin
    aviso.
    """
    doc = L.fromstring(html_original)
    cambiar(doc)
    nuevo = L.tostring(doc, encoding="unicode")
    assert nuevo != html_original, (
        "La deformación no cambió el HTML, así que este caso no prueba nada: lo que levante "
        "después no puede venir de ella."
    )
    return nuevo


def _deformar(html_original: str, panel: str, como) -> str:
    """Aplica `como` a la tabla del panel y devuelve el HTML resultante."""
    return _reescribir(html_original, lambda doc: como(_tabla(doc, panel)))


def test_todo_panel_declarado_se_deforma():
    """Un panel nuevo en `COMPETENCIAS` que nadie agregue acá pone la suite en rojo.

    Es lo que reemplaza a la lista escrita a mano, que se quedó corta tres veces seguidas sin
    que nada lo dijera: los paneles nuevos entraban con sus tests de lectura, la suite quedaba
    verde, y el único arnés que comprueba que su mapeo posicional no se corra en silencio no
    los miraba. Un panel sin cubrir no da un error, da una fila corrida que se ve plausible.
    """
    faltan = sorted(set(_paneles_declarados()) - set(LECTURAS))
    assert not faltan, (
        f"`parser.COMPETENCIAS` declara estos paneles y este archivo no los deforma: {faltan}. "
        "Agrégalos a `LECTURAS` con una fixture que traiga filas y la función que los lee. Sin "
        "eso, el día que la plataforma les mueva una columna el mapeo posicional corre los "
        "campos y la respuesta sale plausible y falsa."
    )


def test_no_se_deforma_un_panel_que_ya_no_se_declara():
    """La dirección contraria: una entrada que sobrevive al panel que leía.

    Sin esto, borrar un panel de `COMPETENCIAS` deja acá una entrada que apunta a un `id` que
    ya no existe. Los cinco casos seguirían verdes, porque un panel que no está levanta
    `EstructuraInesperada` igual que uno deformado, y estarían midiendo la ausencia.
    """
    sobran = sorted(set(LECTURAS) - set(_paneles_declarados()))
    assert not sobran, (
        f"Estas entradas de `LECTURAS` no corresponden a ningún `Panel` de "
        f"`parser.COMPETENCIAS`: {sobran}. Sus cinco casos pasan por la ausencia del panel, no "
        "por la deformación."
    )


@pytest.mark.parametrize(("panel", "fixture", "competencia", "leer"), PANELES, ids=IDS)
def test_la_fixture_sin_deformar_se_lee(panel, fixture, competencia, leer):
    """El control que hace que los cinco de abajo signifiquen algo.

    Los cinco exigen `EstructuraInesperada` sobre una fixture deformada. Si la fixture SIN
    deformar tampoco se pudiera leer (competencia equivocada, fixture que no trae el panel,
    función que no le corresponde), los cinco pasarían igual y por la razón contraria: estarían
    midiendo que la lectura no funciona. Ya ocurrió acá, con la competencia colada en el
    parámetro del cuaderno.

    Y exige además que la fixture elegida traiga filas, salvo en los tres paneles que
    `SIN_FILAS_OBSERVADAS` declara vacíos. De esos sólo se midió el encabezado, así que las
    cuatro deformaciones de celdas alcanzan sólo esa fila y la validación de encabezados es
    toda la protección que tienen. No se saltan por eso: son justamente los que más la
    necesitan, porque el día que una causa traiga una fila se va a leer del mapa que hoy nadie
    contrastó contra una fila real.
    """
    filas = leer(_fixture(fixture), competencia)
    if panel in parser.SIN_FILAS_OBSERVADAS:
        assert filas == [], (
            f"El panel {panel!r} figura en `parser.SIN_FILAS_OBSERVADAS` y la fixture "
            f"{fixture!r} ahora le trae filas. Deja de ser cierto que sólo se midió su "
            "encabezado, y hay comentarios en el parser que lo afirman."
        )
    else:
        assert filas, (
            f"El panel {panel!r} se lee de {fixture!r} y ahí viene sin filas. Las cuatro "
            "deformaciones de celdas alcanzarían sólo el encabezado, que prueba menos, y acá "
            "no se notaría. Busca una fixture con filas o declara el panel en "
            "`parser.SIN_FILAS_OBSERVADAS`."
        )


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

    def renombrar_el_panel(doc) -> None:
        _panel(doc, panel).set("id", f"{panel}Renombrado")

    with pytest.raises(EstructuraInesperada):
        leer(_reescribir(_fixture(fixture), renombrar_el_panel), competencia)


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
