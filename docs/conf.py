"""Configuración de Sphinx."""

project = "mcp-pjud"
copyright = "2026, Lucas Pulgar Escobar"
author = "Lucas Pulgar Escobar"
release = "0.1.0"
version = "0.1"

language = "es"

extensions = [
    "myst_parser",
    # Genera una versión Markdown de cada página, más llms.txt y llms-full.txt.
    # Es lo que permite que un agente lea la documentación sin atravesar el HTML.
    "sphinx_llm.txt",
]

# Sin autodoc, napoleon ni viewcode: ninguna página usa directivas de API. Estaban
# cargadas sin hacer nada.

# Sólo lo que se usa. `colon_fence` para los avisos, `deflist` para las listas de campos.
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

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
