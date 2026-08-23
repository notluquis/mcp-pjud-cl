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

from .conftest import raiz_del_repo

RAIZ = raiz_del_repo()


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


# -- la paginación ------------------------------------------------------------------
#
# Sin estos, quitar `paginar=True`, borrar `--paginate` o romper el aplanado dejaría la suite
# entera en verde: los tests de arriba sólo llaman a `guardar`. Es un parámetro opcional cuyo
# valor por defecto apaga la rama nueva, o sea código sin test por construcción.


@pytest.fixture
def gh_falso(estadisticas, monkeypatch):
    """Reemplaza la llamada a `gh` y guarda con qué argumentos la invocaron."""
    llamadas: list[list[str]] = []

    def correr(orden, **kw):
        llamadas.append(orden)
        salida = (
            '[[{"tag_name": "v0.1.0"}], [{"tag_name": "v0.2.0"}]]'
            if "--slurp" in orden
            else '[{"tag_name": "v0.1.0"}]'
        )
        return type("R", (), {"returncode": 0, "stdout": salida, "stderr": ""})()

    monkeypatch.setattr(estadisticas.subprocess, "run", correr)
    return llamadas


def test_la_consulta_de_versiones_pide_todas_las_paginas(estadisticas, gh_falso):
    """`gh api` trae 30 por página y NO avisa que hay más.

    Pasadas 30 versiones dejarían de contarse las descargas de las viejas, en silencio, que es
    la misma truncación callada que el resto del proyecto levanta en vez de esconder.
    """
    estadisticas.api("releases", paginar=True)
    assert "--paginate" in gh_falso[0], f"la consulta no pagina: {gh_falso[0]}"


def test_las_paginas_llegan_aplanadas_y_no_como_lista_de_listas(estadisticas, gh_falso):
    """`--slurp` devuelve un arreglo por página, y no se puede combinar con `--jq` para
    aplanarlo: `gh` lo rechaza con un error. Se aplana en Python, y si eso se rompe cada
    versión se leería como una lista y `v["assets"]` reventaría.
    """
    versiones = estadisticas.api("releases", paginar=True)
    assert versiones == [{"tag_name": "v0.1.0"}, {"tag_name": "v0.2.0"}]


def test_una_consulta_sin_paginar_no_pide_paginas_de_mas(estadisticas, gh_falso):
    """Las de tráfico devuelven un objeto, no una lista: paginarlas no aporta y `--slurp` las
    envolvería en un arreglo que el resto del código no espera."""
    estadisticas.api("traffic/views")
    assert "--paginate" not in gh_falso[0]
    assert "--slurp" not in gh_falso[0]


def test_un_rechazo_de_permisos_dice_que_falta_el_token(estadisticas, monkeypatch):
    """El 403 de la API de tráfico es indistinguible de un día sin visitas si se traga.

    Está medido: el token del workflow recibe `Resource not accessible by integration`, porque
    la API exige acceso de escritura y `permissions:` no tiene clave que lo conceda.
    """

    def correr(orden, **kw):
        return type(
            "R",
            (),
            {"returncode": 1, "stdout": "", "stderr": "Resource not accessible by integration"},
        )()

    monkeypatch.setattr(estadisticas.subprocess, "run", correr)
    with pytest.raises(SystemExit, match="TRAFICO_TOKEN"):
        estadisticas.api("traffic/views")


def test_la_foto_completa_pide_las_versiones_paginadas(estadisticas, monkeypatch, tmp_path):
    """Los de arriba prueban `api()`, no quién la llama.

    Sin éste, borrar `paginar=True` del sitio de llamada deja toda la suite en verde: es el
    mismo agujero que el parámetro opcional cuyo valor por defecto apaga la rama nueva. Acá se
    camina la foto entera y se exige que la consulta de versiones, y sólo ésa, pagine.
    """
    RESPUESTAS = {
        "traffic/views": '{"views": [{"timestamp": "2026-08-01T00:00:00Z", "count": 3, '
        '"uniques": 1}]}',
        "traffic/clones": '{"clones": []}',
        "traffic/popular/referrers": '[{"referrer": "google.com", "count": 2, "uniques": 2}]',
        "traffic/popular/paths": '[{"path": "/x", "count": 1, "uniques": 1}]',
        "releases": '[[{"tag_name": "v0.1.0", "assets": [{"name": "a.whl", '
        '"download_count": 0}]}]]',
        "": '{"stargazers_count": 1, "forks_count": 0, "subscribers_count": 0, '
        '"open_issues_count": 3}',
    }
    ordenes: list[list[str]] = []

    def correr(orden, **kw):
        ordenes.append(orden)
        ruta = orden[2].removeprefix(f"repos/{estadisticas.REPO}").lstrip("/")
        return type("R", (), {"returncode": 0, "stdout": RESPUESTAS[ruta], "stderr": ""})()

    monkeypatch.setattr(estadisticas.subprocess, "run", correr)
    monkeypatch.setattr(estadisticas, "DESTINO", tmp_path)
    estadisticas.main()

    paginadas = {o[2].split("/")[-1] for o in ordenes if "--paginate" in o}
    assert paginadas == {"releases"}, (
        f"la consulta de versiones tiene que paginar y ninguna otra. Paginan: {paginadas}"
    )
    assert (tmp_path / "README.md").exists(), "la foto no dejó el resumen que se lee en la rama"
