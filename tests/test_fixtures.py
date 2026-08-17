"""Las fixtures no deben contener datos personales reales.

Las respuestas de la Oficina Judicial Virtual traen RUT y nombres completos de personas
naturales que son parte en juicios. Que ese dato sea consultable en la plataforma no autoriza
a republicarlo en un repositorio público: allá vive detrás de una consulta puntual, y acá
quedaría indexado y permanente. Es un cambio de finalidad.

Si estos tests fallan, corre `uv run python tests/fixtures/anonimizar.py`.
"""

import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

_RUT = re.compile(r"\b(\d{7,8})-([\dkK])\b")
_IDENTIFICADOR_ABOGADO = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{4,}\d{7,8}\b")

#: Los RUT ficticios son dígitos repetidos: 11111111-1, 22222222-2, etc.
_FICTICIO = re.compile(r"^(\d)\1{6,7}$")


def _archivos() -> list[Path]:
    archivos = sorted(FIXTURES.glob("*.html"))
    # Sin esto, un glob que no encuentra nada hace pasar todos los tests de abajo.
    # Ya ocurrió una vez durante el desarrollo, con el cwd equivocado.
    assert archivos, f"No se encontró ninguna fixture en {FIXTURES}"
    return archivos


def test_hay_fixtures():
    assert len(_archivos()) >= 3


def test_sin_rut_reales():
    encontrados = {}
    for archivo in _archivos():
        for cuerpo, dv in _RUT.findall(archivo.read_text(encoding="utf-8")):
            if not _FICTICIO.match(cuerpo):
                encontrados.setdefault(archivo.name, set()).add(f"{cuerpo}-{dv}")
    assert not encontrados, (
        f"RUT reales en fixtures: {encontrados}. "
        "Corre: uv run python tests/fixtures/anonimizar.py"
    )


def test_sin_identificadores_de_abogado():
    """El campo `Institución` trae APELLIDO + RUT sin dígito verificador.

    Permite reconstruir la cartera completa de un abogado, así que se anonimiza igual.
    """
    encontrados = {}
    for archivo in _archivos():
        for ident in _IDENTIFICADOR_ABOGADO.findall(archivo.read_text(encoding="utf-8")):
            if ident != "ESTUDIO00000000":
                encontrados.setdefault(archivo.name, set()).add(ident)
    assert not encontrados, f"Identificadores de abogado sin anonimizar: {encontrados}"


def test_sin_nombres_reales_conocidos():
    """Guardia contra reintroducir las identidades que ya se anonimizaron una vez."""
    from tests.fixtures.anonimizar import PERSONAS

    encontrados = {}
    for archivo in _archivos():
        texto = archivo.read_text(encoding="utf-8")
        presentes = {real for real in PERSONAS if real in texto}
        if presentes:
            encontrados[archivo.name] = presentes
    assert not encontrados, f"Nombres reales en fixtures: {encontrados}"
