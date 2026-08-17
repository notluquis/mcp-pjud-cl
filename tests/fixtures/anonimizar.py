"""Anonimiza las fixtures antes de versionarlas.

Las respuestas de la Oficina Judicial Virtual traen RUT y nombres completos de personas
naturales que son parte en juicios de cobranza. Que ese dato sea públicamente consultable en
la plataforma no autoriza a republicarlo en un repositorio: en la OJV vive detrás de una
consulta puntual, y acá quedaría indexado y permanente. Eso es un cambio de finalidad, que es
justamente lo que la Ley 21.719 regula.

Los tests no necesitan ninguno de esos datos: verifican folios, fechas, cuadernos y trámites.
Este script reemplaza identidades por valores ficticios y deja la estructura HTML intacta.

Se ejecuta una vez, sobre las fixtures recién capturadas:

    uv run python tests/fixtures/anonimizar.py
"""

import pathlib
import re

# Personas naturales -> nombres ficticios. Se conservan largo y forma para no alterar
# el layout ni el comportamiento del parser.
PERSONAS = {
    "JOSÉ MANUEL MARTÍNEZ MARTÍNEZ": "PERSONA DEMANDADA UNO",
    "DR JOSE MANUEL MARTÍNEZ Y COMPAÑIA": "EMPRESA DEMANDADA LIMITADA",
    "MARTÍNEZ MARTINEZ": "DEMANDADA UNO",
    "DANIELA ANDREA RUBILAR URRUTIA": "ABOGADA PATROCINANTE UNO",
    "CAROLINA NATALIA RAMÍREZ MORALES": "ABOGADA PATROCINANTE DOS",
    "CAROLINA ANDREA CALLUIL VILLANUEVA": "ABOGADA PATROCINANTE TRES",
    "CATALINA ALEJANDRA PIZARRO ROBINSON": "ABOGADA PATROCINANTE CUATRO",
    "PATRICIO ANDRÉS PACHECO COFRÉ": "ABOGADO PATROCINANTE CINCO",
}

# RUT reales -> ficticios con dígito verificador válido.
RUTS = {
    "11896644-9": "11111111-1",
    "12306213-2": "22222222-2",
    "15550751-9": "33333333-3",
    "16457427-K": "44444444-4",
    "17260931-7": "55555555-5",
    "17699952-7": "66666666-6",
    "76406172-1": "77777777-7",
    "97004000-5": "99999999-9",  # persona jurídica, se anonimiza igual por consistencia
}

# Identificadores de abogado con formato APELLIDO + RUT sin dígito verificador.
IDENTIFICADORES = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{4,}\d{7,8}\b")


def anonimizar(texto: str) -> str:
    for real, ficticio in PERSONAS.items():
        texto = texto.replace(real, ficticio)
    for real, ficticio in RUTS.items():
        texto = texto.replace(real, ficticio)
        texto = texto.replace(real.replace("-", ""), ficticio.replace("-", ""))
    return IDENTIFICADORES.sub("ESTUDIO00000000", texto)


def main() -> None:
    for archivo in sorted(pathlib.Path(__file__).parent.glob("*.html")):
        original = archivo.read_text(encoding="utf-8")
        limpio = anonimizar(original)
        if limpio != original:
            archivo.write_text(limpio, encoding="utf-8")
            print(f"  anonimizado {archivo.name}")
        else:
            print(f"  sin cambios  {archivo.name}")


if __name__ == "__main__":
    main()
