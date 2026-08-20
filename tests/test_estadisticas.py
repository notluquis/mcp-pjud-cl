"""La mezcla de las fotos de tráfico.

Estos CSV son la ÚNICA copia del tráfico después de que la ventana de catorce días de GitHub
caduque: lo que se pierda acá no se puede volver a pedir. Un error en la mezcla no rompería
nada visible, corrompería el archivo en silencio, que es la forma de falla que este proyecto
entero existe para no cometer.

El script vive en `.github/scripts/` y no en el paquete: no se publica en la rueda porque no
tiene nada que hacer en el servidor MCP. Se importa por ruta.
"""

import csv
import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]


@pytest.fixture
def estadisticas(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "_estadisticas", RAIZ / ".github" / "scripts" / "estadisticas.py"
    )
    assert spec is not None
    assert spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo, "DESTINO", tmp_path)
    return modulo


def leer(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


CAMPOS = ["fecha", "vistas"]


def test_una_foto_nueva_no_duplica_los_dias_que_la_anterior_ya_traia(estadisticas, tmp_path):
    """Éste es el error que el diseño existe para evitar, y el que nadie vería.

    La ventana de GitHub son catorce días, así que la foto de mañana trae de nuevo trece días
    que ya están guardados. Si se agregaran en vez de reemplazarse, cada día produciría trece
    duplicados y el archivo crecería en cuadrado, con el día en curso contado catorce veces.
    """
    estadisticas.guardar("t.csv", CAMPOS, [{"fecha": "2026-08-01", "vistas": 5}], ["fecha"])
    estadisticas.guardar(
        "t.csv",
        CAMPOS,
        [{"fecha": "2026-08-01", "vistas": 5}, {"fecha": "2026-08-02", "vistas": 9}],
        ["fecha"],
    )

    filas = leer(tmp_path / "t.csv")
    assert [f["fecha"] for f in filas] == ["2026-08-01", "2026-08-02"]


def test_el_dia_en_curso_se_corrige_hacia_arriba_y_no_se_suma(estadisticas, tmp_path):
    """GitHub cuenta el día en curso a medida que pasa, así que la foto de la tarde trae un
    número mayor que la de la mañana para la MISMA fecha.

    Reemplazar es lo correcto: sumarlas contaría dos veces las visitas de la mañana.
    """
    estadisticas.guardar("t.csv", CAMPOS, [{"fecha": "2026-08-01", "vistas": 3}], ["fecha"])
    estadisticas.guardar("t.csv", CAMPOS, [{"fecha": "2026-08-01", "vistas": 11}], ["fecha"])

    filas = leer(tmp_path / "t.csv")
    assert filas == [{"fecha": "2026-08-01", "vistas": "11"}]


def test_una_foto_nueva_no_borra_los_dias_que_ya_caducaron(estadisticas, tmp_path):
    """La razón entera de que esto exista.

    Un día que sale de la ventana de catorce días desaparece de la respuesta de GitHub para
    siempre. Si la foto nueva reescribiera el archivo con sólo lo que la API devuelve hoy, el
    historial se borraría solo, en silencio, y justo el archivo que se guarda para no perderlo.
    """
    estadisticas.guardar("t.csv", CAMPOS, [{"fecha": "2026-07-01", "vistas": 42}], ["fecha"])
    estadisticas.guardar("t.csv", CAMPOS, [{"fecha": "2026-08-20", "vistas": 7}], ["fecha"])

    filas = leer(tmp_path / "t.csv")
    assert [f["fecha"] for f in filas] == ["2026-07-01", "2026-08-20"]
    assert filas[0]["vistas"] == "42", "el día caducado perdió su valor"


def test_la_clave_compuesta_distingue_dos_referentes_de_la_misma_foto(estadisticas, tmp_path):
    """Referentes y rutas se guardan por foto Y por nombre.

    Con la fecha sola como clave, los cuatro referentes de una foto colapsarían en uno y el
    archivo guardaría el último que le tocara. Con el nombre solo, la foto de mañana pisaría
    la de hoy y no habría serie de tiempo, que es lo único que se busca.
    """
    campos = ["foto", "referente", "vistas"]
    estadisticas.guardar(
        "r.csv",
        campos,
        [
            {"foto": "2026-08-20", "referente": "google.com", "vistas": 2},
            {"foto": "2026-08-20", "referente": "github.com", "vistas": 77},
        ],
        ["foto", "referente"],
    )
    estadisticas.guardar(
        "r.csv",
        campos,
        [{"foto": "2026-08-21", "referente": "github.com", "vistas": 80}],
        ["foto", "referente"],
    )

    filas = leer(tmp_path / "r.csv")
    assert len(filas) == 3, f"se esperaban tres filas distintas y hay {filas}"
    assert {(f["foto"], f["referente"]) for f in filas} == {
        ("2026-08-20", "google.com"),
        ("2026-08-20", "github.com"),
        ("2026-08-21", "github.com"),
    }
