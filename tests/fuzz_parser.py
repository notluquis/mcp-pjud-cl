"""Harness de fuzzing para el parser de Historia.

Complementa las pruebas basadas en propiedades de `test_propiedades.py`. La diferencia no
está en el oráculo, que es el mismo, sino en cómo se llega a la entrada que rompe:
Hypothesis genera desde estrategias tipadas y reduce el caso al mínimo; Atheris muta bytes
guiado por cobertura y alcanza caminos que una estrategia tipada quizá nunca produzca.

No corre en CI. Se ejecuta a mano cuando se toca el parser:

    uv run --with atheris python tests/fuzz_parser.py -atheris_runs=100000

El oráculo es el mismo que la invariante central del proyecto: toda fecha que el parser
devuelve tiene que venir en la entrada. Una fecha de diligencia inventada se computa como
plazo, y eso es peor que no devolver ninguna.
"""

import re
import sys
from datetime import date

import atheris

with atheris.instrument_imports():
    from mcp_pjud.parser import EstructuraInesperada, parse_historia

_FECHA = re.compile(r"\d{2}/\d{2}/\d{4}")


def _fechas_de(texto: str) -> set[date]:
    """Fechas presentes en el texto, como objetos `date`.

    Se comparan objetos y no cadenas a propósito. Reconstruir la fecha en formato chileno
    para compararla contra el texto original da falsos positivos en dos casos que Atheris
    genera: el año 1 se reconstruye como `01/01/1` y no `01/01/0001`, y `\d` de Python
    matchea dígitos Unicode, que `int()` acepta pero cuya reconstrucción sale en ASCII.
    """
    encontradas = set()
    for hallazgo in _FECHA.findall(texto):
        d, m, a = hallazgo.split("/")
        try:
            encontradas.add(date(int(a), int(m), int(d)))
        except ValueError:
            # 31/02 y similares: el parser tampoco las acepta.
            continue
    return encontradas

PLANTILLA = """<div id="historiaCiv"><table>
  <thead><tr><th>Folio</th><th>Doc.</th><th>Anexo</th><th>Etapa</th>
  <th>Tr&aacute;mite</th><th>Desc. Tr&aacute;mite</th><th>Fec. Tr&aacute;mite</th>
  <th>Foja</th><th>Georref.</th></tr></thead><tbody>
  <tr><td>1</td><td></td><td></td><td>Exhorto</td><td>Actuaci&oacute;n Receptor</td>
  <td>{desc}</td><td>{fec}</td><td>0</td><td></td></tr>
  </tbody></table></div>"""


def prueba(datos: bytes) -> None:
    proveedor = atheris.FuzzedDataProvider(datos)
    desc = proveedor.ConsumeUnicodeNoSurrogates(120)
    fec = proveedor.ConsumeUnicodeNoSurrogates(60)

    # Las celdas no pueden llevar marcado propio: romperían el HTML de la plantilla en vez
    # de ejercitar el parser, que es lo que interesa.
    desc = desc.replace("<", "").replace(">", "").replace("&", "")
    fec = fec.replace("<", "").replace(">", "").replace("&", "")

    entrada = PLANTILLA.format(desc=desc, fec=fec)

    try:
        actuaciones = parse_historia(entrada)
    except EstructuraInesperada:
        # Falla declarada del parser ante estructura desconocida. Es el comportamiento
        # correcto y no un hallazgo.
        return

    presentes = _fechas_de(desc) | _fechas_de(fec)
    for a in actuaciones:
        for campo, valor in (("diligencia", a.fecha_diligencia), ("registro", a.fecha_registro)):
            if valor is None:
                continue
            assert valor in presentes, (
                f"El parser inventó una fecha de {campo}: {valor.isoformat()} no aparece en "
                f"la entrada. desc={desc!r} fec={fec!r}"
            )


def main() -> None:
    atheris.Setup(sys.argv, prueba)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
