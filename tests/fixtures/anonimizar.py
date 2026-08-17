"""Anonimiza las fixtures antes de versionarlas.

Las respuestas de la Oficina Judicial Virtual traen RUT y nombres completos de personas
naturales que son parte en juicios de cobranza. Que ese dato sea públicamente consultable en
la plataforma no autoriza a republicarlo en un repositorio: en la OJV vive detrás de una
consulta puntual, y acá quedaría indexado y permanente. Eso es un cambio de finalidad, que es
justamente lo que la Ley 21.719 regula.

Los tests no necesitan ninguno de esos datos: verifican folios, fechas, cuadernos y trámites.

## El mapeo NO se versiona

Publicar la tabla `real -> ficticio` desharía la anonimización: cualquiera podría revertirla.
Por eso el mapeo se lee de `mapeo.local.json`, que está en .gitignore y nunca se sube.

Formato:

    {
      "personas": {"NOMBRE REAL": "PERSONA DEMANDADA UNO"},
      "ruts":     {"<rut real>": "11111111-1"}
    }

Ojo con el ejemplo: no pongas un RUT real ni siquiera acá. Este archivo se versiona.

El guardia que impide reintroducir datos reales vive en `tests/test_fixtures.py` y usa
hashes, no el mapeo: verifica que no queden RUT con estructura real ni identificadores de
abogado, sin necesitar saber cuáles eran.

Uso, sobre fixtures recién capturadas:

    uv run python tests/fixtures/anonimizar.py
"""

import json
import pathlib
import re
import sys

AQUI = pathlib.Path(__file__).parent
MAPEO = AQUI / "mapeo.local.json"

# Identificadores de abogado con formato APELLIDO + RUT sin dígito verificador. Permiten
# reconstruir la cartera completa de un abogado, así que se borran siempre, sin mapeo.
IDENTIFICADORES = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{4,}\d{7,8}\b")
IDENTIFICADOR_FICTICIO = "ESTUDIO00000000"


def anonimizar(texto: str, personas: dict[str, str], ruts: dict[str, str]) -> str:
    for real, ficticio in personas.items():
        texto = texto.replace(real, ficticio)
    for real, ficticio in ruts.items():
        texto = texto.replace(real, ficticio)
        texto = texto.replace(real.replace("-", ""), ficticio.replace("-", ""))
    return IDENTIFICADORES.sub(IDENTIFICADOR_FICTICIO, texto)


def main() -> int:
    if not MAPEO.exists():
        print(
            f"Falta {MAPEO.name}. Créalo con las identidades a reemplazar; no se versiona.\n"
            'Formato: {"personas": {"NOMBRE REAL": "PERSONA UNO"}, '
            '"ruts": {"<rut real>": "11111111-1"}}',
            file=sys.stderr,
        )
        return 1

    datos = json.loads(MAPEO.read_text(encoding="utf-8"))
    personas = datos.get("personas", {})
    ruts = datos.get("ruts", {})

    for archivo in sorted(AQUI.glob("*.html")):
        original = archivo.read_text(encoding="utf-8")
        limpio = anonimizar(original, personas, ruts)
        estado = "anonimizado" if limpio != original else "sin cambios "
        if limpio != original:
            archivo.write_text(limpio, encoding="utf-8")
        print(f"  {estado} {archivo.name}")

    print("\nAhora corre: uv run pytest tests/test_fixtures.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
