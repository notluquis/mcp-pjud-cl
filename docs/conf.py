"""Configuración de Sphinx."""

project = "mcp-pjud"
copyright = "2026, Lucas Pulgar Escobar"
author = "Lucas Pulgar Escobar"
release = "0.1.0"
version = "0.1"

language = "es"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

# Sólo lo que se usa. `colon_fence` para los avisos, `deflist` para las listas de campos.
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_title = "mcp-pjud"
html_static_path = []

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
