"""La instantánea de lo que este servidor promete por el protocolo.

Los demás tests comprueban REGLAS: que la directiva quepa, que una descripción nombre las
competencias que exigen `tribunal`, que ningún esquema anunciado lleve prosa. Cada una dice
por qué su cosa tiene que ser así, y ninguna nota un cambio que no viole ninguna: renombrar un
campo de salida, perder una anotación, reordenar el catálogo, borrar media descripción.

Eso es justo lo que los cuatro cambios anteriores estuvieron moviendo, y es lo que ve el modelo
antes de responderle a un abogado. La instantánea no reemplaza a las reglas: las reglas dicen
POR QUÉ, ésta dice QUÉ, y un cambio no querido se cae acá aunque no rompa ninguna regla.

Es lo mismo que hace el servidor MCP de GitHub con sus `__toolsnaps__`.

Va como UNA lista ordenada y no como un diccionario por nombre a propósito: el orden de
`tools/list` es parte del contrato, y una instantánea indexada por nombre lo pierde en silencio.

`instrucciones` sale de `DIRECTIVA` y no de un saludo: está medido por stdio, con el servidor en
otro proceso, que lo que viaja en `instructions` son sus mismos 1.843 bytes.
"""

import json
import os

from mcp_pjud.server import DIRECTIVA

from .conftest import raiz_del_repo
from .test_documentacion import _catalogo

RAIZ = raiz_del_repo()
CONTRATO = RAIZ / "tests" / "contrato.json"

#: Cómo se aprueba un cambio de contrato. Va en el mensaje del fallo porque una instantánea que
#: no dice cómo regenerarse se regenera a ciegas, y ahí deja de medir.
COMO_APROBAR = "APROBAR_CONTRATO=1 uv run pytest tests/test_contrato.py"


def _instantanea() -> dict:
    return {"instrucciones": DIRECTIVA, "herramientas": list(_catalogo())}


def test_el_contrato_es_el_que_esta_aprobado():
    """Un cambio de lo que viaja falla hasta que alguien lo mire y lo apruebe."""
    ahora = _instantanea()
    if os.environ.get("APROBAR_CONTRATO"):
        CONTRATO.write_text(
            json.dumps(ahora, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return

    assert CONTRATO.exists(), f"falta la instantánea del contrato. Para crearla: {COMO_APROBAR}"
    aprobado = json.loads(CONTRATO.read_text(encoding="utf-8"))

    nombres_ahora = [h["name"] for h in ahora["herramientas"]]
    nombres_antes = [h["name"] for h in aprobado["herramientas"]]
    assert nombres_ahora == nombres_antes, (
        f"cambió qué herramientas se anuncian, o en qué orden: {nombres_antes} -> "
        f"{nombres_ahora}. Si es a propósito: {COMO_APROBAR}"
    )
    assert ahora["instrucciones"] == aprobado["instrucciones"], (
        f"cambió la directiva que el servidor entrega al conectarse. Si es a propósito: "
        f"{COMO_APROBAR}"
    )
    # De a una y por nombre: el diff de catorce herramientas juntas no se lee.
    for herramienta, antes in zip(ahora["herramientas"], aprobado["herramientas"], strict=True):
        assert herramienta == antes, (
            f"cambió lo que `{herramienta['name']}` promete por el protocolo. Si es a "
            f"propósito: {COMO_APROBAR}"
        )
