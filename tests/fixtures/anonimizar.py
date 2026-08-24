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

# Las respuestas traen JWT que la plataforma usa como referencia opaca de causa, cuaderno o
# documento. El del listado declara media hora, así que no sirve de credencial, pero su carga
# `data` va FIRMADA y no cifrada: se lee sin más, y probablemente codifica identificadores de
# la misma causa cuyos nombres y RUT ya se anonimizaron. Dejarlos sería incoherente, y además
# los detectores de secretos los marcan en cada revisión, lo que entrena a ignorar alertas.
#
# Los tests no necesitan su contenido: sólo comprueban que la referencia exista.
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")

# Consultas SQL que la plataforma imprime dentro de una celda en vez de renderizar el documento.
# Medido en el detalle de Cortes de Apelaciones: la columna `Doc.` traía el SELECT completo, con
# el esquema, la tabla y los parámetros con nombre.
#
# Se borran siempre y sin mapeo. No es un dato de este proyecto ni de las partes: son internos
# del sistema de un tercero, y republicarlos en un repositorio público los deja indexados y
# permanentes. La misma razón por la que los hallazgos de seguridad de la plataforma no se
# publican acá: si hay que decirlo, se dice a la CAPJ por divulgación responsable.
#
# Los tests no necesitan el contenido de esa celda: comprueban que la columna exista.
SQL = re.compile(r"SELECT\s+[A-Z_0-9,\s]+FROM\s+\w+\.\w+.*?(?=<|$)", re.I | re.S)
SQL_FICTICIO = "(consulta interna suprimida)"


def anonimizar(texto: str, personas: dict[str, str], ruts: dict[str, str]) -> str:
    for real, ficticio in personas.items():
        texto = texto.replace(real, ficticio)
    for real, ficticio in ruts.items():
        texto = texto.replace(real, ficticio)
        texto = texto.replace(real.replace("-", ""), ficticio.replace("-", ""))
    texto = IDENTIFICADORES.sub(IDENTIFICADOR_FICTICIO, texto)
    texto = SQL.sub(SQL_FICTICIO, texto)

    # Cada JWT distinto recibe una referencia ficticia distinta, para que las fixtures sigan
    # distinguiendo un cuaderno de otro.
    vistos: dict[str, str] = {}

    def _referencia(m: re.Match[str]) -> str:
        return vistos.setdefault(m.group(0), f"referencia-ficticia-{len(vistos) + 1:03d}")

    return JWT.sub(_referencia, texto)


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
