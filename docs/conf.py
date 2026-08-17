"""Configuración de Sphinx."""

from importlib.metadata import version as _version

project = "mcp-pjud"
copyright = "2026, Lucas Pulgar Escobar"
author = "Lucas Pulgar Escobar"

# La versión se lee de los metadatos del paquete y no se escribe acá. Duplicarla significa
# que al subir la versión en pyproject alguien tiene que acordarse de este archivo, y no
# se acuerda.
release = _version("mcp-pjud")
version = ".".join(release.split(".")[:2])

language = "es"

extensions = [
    "myst_parser",
    # Genera una versión Markdown de cada página, más llms.txt y llms-full.txt.
    # Es lo que permite que un agente lea la documentación sin atravesar el HTML.
    "sphinx_llm.txt",
    # Botón de copiar en cada bloque de código, y pestañas para mostrar la misma llamada
    # desde clientes distintos. Es lo que hace legible una referencia de API.
    "sphinx_copybutton",
    "sphinx_design",
]

# Sin autodoc, napoleon ni viewcode: ninguna página usa directivas de API. Estaban
# cargadas sin hacer nada.

# Sólo lo que se usa. `colon_fence` para los avisos, `deflist` para las listas de campos.
myst_enable_extensions = ["colon_fence", "deflist", "attrs_inline"]
myst_heading_anchors = 3

templates_path = ["_templates"]
# `_generado` se incluye dentro de otras páginas con `{include}`, no es una página propia.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "_generado"]

html_theme = "furo"
html_title = "mcp-pjud"
html_static_path = []

# La extensión genera llms.txt, llms-full.txt y un .md por página. Se le deja a ella en
# vez de mantener un llms.txt a mano: uno escrito a mano se desincroniza del índice a la
# primera página nueva. Lo que sí se cuida a mano es la descripción, porque es la primera
# línea que lee un agente y ahí tiene que estar la distinción entre las dos fechas.
llms_txt_enabled = True
llms_txt_full_build = True
llms_txt_description = (
    "Servidor MCP de solo lectura para la consulta pública de causas del Poder Judicial "
    "de Chile. fecha_diligencia es la que corre los plazos procesales; fecha_registro no."
)

html_theme_options = {
    "source_repository": "https://github.com/notluquis/mcp-pjud-cl/",
    "source_branch": "main",
    "source_directory": "docs/",
}

# Aviso permanente en cada página: el proyecto no es institucional y el software no
# reemplaza la revisión del expediente.
rst_prolog = """
.. warning::
   Proyecto independiente, sin relación con el Poder Judicial de Chile ni con la
   Corporación Administrativa del Poder Judicial. Solo lectura de información pública.
   No reemplaza la revisión del expediente ni el criterio profesional.
"""


# -- esquema de las herramientas, generado desde el servidor ---------------------
#
# La tabla de parámetros escrita a mano puede quedar vieja; el esquema que el servidor
# entrega por el protocolo, no. Se genera al construir la documentación, así que la
# referencia publicada es literalmente lo que un cliente MCP recibe.


def _generar_esquemas(app):
    # Los imports viven acá y no arriba porque hay que poner `src` en la ruta antes de
    # importar el paquete, y hacerlo en el ámbito del módulo obliga a un import fuera de
    # lugar que el linter marca con razón.
    import asyncio
    import json
    import os
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))
    # El servidor exige un contacto para operar. Acá no consulta nada: sólo se le pide que
    # declare sus herramientas.
    os.environ.setdefault("MCP_PJUD_CONTACTO", "documentacion@ejemplo.cl")

    from mcp_pjud.server import mcp

    destino = pathlib.Path(__file__).parent / "_generado"
    destino.mkdir(exist_ok=True)

    for h in asyncio.run(mcp.list_tools()):
        esquema = {
            "name": h.name,
            "inputSchema": h.input_schema,
            "outputSchema": h.output_schema,
            "annotations": h.annotations.model_dump(exclude_none=True) if h.annotations else {},
        }
        (destino / f"{h.name}.md").write_text(
            ":::{dropdown} Esquema que entrega el protocolo\n"
            ":color: secondary\n:icon: code\n\n"
            "Generado desde el servidor al construir esta página, así que no puede quedar\n"
            "desactualizado respecto del código.\n\n"
            "```json\n" + json.dumps(esquema, ensure_ascii=False, indent=2) + "\n```\n:::\n",
            encoding="utf-8",
        )


def setup(app):
    app.connect("builder-inited", _generar_esquemas)
