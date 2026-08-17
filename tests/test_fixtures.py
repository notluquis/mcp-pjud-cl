"""Las fixtures no deben contener datos personales reales.

Las respuestas de la Oficina Judicial Virtual traen RUT y nombres completos de personas
naturales que son parte en juicios. Que ese dato sea consultable en la plataforma no autoriza
a republicarlo en un repositorio público: allá vive detrás de una consulta puntual, y acá
quedaría indexado y permanente. Es un cambio de finalidad.

Si estos tests fallan, corre `uv run python tests/fixtures/anonimizar.py`.
"""

import hashlib
import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

_RUT = re.compile(r"\b(\d{7,8})-([\dkK])\b")
_IDENTIFICADOR_ABOGADO = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{4,}\d{7,8}\b")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")

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


#: sha256 de las identidades que ya se anonimizaron una vez, en mayúsculas y sin espacios
#: sobrantes. Se guardan como hash y no en claro: publicar la lista de nombres reales
#: desharía la anonimización que este mismo test protege.
_NOMBRES_RETIRADOS = {
    "57c6ab2cde0f0577a101d61e301a26c6c430028fd6b77050625b20c946ff8e8d",
    "697e19a30c414722d14d87c43e3fadfdf69785f57e8921485286415225a5c9c8",
    "789071cded7db7fcee5a3eb38342bed8087ce3077ebebde9b6ac6d5aa6258e14",
    "89b87997a8eb260a6692b61440539c5c64950f6770d76df49668d9556c542272",
    "8c89342be628f7cb8143f52c0230a85f6cefb705717541fa31a8fc14fc4fc270",
    "a35e09efbb7d06ac500b4a7efbca11e4903b14610e8519f5d9f923b076099090",
    "d8e1ed7044e561e2224e8288c92d3d5113f4fb0ae1e21c9978379a38acce4e75",
}


def _huella(texto: str) -> str:
    return hashlib.sha256(" ".join(texto.split()).upper().encode()).hexdigest()


def test_sin_nombres_reales_conocidos():
    """Guardia contra reintroducir identidades que ya se anonimizaron.

    Compara hashes de los nombres que aparecen en las fixtures contra la lista de los que se
    retiraron. No necesita conocer los nombres reales para funcionar.
    """
    encontrados = {}
    for archivo in _archivos():
        texto = archivo.read_text(encoding="utf-8")
        for candidato in re.findall(r">\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{10,60})\s*<", texto):
            if _huella(candidato) in _NOMBRES_RETIRADOS:
                encontrados.setdefault(archivo.name, set()).add("(identidad retirada)")
    assert not encontrados, (
        f"Se reintrodujo una identidad que ya se había anonimizado: {encontrados}"
    )


def test_los_nombres_de_las_fixtures_son_los_ficticios():
    """Refuerzo del anterior: los nombres presentes deben ser los ficticios conocidos.

    El test de hashes sólo detecta identidades ya vistas. Éste detecta cualquier nombre nuevo
    que se cuele, incluido uno que nunca haya pasado por el anonimizador.
    """
    permitidos = {"BANCO DE CHILE"}
    inesperados = {}
    for archivo in _archivos():
        texto = archivo.read_text(encoding="utf-8")
        for candidato in re.findall(r">\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{14,60})\s*<", texto):
            nombre = " ".join(candidato.split())
            if len(nombre.split()) < 3 or nombre in permitidos:
                continue
            if not nombre.startswith(("PERSONA ", "ABOGAD", "EMPRESA ", "DEMANDAD")):
                inesperados.setdefault(archivo.name, set()).add(nombre)
    assert not inesperados, (
        f"Nombres que no son ficticios en las fixtures: {inesperados}. "
        "Corre: uv run python tests/fixtures/anonimizar.py"
    )


def test_sin_jwt_de_la_plataforma():
    """Las respuestas traen JWT como referencia opaca de causa, cuaderno o documento.

    Caducan a los 30 minutos, así que no sirven de credencial, pero su carga va cifrada y
    probablemente codifica identificadores de la misma causa cuyos nombres y RUT ya se
    anonimizaron. Además los detectores de secretos los marcan en cada revisión, lo que
    entrena a ignorar alertas.
    """
    encontrados = {}
    for archivo in _archivos():
        hallados = _JWT.findall(archivo.read_text(encoding="utf-8"))
        if hallados:
            encontrados[archivo.name] = len(hallados)
    assert not encontrados, (
        f"JWT de la plataforma en fixtures: {encontrados}. "
        "Corre: uv run python tests/fixtures/anonimizar.py"
    )
