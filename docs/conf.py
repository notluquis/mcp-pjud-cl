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
    #
    # Se deja porque no cuesta nada y no duplica ningún dato: sale de las mismas páginas. NO
    # se deja porque conste que alguien lo consuma. En mayo de 2026 Ahrefs midió 137.210
    # dominios y el 97% de los `llms.txt` publicados no recibió ninguna petición: es una
    # capacidad y no una audiencia, y no sirve para justificar decisiones de estructura.
    "sphinx_llm.txt",
    # Botón de copiar en cada bloque de código, y pestañas para mostrar la misma llamada
    # desde clientes distintos. Es lo que hace legible una referencia de API.
    "sphinx_copybutton",
    "sphinx_design",
    # Diagramas. Se elige mermaid y no graphviz por una razón concreta: GitHub renderiza
    # los bloques ```mermaid de forma nativa, así que el mismo texto se ve en la
    # documentación publicada Y al leer el archivo en el repositorio. Graphviz obligaría a
    # instalar un binario en el runner y no se vería en GitHub.
    "sphinxcontrib.mermaid",
]

# Sin autodoc, napoleon ni viewcode: ninguna página usa directivas de API. Estaban
# cargadas sin hacer nada.

# Sólo lo que se usa. `colon_fence` para los avisos, `deflist` para las listas de campos.
myst_enable_extensions = ["colon_fence", "deflist", "attrs_inline"]

# Sin esto habría que escribir ```{mermaid}, que es la directiva de Sphinx y GitHub muestra
# como texto plano. Con esto el bloque se escribe ```mermaid a secas: GitHub lo dibuja solo y
# Sphinx lo trata igual que la directiva. Un diagrama que sólo se ve en un lado se desactualiza
# en el otro sin que nadie lo note.
myst_fence_as_directive = ["mermaid"]
myst_heading_anchors = 3

templates_path = ["_templates"]
# `_generado` se incluye dentro de otras páginas con `{include}`, no es una página propia.
# Los documentos de trabajo se nombran con `_` adelante y se excluyen del build. `orphan: true`
# sólo calla el aviso de que no cuelgan de ningún `toctree`: la página se genera igual, y
# aparece en el buscador y en `llms.txt`. O sea decían "no publicado" y se publicaban.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "_generado", "_*.md"]

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
    # Los tres de arriba ponen "Ver código fuente" arriba a la derecha, y sólo en las páginas
    # de contenido. `footer_icons` es lo que el tema ofrece para un enlace presente en TODAS,
    # incluida la portada: va al pie de la barra lateral, que no se desplaza.
    "source_repository": "https://github.com/notluquis/mcp-pjud-cl/",
    "source_branch": "main",
    "source_directory": "docs/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/notluquis/mcp-pjud-cl",
            # El SVG va en línea y no como archivo estático a propósito: `html_static_path`
            # está vacío, y agregar un directorio de estáticos por un icono suma una ruta que
            # hay que mantener. Es el logotipo oficial de GitHub, tomado de la documentación
            # del propio tema.
            "html": """
                <svg stroke="currentColor" fill="currentColor" stroke-width="0"
                     viewBox="0 0 16 16">
                    <path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53
                    5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69
                    -.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58
                    1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89
                    -3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21
                    2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82
                    2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75
                    -3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013
                    8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path>
                </svg>
            """,
            "class": "",
        },
    ],
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


# -- tablas de competencias, generadas desde `parser.COMPETENCIAS` ----------------
#
# Mismo motivo que los esquemas, y con más razón: estas dos tablas se escribían a mano y
# se copiaban de la tabla del código, así que cada competencia nueva obligaba a recordar
# tocarlas. La de paneles ya había quedado vieja una vez.


def _generar_tablas(app):
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

    from mcp_pjud.client import MODULOS
    from mcp_pjud.parser import COMPETENCIAS

    destino = pathlib.Path(__file__).parent / "_generado"
    destino.mkdir(exist_ok=True)

    def lista(nombres):
        return ", ".join(f"`{n}`" for n in sorted(nombres))

    filas = []
    for exige, campo in (("`tribunal`", "tribunal"), ("`corte`", "corte"), ("nada", None)):
        cuales = [n for n in MODULOS if COMPETENCIAS[n].acota_por == campo]
        if cuales:
            filas.append(f"| {lista(cuales)} | {exige} |")
    (destino / "acotacion.md").write_text(
        "| Competencia | Exige |\n|---|---|\n" + "\n".join(filas) + "\n",
        encoding="utf-8",
    )

    paneles = (
        "historia",
        "litigantes",
        "notificaciones",
        "liquidaciones",
        "materias",
        "exhortos",
        "piezas_exhorto",
        "causa_de_origen",
    )
    filas = []
    for campo in paneles:
        cuales = [n for n in MODULOS if getattr(COMPETENCIAS[n], campo) is not None]
        filas.append(f"| `{campo}` | {lista(cuales) if cuales else 'ninguna todavía'} |")
    # El mismo dato como grafo. Se genera y no se dibuja a mano por lo de siempre: un diagrama
    # escrito a mano con las competencias de hoy es un dato repetido, y los dibujos son peores
    # que las tablas para notar que quedaron viejos.
    lineas = ["```mermaid", "graph LR"]
    for campo in paneles:
        cuales = [n for n in MODULOS if getattr(COMPETENCIAS[n], campo) is not None]
        for quien in sorted(cuales):
            lineas.append(f"  {quien} --> {campo}")
    sin_nada = sorted(
        n for n in MODULOS if not any(getattr(COMPETENCIAS[n], c) is not None for c in paneles)
    )
    for quien in sin_nada:
        lineas.append(f'  {quien} --> nada["ningún panel medido"]')
    lineas.append("```")
    (destino / "paneles-grafo.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    (destino / "paneles.md").write_text(
        "| Campo | Dónde existe |\n|---|---|\n" + "\n".join(filas) + "\n",
        encoding="utf-8",
    )


def setup(app):
    app.connect("builder-inited", _generar_esquemas)
    app.connect("builder-inited", _generar_tablas)
