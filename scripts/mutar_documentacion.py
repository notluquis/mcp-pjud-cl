"""Rompe cada cifra de la documentación y exige que la suite se ponga en rojo.

`mutmut` muta el CÓDIGO. Nada mutaba la documentación, que es donde este proyecto guarda lo
medido: los plazos, la latencia, cuántas coincidencias oculta el buscador, cuánto pesa un
documento. Un guardia sobre una cifra que no puede fallar imprime exactamente lo mismo que
uno que sí, y en una sesión aparecieron seis así.

Lo que hace: por cada cifra de `docs/*.md` y del `README`, la cambia por otra plausible,
corre `tests/test_documentacion.py` y comprueba que algo se caiga. Las que no rompen nada
salen listadas.

No corre en la suite: son decenas de corridas de pytest. Vive en `mutacion.yml`, junto a
`mutmut`, por la misma razón por la que ése tampoco corre en el ciclo de desarrollo.

    uv run python scripts/mutar_documentacion.py [--rapido]
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]

#: Cifras que NO se puede exigir que un guardia cubra, con la razón. Son mediciones que
#: ocurren en una sola página y que nada del repositorio puede derivar: no hay copia de la
#: cual divergir ni fuente contra la cual compararlas.
#:
#: Esta lista es también el inventario honesto de lo que la documentación afirma sobre su
#: palabra. Que sea corta importa; que crezca sin razón escrita, más.
SIN_FUENTE_DERIVABLE = {
    "20.886": "número de ley",
    "21.719": "número de ley",
    "17.336": "número de ley",
    "20.000": "número de ley",
    "21.394": "número de ley",
    "1.223.925": "medido una vez contra el buscador, sin fuente en el repositorio",
    "269.256": "ídem, sobre el buscador laboral",
    "269.264": "ídem",
    "106.068": "ídem",
    "232.021": "ídem",
    "829.079": "ídem",
    "20.924": "ídem",
    "300.005": "ídem",
    "1.159": "cuántas líneas tenía la hoja de ruta antes de partirla; histórico",
    "6.677": "ídem, en caracteres",
    "97.848": "tamaño de una respuesta real, medido una vez",
    "11.549": "ídem",
    "11.552": "ídem",
    "38.477": "ídem",
    "19.799": "ídem",
    "2.977": "ídem",
    "10.000": "precio de un producto de terceros",
    "10.400": "ídem",
    "2.000": "ídem",
    "31.200": "ídem",
    "6.500": "ídem",
    "1,6": "latencia medida una vez",
    "115,6": "ídem",
    "4,3": "ídem",
}

#: Cuántas cifras tiene que encontrar el PATRÓN, antes de descontar las que no se pueden
#: derivar. Sin este piso, un cambio que deje de encontrar nada informaría "todo cubierto"
#: con el mismo texto que un repositorio sano: es la forma exacta de guardia inerte que este
#: arnés existe para cazar, y sería vergonzoso cometerla acá.
#:
#: Va sobre el total y no sobre lo que queda después de filtrar, porque lo que protege es el
#: instrumento. La lista de exclusiones es política y puede crecer con razón escrita; que el
#: patrón deje de ver la documentación no tiene ninguna.
MINIMO_QUE_DEBE_VER_EL_PATRON = 45

PATRON = re.compile(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d+,\d+\b")


def paginas() -> list[pathlib.Path]:
    return [
        *(p for p in sorted((RAIZ / "docs").glob("*.md")) if not p.name.startswith("_")),
        RAIZ / "README.md",
    ]


def cifras() -> tuple[list[tuple[pathlib.Path, str]], int]:
    """Las que hay que mutar, y cuántas vio el patrón en total."""
    todas = [
        (p, n)
        for p in paginas()
        for n in sorted(set(PATRON.findall(p.read_text(encoding="utf-8"))))
    ]
    fuera = set(SIN_FUENTE_DERIVABLE)
    return [par for par in todas if par[1] not in fuera], len(todas)


def otra(n: str) -> str:
    """Una cifra distinta y del mismo tamaño, para que el cambio siga siendo plausible."""
    return ("9" if n[0] != "9" else "8") + n[1:]


def suite_en_rojo() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_documentacion.py", "-x", "-q", "--no-header"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    return r.returncode != 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true", help="sólo las diez primeras")
    args = ap.parse_args()

    candidatas, vistas = cifras()
    # S101: no es una comprobación de tipos que se pueda apagar con -O, es lo único que
    # impide que este arnés informe 'todo cubierto' sin haber mirado nada.
    assert vistas >= MINIMO_QUE_DEBE_VER_EL_PATRON, (  # noqa: S101
        f"el patrón vio {vistas} cifras y tiene que ver al menos "
        f"{MINIMO_QUE_DEBE_VER_EL_PATRON}. Antes de bajar el mínimo hay que mirar el patrón: "
        "un arnés que no encuentra nada informa 'todo cubierto' con el mismo texto que uno sano."
    )
    if args.rapido:
        candidatas = candidatas[:10]

    print(
        f"El patrón ve {vistas} cifras; {vistas - len(candidatas)} están declaradas sin "
        f"fuente derivable. Mutando las {len(candidatas)} restantes.\n",
        flush=True,
    )
    sin_guardia = []
    for archivo, n in candidatas:
        original = archivo.read_text(encoding="utf-8")
        mutado = original.replace(n, otra(n))
        # Sin esto el arnés mide lo mismo que no hacer nada, que es como se cuela un guardia
        # inerte: la ruptura tiene que haberse aplicado de verdad.
        # S101: ídem. Sin esto, una mutación que no se aplica se mide como cifra guardada.
        assert mutado != original, (  # noqa: S101
            f"la mutación de {n} en {archivo.name} no cambió el archivo"
        )
        archivo.write_text(mutado, encoding="utf-8")
        try:
            roja = suite_en_rojo()
        finally:
            archivo.write_text(original, encoding="utf-8")
        if not roja:
            sin_guardia.append((archivo.name, n))
            print(f"  SIN GUARDIA  {archivo.name}: {n}", flush=True)

    print()
    if sin_guardia:
        print(f"{len(sin_guardia)} de {len(candidatas)} cifras no rompen ningún test.")
        print("O se les escribe un guardia, o entran a SIN_FUENTE_DERIVABLE con su razón.")
        return 1
    print(f"Las {len(candidatas)} cifras rompen algún test al cambiarlas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
