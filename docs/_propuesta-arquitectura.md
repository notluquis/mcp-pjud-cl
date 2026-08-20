---
orphan: true
---

# Propuesta: arquitectura de la documentación para dos audiencias

:::{note}
Documento de trabajo, no publicado. Responde a la incidencia
[#57](https://github.com/notluquis/mcp-pjud-cl/issues/57) y la amplía: la pregunta no es dónde
mover secciones, sino cuál es la arquitectura correcta sabiendo que hay dos audiencias.

Lleva `orphan: true` porque no cuelga de ningún `toctree`. Sin eso, Sphinx emite
`toc.not_included` y la propuesta de la sección 4 (encender `-W`) haría fallar el build por
culpa de este mismo archivo. Aun con `orphan`, la página **sí** aparece en `llms.txt`,
ordenada al final: está medido en 2.1f. Cuando esta propuesta se ejecute o se
descarte, el archivo se borra.

Todo lo que dice "medido" se midió en este repositorio el 20-08-2026, sobre `2ab2714`, sin
consultar al Poder Judicial. Los comandos están citados para que se puedan repetir.
:::

## 1. La recomendación, en una frase

Un solo árbol de Diátaxis y **ninguna página por audiencia**: se parte `docs/roadmap.md` por
tipo de documento y no por lector, la audiencia se expresa como orden de entrada y como
descripción `html_meta` de cada página, y **antes de mover una sola línea se enciende `-W` en
el build**, porque hoy es lo único capaz de ver el destrozo y hoy está apagado.

Corolario, que es lo que hace que la arquitectura aguante con un solo mantenedor: lo que se
repite entre prosa y código no se resuelve con más disciplina ni con sustituciones de MyST,
sino generando el texto dentro del `.md` versionado y verificándolo en CI. La sección 4
desarrolla el mecanismo y la 5 lo aterriza con nombres de archivo.

## 2. Por qué

### 2.1 Lo medido en este repositorio

Seis mediciones sostienen todo lo demás. Ninguna es una opinión sobre estructura.

**a) La medición de la incidencia #57 ya envejeció, en cuatro días.** `wc -l docs/*.md` hoy da
2.786 líneas totales, `roadmap.md` 1.103 y `herramientas.md` 553. La incidencia dice que la
hoja de ruta es «2,3 veces la siguiente»: hoy es 2,0, porque la referencia creció 72 líneas.
Sigue siendo el 40% del total (1.103 de 2.786). El dato importa por lo que ilustra: una cifra
escrita a mano en un texto en prosa envejece aunque el texto tenga cuatro días, y ésta estaba
en una incidencia, que es justo donde nadie tiene un guardia.

**b) El build de la documentación no puede ver una reorganización rota.** El paso de CI es
`uv run sphinx-build -b html docs docs/_build/html` (`.github/workflows/tests.yml:87`), sin
`-W`. Se copió `docs/` a un directorio aparte, se agregó una página fuera de todo `toctree` y
dos `{doc}` a páginas inexistentes (`verificacion`, `ecosistema`, los dos nombres que esta
propuesta va a crear), y el resultado fue:

| Comando | Salida | Avisos |
|---|---|---|
| `sphinx-build -b html` (el de CI hoy) | **0**, «build succeeded» | 3, ignorados |
| `sphinx-build -W -b html` | **1**, «build finished with problems» | 3, tratados como error |

Los tres avisos son exactamente las dos clases que produce una reorganización:
`toc.not_included` y `ref.doc`. O sea: **con el comando de hoy, partir la hoja de ruta y dejar
media docena de enlaces rotos pasa en verde.**

**c) El guardia se puede encender hoy, sin deuda previa.** `sphinx-build -W -E docs` sobre el
árbol actual: exit 0, cero avisos. No hay backlog que limpiar antes. Y `conf.py` no define
`suppress_warnings`, que es lo único que podría vaciar el guardia sin que se note.

**d) `roadmap.md` es el 34% del texto que se sirve, y su descripción publicada describe sólo
su primera sección.** `llms-full.txt` son 239.535 bytes y `roadmap.html.md` son 82.419, o sea
el 34%. La entrada de `roadmap.md` en `llms.txt` dice «Esta tabla es lo más importante de la
página. Distingue tres cosas que suelen confundirse:», que es literalmente su primera línea de
prosa, cortada a 100 caracteres. La de `uso.md` sale partida a media palabra. No es un defecto
de la extensión: `sphinx_llm/txt.py:1047` toma la primera línea de más de 10 caracteres y la
trunca. Un archivo que son seis documentos no puede tener una descripción.

**e) Eso tiene arreglo y es barato.** `get_page_description` (`sphinx_llm/txt.py:692`) prefiere
el `html_meta` de la página si existe. Se le agregó a `uso.md` un front matter con

```yaml
html_meta:
  "description": "..."
```

y la línea de `llms.txt` pasó de la primera frase cortada a la descripción escrita. Medido, no
inferido. Y `html_meta` no sirve sólo para eso: es la etiqueta `<meta name="description">` de la
página publicada, o sea lo que muestra un buscador y lo que ve quien comparte el enlace.

:::{caution}
**`llms.txt` es una capacidad, no una audiencia, y no puede justificar decisiones de
estructura.** Ahrefs midió 137.210 dominios en mayo de 2026 y **el 97% de los `llms.txt`
publicados no recibió ninguna petición**
([estudio](https://ahrefs.com/blog/llmstxt-study/)). Generarlo cuesta cero y no duplica ningún
dato, así que sobrevive el criterio del proyecto y se queda. Pero todo argumento de esta
propuesta se sostiene sobre el lector humano; lo que sigue sobre `llms.txt` es efecto
secundario medido, no premisa.

Dato de identidad, porque es donde se equivoca uno: hay al menos dos paquetes distintos
compitiendo, `sphinx-llm` y `sphinx-llms-txt` (de jdillard). El instalado acá es
`sphinx-llm` 1.0.0, autoría de Jacob Tomlinson, alojado en
[NVIDIA/sphinx-llm](https://github.com/NVIDIA/sphinx-llm); los dos nombres que circulan son el
mismo paquete. Verificado en el `METADATA` del entorno, no en un README. Read the Docs **no**
genera el archivo: lo sirve desde la raíz de la versión por defecto si uno lo produce
([doc](https://docs.readthedocs.com/platform/latest/reference/llms-txt.html)).
:::

**f) El `toctree` decide el orden de `llms.txt`, y sus `:caption:` se pierden.** En el código de
la extensión instalada (`sphinx_llm/txt.py:611`):

```
# Follow the Sphinx toctree, with orphaned documents sorted last.
```

La cadena `caption` no aparece en el archivo, y la única sección que escribe es un `## Pages`
plano. O sea: la partición de Diátaxis es visible en la barra lateral de Furo y **no** en el
archivo servido. Verificado también que una página huérfana no desaparece: se ordena al final.
Sacar algo del `toctree` lo esconde del lector humano y lo deja donde estaba para el otro
canal.

### 2.2 Dónde chocan las dos audiencias, y por qué eso decide la arquitectura

Diátaxis parte por **propósito del lector**, no por identidad del lector. Al mapear las dos
audiencias contra los cuatro propósitos, casi todo se separa solo:

| Pregunta | Quién la hace | Dónde vive |
|---|---|---|
| ¿me sirve esto? | abogada | `uso.md` (Explicación) |
| ¿cómo lo instalo? | abogada, o su informático | `instalacion.md` (Cómo se hace) |
| ¿qué significa este campo? | abogada | `herramientas.md` (Referencia) |
| ¿por qué esta fecha y no la otra? | abogada | `index.md`, `uso.md` (Explicación) |
| ¿qué se decidió y por qué? | quien audita | `licencia.md`, `cumplimiento.md`, hoja de ruta |
| ¿qué falta y en qué orden? | quien audita | hoja de ruta |
| **¿esto está verificado o es una suposición?** | **las dos** | hoy: línea 3 de un archivo de mil |

La última fila es toda la arquitectura. La tabla «Qué está verificado y qué no» es una
**consulta**, no una explicación: quien la abre busca una fila, no un argumento. La abogada la
consulta para saber si su competencia está cubierta antes de confiar en una fecha; quien audita
la consulta para saber qué se puede afirmar del sistema. Es la misma tabla, con el mismo
contenido, leída por dos personas con motivos distintos.

Partirla en «verificación para abogados» y «verificación para quien audita» **duplicaría el
dato más consecuente del proyecto**, que es lo que `AGENTS.md` prohíbe en la línea que dice que
un dato repetido es un dato que va a quedar viejo. Y no es una prohibición abstracta: ya hay
ocho guardias en `tests/test_documentacion.py` que existen porque una cifra se escribió dos
veces y una de las dos envejeció.

De ahí la recomendación: **las dos audiencias no piden dos árboles, piden dos puertas al mismo
árbol.**

### 2.3 Una asimetría que hoy nadie ve

El material más denso para la segunda audiencia (`AGENTS.md` y `.github/CONTRIBUTING.md`) **no
entra al build de Sphinx**. El `toctree` «Proyecto» de `index.md` los enlaza como URL externa a
GitHub, o sea como enlace de salida, no como página.

Para quien audita, eso significa tres cosas concretas: las reglas que no se negocian **no
aparecen en el buscador del sitio**, no están en el árbol de la barra lateral, y leerlas obliga
a salir de Read the Docs hacia GitHub, donde ya no hay ni navegación ni versión. La documentación
publicada le dedica 1.103 líneas a lo que falta hacer y cero a lo que no se puede hacer.

Es un hallazgo de arquitectura, no de estilo, y mover secciones de `roadmap.md` no lo toca. La
pieza (c) de la sección 3.3 lo resuelve sin duplicar una línea.

### 2.4 Qué hacen otros proyectos con dos audiencias

<!-- PENDIENTE-AUDIENCIAS -->

### 2.5 Árbol contra grafo

La documentación de Sphinx es un árbol y no es negociable: `root_doc` es **uno solo**
([configuración](https://www.sphinx-doc.org/en/master/usage/configuration.html)). No hay
portadas múltiples. Lo que sí se puede es colgar una página de **dos** `toctree`, que es la
versión mínima de un grafo, y ahí es donde conviene mirar antes de proponerlo.

**Lo que se pierde, y no está documentado.** En Sphinx 9.1.0, cuando una página cuelga de dos
`toctree`, `_check_toc_parents` emite el mensaje con `logger.info`, **no** con `logger.warning`.
Consecuencia directa para esta propuesta: **`-W` no lo atrapa**. Y lo que pasa después es que
dos mecanismos independientes eligen padres distintos: el anterior/siguiente sale de
`collect_relations()`, que recorre en preorden y se queda con el **primer** encuentro; la barra
lateral se queda con `max(parents)`, o sea el **mayor alfabéticamente**. Cuando discrepan, la
ruta resaltada de la barra lateral y la cadena anterior/siguiente apuntan a lugares distintos.
Está reportado y abierto:
[sphinx-doc/sphinx#13012](https://github.com/sphinx-doc/sphinx/issues/13012).

Un grafo, en este stack, es una estructura que se rompe en silencio y que el guardia que esta
propuesta quiere encender no puede ver. Eso basta para descartarlo como esqueleto.

**Etiquetas.** `sphinx-tags` es la única extensión de etiquetado del ecosistema que calza con
MyST, y su estado es incómodo: último release en PyPI **0.4, de julio de 2024**, con commits en
`main` hasta julio de 2026 y un README que se autodescribe como experimental. Instalarla desde
PyPI es quedarse dos años atrás del código. Para un repositorio de un mantenedor que fija
versiones con `uv.lock`, es deuda, no navegación.

**El tema tampoco ofrece un segundo eje.** Furo no tiene barra superior ni navegación de dos
niveles, y es doctrina explícita de su autor, no una omisión. En
[furo#242](https://github.com/pradyunsg/furo/discussions/242) Pradyun Gedam responde que separar
«page structure» de «site structure» es una decisión de diseño: la barra izquierda es la
estructura del sitio y la derecha es la de la página. Ojo con lo que ahí **no** dice: no
recomienda migrar a otro tema. Lo que sí hay dentro de Furo es el mecanismo de dos niveles que
este repositorio ya usa, `:caption:` como encabezado de sección más sub-índices anidados, que es
lo mismo que hace la documentación de `pip`.

**Y el mismo estándar admite las dos respuestas.** En `llms.txt`, Prefect publica un archivo
**plano**, con unas 800 referencias sin anidar y secciones temáticas que no espejan el árbol de
navegación. Cloudflare hace lo contrario: el archivo raíz enlaza a un `llms.txt` por producto y
la jerarquía vuelve por anidamiento de archivos. La especificación permite ambas. Es la prueba
de que árbol contra grafo no tiene una respuesta correcta en abstracto: tiene una respuesta
correcta **por proyecto**, y depende de cuánta disciplina puede sostener quien lo mantiene.

**Conclusión.** Se queda el árbol como esqueleto, porque es lo único que Sphinx sabe verificar,
lo único que Furo sabe dibujar y lo único que `-W` puede proteger. El grafo entra donde no
cuesta mantenimiento: enlaces `{doc}` en el cuerpo y el segundo bloque de entrada de 3.3a. Es un
grafo tendido sobre un árbol, que es lo que cualquier sitio de documentación es en la práctica.

Sobre cruzar Diátaxis con un eje de audiencia: la medición de 2.2 muestra que el cruce sería
degenerado. De las siete preguntas, seis caen en una sola audiencia y **una** cae en las dos, y
esa una es una consulta de Referencia. Un eje entero para una celda compartida no se paga.
Diátaxis basta, siempre que la partición se haga bien, que es exactamente lo que hoy no pasa con
`roadmap.md`.


## 3. El mapa concreto

Once páginas donde hoy hay nueve. Dos nuevas, ninguna renombrada, **ninguna URL publicada
muere**: `roadmap.md` y `cumplimiento.md` conservan su nombre, así que no hace falta ninguna
extensión de redirecciones.

| Página | Diátaxis | Qué se lleva | Líneas |
|---|---|---|---|
| `index.md` | portada | igual, más la segunda puerta de 3.3 | 95 |
| `instalacion.md` | Cómo se hace | sin cambios | 294 |
| `ejemplos.md` | Cómo se hace | sin cambios | 213 |
| `herramientas.md` | Referencia | sin cambios | 553 |
| **`verificacion.md`** | **Referencia** | ver 3.1 | ~280 |
| `uso.md` | Explicación | sin cambios | 146 |
| `cumplimiento.md` | Explicación | más `## Hallazgos de OpenSSF Scorecard` (84) | ~303 |
| `roadmap.md` | Explicación | ver 3.2 | ~340 |
| **`ecosistema.md`** | **Explicación** | `## Qué más existe` entero | ~386 |
| `licencia.md` | Explicación | sin cambios | 92 |
| `financiamiento.md` | Explicación | sin cambios | 71 |

Ninguna página queda por sobre `herramientas.md`, que hoy es la más larga después de la hoja de
ruta y que no se toca. La que hay que mirar después es `ecosistema.md`, cuya subsección
`### Lo que falta, medido` son 208 líneas por sí sola: es la sección individual más grande de
toda la documentación y ya merece su propio seguimiento.

### 3.1 `verificacion.md`: lo que los guardias ya estaban señalando

El corte no se inventa. Los cuatro guardias que están anclados a un **título literal** de la
hoja de ruta apuntan, todos, a un hallazgo medido sobre la plataforma que quedó escrito dentro
de una entrada de versión. Un plan de versión es Explicación; una tabla de rutas medidas es
Referencia. Los guardias ya venían marcando dónde estaba la línea.

| Origen en `roadmap.md` | Líneas | Guardia que lo ancla |
|---|---|---|
| `## Qué está verificado y qué no` y sus cuatro subsecciones | 73 | `test_la_hoja_de_ruta_no_declara_sin_ejecutar_lo_que_ya_se_verifico`, `test_el_detalle_mapeado_no_sigue_figurando_entre_las_rutas_sin_ejecutar` |
| `### Los diez buscadores` y `### Endpoints del buscador, mapeados y sin ejecutar` | 57 | `test_las_cifras_medidas_del_buscador_son_las_mismas_en_todas_partes` |
| `#### Los dos lados del exhorto, medidos` (dentro de `### 0.5`) | ~30 | `test_lo_que_la_hoja_de_ruta_dice_del_exhorto_es_lo_que_traen_las_fixtures` |
| la tabla de rutas de `### 0.7: documentos` | ~25 | `test_las_rutas_de_documentos_de_la_hoja_de_ruta_son_las_de_la_respuesta_real` |
| `### 0.7a: los códigos de tribunal` | 33 | `test_los_codigos_de_tribunal_que_cita_la_documentacion_son_los_medidos` |
| las cifras de `## Herramientas de descubrimiento que no existen` | ~5 | `test_la_cuenta_de_rutas_de_la_plataforma_es_la_de_la_fixture` |
| `## Reglas de la plataforma ya mapeadas` | 22 | (sin guardia hoy) |
| `## Sobre los identificadores de causa en esta documentación` | 19 | (sin guardia hoy) |
| la tercera fecha de `### 0.7b: la georreferencia` | ~15 | (sin guardia hoy, y es un dato de fecha) |

Regla del corte, para que no genere un dato repetido: **la entrada de versión conserva la
decisión y enlaza con `{doc}`; la tabla medida se va entera.** Si al terminar la entrada de
versión sigue citando la cifra, el corte quedó mal hecho.

`### 0.7b` merece atención aparte: dice que la georreferencia trae una **tercera** fecha. Este
proyecto existe por la distinción entre dos fechas. Una tercera fecha medida y sin guardia,
enterrada en la línea 397 de un archivo de mil, es exactamente el tipo de dato que la
arquitectura tiene que sacar a la superficie.

### 3.2 `roadmap.md`: lo que queda, y por fin es una hoja de ruta

`## Versionado` con sus condiciones para 1.0.0, `## Hoja de ruta` sin los hallazgos medidos,
`### Lo que falta decidir` de jurisprudencia, `## Herramientas de descubrimiento que no existen`
sin sus cifras, `## Lo que se va a romper` y `## Cómo influir en esto`. Todo Explicación, un
solo propósito, y el título por fin describe el contenido.

### 3.3 Las dos puertas, que es toda la solución de audiencia

Nada de esto crea una página para la segunda audiencia. Lo que crea es una segunda entrada al
mismo árbol, en tres piezas, ninguna de las cuales duplica un dato:

**a) Un segundo bloque en «Por dónde empezar» de `index.md`.** El que existe le habla a la
abogada. El nuevo, con un título del tipo «Si vienes a evaluar o auditar el código», enlaza a
`verificacion.md` primero, después a `cumplimiento.md`, `licencia.md` y `roadmap.md`. Son
enlaces, no contenido: cero duplicación, y la portada pasa a declarar que hay dos lecturas
posibles en vez de dejarlo implícito.

**b) `html_meta` por página.** Es la `<meta name="description">` de la página publicada, o sea
lo que muestra un buscador y lo que aparece al compartir el enlace, y de paso lo que `llms.txt`
usa en vez de truncar la primera línea (2.1e). Hoy está sin usar en las nueve páginas. Once
descripciones de una frase, en el front matter, sin duplicar contenido: es donde la audiencia se
nombra explícitamente («para quien evalúa si puede confiar en una fecha», «para quien audita el
alcance verificado») sin que eso obligue a partir ninguna página.

**c) `AGENTS.md` y `.github/CONTRIBUTING.md` entran al `toctree`.** Hoy son enlaces externos
(2.3), o sea invisibles para `llms.txt`. La forma barata, sin mover los archivos ni duplicarlos,
es una página `contribuir.md` de pocas líneas que los incluya con `{include} ../AGENTS.md`,
igual que `herramientas.md` ya incluye `_generado/`. Es lo que hace que las reglas que no se
negocian lleguen al lector que las necesita.

:::{warning}
La pieza (c) es la única de las tres que puede salir mal en silencio: un `{include}` de un
archivo que se renombra deja de incluir sin avisar si `-W` no está encendido. Es otra razón
para el orden que impone la sección 6.
:::

## 4. Que la documentación no diverja del código, como mecanismo

Ésta es la parte que se paga todas las semanas. La separación de audiencias se decide una vez.

### 4.1 La pregunta directa: ¿hay algo mejor que los 63 guardias?

**No para reemplazarlos, sí para bajar el costo por afirmación.** La razón es estructural y se
puede enunciar en una línea:

> Los `.md` que hay que vigilar no son los que Sphinx construye.

`PROSA`, en `tests/test_documentacion.py:54`, recorre `*.md` de la raíz, de `docs/` y de
`.github/`. De esos, Sphinx sólo ve los nueve de `docs/`. `README.md`, `AGENTS.md`,
`CHANGELOG.md`, `CLAUDE.md` y las plantillas de `.github/` no pasan por ningún build, así que
**ningún mecanismo de Sphinx puede vigilarlos**: ni `myst_substitutions`, ni `{include}`, ni un
hook `builder-inited` como los dos que ya tiene `conf.py`.

Eso descarta la respuesta que uno esperaría. Las sustituciones de MyST funcionan, y las probé:
un `conf.py` que importa `INTERVALO_MINIMO` y `RAFAGA_MAXIMA` y los pone en
`myst_substitutions` interpola bien en prosa, **en celdas de tabla** y dentro de directivas como
`{note}`. No interpola dentro de un bloque de código cercado: ahí `{{ intervalo }}` sale
literal. La documentación oficial lo dice con todas sus letras, «Substitutions will only be
assessed where you would normally use Markdown, e.g. not in code blocks»
([myst-parser](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)), y
`sphinx-substitution-extensions` existe para tapar ese hueco. Detalle menor pero real: el valor
crudo sale `5.0`, no `5`, así que habría que formatear.

Aun así, no las recomiendo para este repositorio, y el motivo no es técnico sino de
consecuencias. Una sustitución **vacía el guardia**: el `.md` deja de tener el número, así que
ya no hay nada que comparar contra la constante. Se cambia un guardia que muerde por una
interpolación que ningún test puede leer desde el archivo. Y de paso el fuente se lee peor en
GitHub, que es lo mismo que `conf.py` ya argumenta cuando explica por qué eligió mermaid sobre
graphviz.

### 4.2 El mecanismo que sí calza: escribir el valor dentro del `.md`

[`cog`](https://cog.readthedocs.io/en/latest/) ejecuta Python embebido en comentarios y **deja
el resultado escrito en el archivo**, versionado y visible en el diff. Corre sobre texto plano,
sin Sphinx, así que alcanza a `README.md`, `AGENTS.md`, `CHANGELOG.md` y hasta los `.yml` de
workflows.

El precedente no es teórico. `coverage.py`, de Ned Batchelder, que es además el autor de `cog`,
lo usa exactamente así: el `Makefile` regenera con `-r` y `tox.ini` verifica en CI con
`--check`, sobre `doc/*.rst` **y** sobre `.github/workflows/*.yml`, con
`--check-fail-msg='run make prebuild'` para que quien vea el rojo sepa qué comando correr
([Makefile](https://github.com/nedbat/coveragepy/blob/master/Makefile),
[tox.ini](https://github.com/nedbat/coveragepy/blob/master/tox.ini)). `cogapp` 3.6.0 es de
septiembre de 2025 y está clasificado Production/Stable.

En Markdown los marcadores van en comentarios HTML, o sea invisibles al renderizar y visibles
al leer el fuente.

### 4.3 Los tres niveles

| Nivel | Cuándo | Mecanismo | Alcanza a |
|---|---|---|---|
| 1 | el dato sale del código y se puede plantillar | `cog` con marcador en comentario HTML | **todo el repositorio**, incluidos `README.md` y `AGENTS.md` |
| 2 | referencias internas y páginas fuera del árbol | `sphinx-build -W` | sólo `docs/` |
| 3 | afirmación de prosa que no se puede plantillar | guardia en `tests/test_documentacion.py` | todo `PROSA` |

El nivel 3 no desaparece y no debe desaparecer. Lo que cambia es su tamaño: de los 28 guardias
anclados a una página concreta, **nueve** afirman «este valor literal del código aparece en esta
página», que es justo lo que el nivel 1 convierte en plantilla. Los otros diecinueve afirman
relaciones (igualdad de conjuntos, ausencia de una frase, consistencia interna de una tabla) y
se quedan donde están, porque no hay valor que interpolar.

### 4.4 Cómo se sistematiza el nivel 3, y cómo se comprueba que muerde

El problema que `AGENTS.md` ya nombra es que un guardia que no puede fallar imprime lo mismo que
uno que pasa, y que la única forma conocida de saberlo es romper a mano lo que protege. Eso se
puede mecanizar sin herramienta nueva, cambiando una sola cosa: **que el guardia reciba el
texto en vez de leer el archivo.**

```python
def verificar(texto: str, afirmacion: str) -> None: ...
```

Con esa firma, una sola tabla declarativa de `(archivo, afirmación, fuente)` alimenta **dos**
tests parametrizados:

- `test_dato_vigente[fila]`: lee el `.md` real y verifica.
- `test_el_guardia_muerde[fila]`: toma el mismo texto, le corrompe la afirmación con un
  `str.replace`, y afirma que el guardia **falla**.

Como comparten la tabla, agregar una afirmación agrega automáticamente su prueba de mordida.
Deja de ser posible escribir un guardia sin su rojo. Es la mecanización de una regla que hoy es
disciplina, que es exactamente lo que esta propuesta persigue.

Nota sobre `mutmut`, que este repositorio ya corre: **no muta archivos `.md`**, y
`paths_to_mutate` es `src/mcp_pjud/`. Sirve por el otro lado (mutar `INTERVALO_MINIMO` mata al
guardia que compara la prosa contra esa constante, o sea prueba que el guardia está conectado al
código) pero no dice nada sobre si está conectado al **texto**. Un guardia cuya regex dejó de
calzar con la prosa pasa verde y `mutmut` lo da por bueno.

### 4.5 Tabla de mordidas

Ninguna herramienta entra sin decir cómo se la ve en rojo.

| Mecanismo | Qué se rompe a propósito | Rojo esperado |
|---|---|---|
| `sphinx-build -W` | un `{doc}` a una página inexistente | exit 1, `ref.doc`. **Medido**: exit 0 sin `-W`, exit 1 con `-W` |
| `sphinx-build -W` (segunda mordida) | agregar `myst.xref_missing` a `suppress_warnings` en `conf.py` | si con eso el paso anterior vuelve a verde, el guardia estaba vacío. Hoy `conf.py` no define `suppress_warnings` |
| `cog --check` | editar a mano un dígito **dentro** de la región generada | exit distinto de 0, más el diff con `--diff` y el comando de arreglo con `--check-fail-msg` |
| guardia de nivel 3 | el `test_el_guardia_muerde` de 4.4 | rojo si el guardia no reacciona a la corrupción |
| ejemplos JSON (sección 5) | renombrar un campo del modelo | **medido**: renombrando `fecha_diligencia` la comprobación pasa a rojo en `docs/ejemplos.md:21` y `:120` |

## 5. Qué se puede generar en vez de escribir a mano

`conf.py` ya genera dos cosas y las incluye con `{include} _generado/…`: los esquemas de cada
herramienta y las tablas de competencias. El patrón está probado. Lo que sigue son los
candidatos medidos, en orden de cuánto duplican.

### 5.1 El bloque de configuración del cliente MCP: cuatro copias, un cuerpo

Medido: hay **cuatro** bloques ```` ```json ```` con la configuración del servidor, tres en
`docs/instalacion.md` (líneas 45, 61 y 78, para Claude Desktop, Cursor y VS Code) y uno en
`README.md`. Los cuatro cuerpos son **idénticos**: la única diferencia real es la clave de
primer nivel, `mcpServers` contra `servers`, que es justo lo que la prosa de VS Code advierte.

Cada copia repite cinco datos: el ejecutable `uvx`, la URL del repositorio, la rama `@stable`,
el nombre del script `mcp-pjud` y la variable `MCP_PJUD_CONTACTO`. Cinco por cuatro son veinte
lugares, vigilados hoy por tres guardias separados
(`test_el_ejecutable_que_documentan_las_guias_es_el_que_declara_el_paquete`,
`test_la_instalacion_documentada_apunta_a_la_rama_publicada`,
`test_la_variable_de_entorno_documentada_es_la_que_el_servidor_lee`).

Es el candidato más claro del repositorio, y **es el que prueba que la herramienta tiene que ser
`cog` y no un hook**: una de las cuatro copias vive en `README.md`, donde `{include}` no llega.

### 5.2 El resto, por orden de rendimiento

| Qué | Dónde está escrito a mano | Fuente | Guardia que reemplaza |
|---|---|---|---|
| listado de herramientas | `README.md` | `mcp.list_tools()` | `test_el_readme_nombra_todas_las_herramientas_que_el_servidor_expone` |
| cuenta de dependencias | `docs/instalacion.md` | `pyproject.toml` | `test_la_cuenta_de_dependencias_que_cita_la_guia_es_la_del_paquete` |
| versión de Python | `docs/instalacion.md`, `README.md` | `requires-python` | `test_la_version_de_python_que_piden_las_guias_es_la_que_exige_el_paquete` |
| tope de filas | `docs/herramientas.md` | `FILAS_MAXIMAS` | `test_los_topes_declarados_coinciden_con_el_codigo` |
| cuenta de cortes | `docs/herramientas.md` | medición versionada | `test_la_cuenta_de_cortes_que_cita_la_referencia_es_la_medida` |
| cuenta de buscadores | `docs/herramientas.md` | el código | `test_la_cuenta_de_buscadores_verificados_es_la_del_codigo` |
| intervalo y ráfaga | seis archivos, dentro y fuera de `docs/` | `INTERVALO_MINIMO`, `RAFAGA_MAXIMA` | parte de `test_ninguna_pagina_cita_un_intervalo_distinto_del_real` |

Nombres de archivo propuestos, siguiendo la convención que ya existe:
`docs/_generado/config-mcp.md` (5.1, si se hace con `{include}` para las tres copias de
`instalacion.md`), y marcadores de `cog` embebidos en `README.md`, `docs/instalacion.md` y
`docs/herramientas.md` para el resto. Regenerar con un solo comando, verificar en CI con
`cog --check --diff`.

### 5.3 Y lo que NO conviene generar

`### Verificado contra el sistema real` es tentador, porque `COMPETENCIAS` ya sabe qué panel
tiene cada competencia y `conf.py` ya dibuja ese grafo. Pero la tabla no dice sólo qué existe:
dice **contra qué se verificó y cuándo**, y eso no está en el código ni debería estarlo. La
regla que se cae sola de Diátaxis es: se genera Referencia, se escribe Explicación a mano. Una
página que mezcla las dos es la que se vuelve ilegible, y es el fallo que `AGENTS.md` ya nombra.

### 5.4 Una verificación nueva que hoy no existe y cuesta poco

Medido: hay 51 bloques de código cercados en toda la prosa. Uno solo es `python` y ninguno trae
un doctest. En cambio hay **ocho** bloques `json`, y los ocho parsean. Tres de ellos son
respuestas de ejemplo del modelo `Actuacion`.

No se pueden validar con `Actuacion.model_validate`, y eso es un hallazgo, no un obstáculo: los
ejemplos están **recortados a propósito** («respuesta, recortada al folio que interesa»), así
que la validación estricta falla por campos ausentes y estaría midiendo mal. Lo que sí muerde es
la comprobación de subconjunto: toda clave del ejemplo tiene que ser un campo del modelo.

Verificado en los dos sentidos: pasa hoy sobre los tres bloques, y renombrando
`fecha_diligencia` en el modelo se pone en rojo en `docs/ejemplos.md:21` y `:120`. Cero
dependencias nuevas.

## 6. Qué se rompe al hacerlo

Estado de partida, medido hoy: `uv run pytest tests/test_documentacion.py -q` recolecta **65
casos** de 63 funciones y pasan todos. `sphinx-build -W` sobre el árbol actual sale en 0.

### 6.1 El censo

De las 63 funciones del archivo:

| Cómo localizan el texto | Cuántas | Qué les pasa al mover |
|---|---|---|
| recorren `PROSA`, que es un glob de `*.md` | **7** | nada, sobreviven y **cubren las páginas nuevas solas** |
| nombran una página por ruta o una sección por título literal | **28** | dependen de la ruta |
| de esas, **ancladas a `docs/roadmap.md`** | **8** | se caen todas |
| de esas ocho, ancladas **además** a un título literal | **4** | se caen dos veces |

Las siete de `PROSA` son la parte buena de la noticia y conviene decirla: los guardias que
recorren el glob **empiezan a vigilar `verificacion.md` y `ecosistema.md` el día que existan**,
sin tocarlos. Es evidencia de que el patrón de glob envejece mejor que el de ruta fija, y es un
argumento para escribir los guardias nuevos así.

### 6.2 Los ocho, con nombre y línea

| Línea | Guardia | Se repunta a | Ancla de título |
|---|---|---|---|
| 156 | `test_las_cifras_medidas_del_buscador_son_las_mismas_en_todas_partes` | `verificacion.md` | (vía `PAGINAS_CON_LA_MEDICION:152`) |
| 862 | `test_la_hoja_de_ruta_no_declara_sin_ejecutar_lo_que_ya_se_verifico` | `verificacion.md` | `### Mapeado pero nunca ejecutado` |
| 885 | `test_la_hoja_de_ruta_no_publica_el_diagnostico_que_resulto_falso` | **`PROSA`**, ver 6.3 | |
| 1084 | `test_el_detalle_mapeado_no_sigue_figurando_entre_las_rutas_sin_ejecutar` | `verificacion.md` | `### Mapeado pero nunca ejecutado` |
| 1277 | `test_los_codigos_de_tribunal_que_cita_la_documentacion_son_los_medidos` | `verificacion.md` | |
| 1315 | `test_las_rutas_de_documentos_de_la_hoja_de_ruta_son_las_de_la_respuesta_real` | `verificacion.md` | `### 0.7: documentos` |
| 1346 | `test_lo_que_la_hoja_de_ruta_dice_del_exhorto_es_lo_que_traen_las_fixtures` | `verificacion.md` | `#### Los dos lados del exhorto` |
| 1491 | `test_la_cuenta_de_rutas_de_la_plataforma_es_la_de_la_fixture` | `verificacion.md` | |

Los ocho fallan **ruidosamente**: `_texto()` sobre una ruta inexistente levanta
`FileNotFoundError`, y un `.split("### 0.7: documentos", 1)[1]` sobre un título que se movió
levanta `IndexError`. Ninguno se degrada en silencio al romperse.

### 6.3 Lo peligroso no es el rojo, es el arreglo

Ésta es la parte que hay que leer dos veces, porque es la lección que este repositorio ya pagó
aplicada a la migración misma: **un guardia que no puede fallar imprime lo mismo que uno que
pasa**, y los tres arreglos de abajo devuelven el verde cubriendo menos.

**a) `PAGINAS_CON_LA_MEDICION` es una lista positiva.** Hoy es
`("docs/herramientas.md", "docs/roadmap.md")`. Cuando las cifras se vayan a `verificacion.md`,
el guardia se pone rojo porque `roadmap.md` ya no las tiene. Hay dos formas de devolverlo a
verde: **agregar** la página nueva, que es lo correcto, o **sacar** `roadmap.md`, que también
funciona y deja la medición sin vigilancia en su único hogar real.

**b) `test_los_codigos_de_tribunal...` se conforma con una coincidencia.** La línea 1299 es
`assert citados, "..."`, o sea exige que **al menos un** tribunal medido aparezca. Si los
códigos quedan repartidos entre `verificacion.md` y una entrada de versión, repuntar el guardia
a una de las dos lo deja verde cubriendo la mitad, sin ninguna señal.

**c) El guardia 885 es negativo y hay que convertirlo, no repuntarlo.** Afirma que dos frases
desmentidas por la medición **no** aparecen en `roadmap.md`, y que `radio-group` sí. Una frase
prohibida tiene que estarlo en todas partes: si el guardia sigue leyendo un solo archivo, la
frase falsa puede reaparecer en `verificacion.md` sin que nada la vea. La mitad negativa se
mueve a `PROSA`; la positiva se queda apuntando a la página donde viva el diagnóstico.

**Paso obligatorio, no opcional.** Después de repuntar cada uno de los ocho: romper el dato **en
su nuevo hogar**, correr la suite, ver el rojo, restaurar. En los cuatro anclados a un título
literal es obligatorio, porque ahí se mueven dos cosas a la vez, la ruta y el ancla, y un
`.split()` que ya no calza es exactamente la forma de fallo que este repositorio ya encontró en
un `grep` cuya salida vacía se leía como "sin hallazgos".

### 6.4 Lo demás que se rompe

- **Los enlaces internos**, y hoy nadie los ve: es la medición 2.1b. Por eso `-W` va primero.
- **El `toctree` de `index.md`**: dos entradas nuevas, y el orden cambia.
- **Un hueco en el guardia de tráfico saliente que conviene anotar acá.**
  `test_todo_workflow_que_corre_la_suite_bloquea_el_trafico_saliente` sólo mira los workflows
  cuyo texto contiene `pytest` o `mutmut`. Un workflow nuevo dedicado a la documentación (por
  ejemplo para `linkcheck` o `lychee`) **no calza con ese filtro y se salta el guardia**. Si
  alguna vez se agrega uno con red, el filtro hay que ampliarlo primero.
- **Ninguna URL publicada muere**, por diseño: `roadmap.md` y `cumplimiento.md` conservan su
  nombre. No hace falta `sphinx-reredirects` ni `sphinxext-rediraffe`.

### 6.5 El orden, que es lo único que no se puede alterar

1. **`-W` en el paso de documentación de `tests.yml`.** Medido: hoy sale verde, no hay deuda.
   Si entra después del movimiento, el destrozo del movimiento es invisible mientras se hace.
2. El corte de `roadmap.md` en cuatro, con los ocho guardias repuntados y **vistos en rojo** uno
   por uno.
3. `html_meta` en las once páginas y el segundo bloque de entrada del `index.md`.
4. La generación de la sección 5, empezando por el bloque de configuración, que es el que más
   duplica.

## 7. Lo que se descartó, y por qué

Esta sección importa tanto como la recomendación: casi todo lo de abajo es lo que uno propondría
sin medir.

### 7.1 De arquitectura

**Dos árboles, o un sitio aparte para quien contribuye (el patrón `docs/internals/` de Django,
o un devguide separado).** Duplicaría la tabla de verificación, que es el único contenido que
las dos audiencias consultan (2.2), y ése es el dato más consecuente del proyecto. Además
resuelve el problema equivocado: el material de la segunda audiencia ya está separado, tanto que
está **fuera del sitio** (2.3), y lo que falta es meterlo, no sacar más.

**Pestañas de `sphinx-design` por audiencia dentro de la misma página.** Descartado por una
razón concreta y no estética: el CSS de `tab-set` es `display: none` para la pestaña inactiva, y
**Ctrl+F no encuentra texto con `display:none`**. Una abogada que busca «georreferenciado» en la
página no lo encontraría si quedó en la pestaña del otro perfil. Peor todavía, la selección se
guarda en `localStorage` y persiste **entre páginas y entre sesiones**, así que una elección
accidental esconde media documentación de forma permanente. Si en algún momento hace falta
plegar contenido, `dropdown` es lo correcto: son `<details>`/`<summary>` nativos, y Chromium los
expande durante la búsqueda en página
([Chrome](https://developer.chrome.com/docs/css-ui/hidden-until-found)).

**Una página colgando de dos `toctree`, o `sphinx-tags`.** Los motivos están medidos en 2.5: el
mensaje de Sphinx es `info` y `-W` no lo ve, la barra lateral y el anterior/siguiente eligen
padres por reglas distintas ([#13012](https://github.com/sphinx-doc/sphinx/issues/13012)), y
`sphinx-tags` lleva dos años sin publicar en PyPI.

**`:orphan:` para esconder páginas de trabajo.** Medido: no las esconde de `llms.txt`, sólo
silencia el aviso `toc.not_included`. Tampoco las saca del buscador del sitio, que usa el campo
aparte `:no-search:`.

**Cambiar de tema para tener navegación de dos niveles.** Furo no la tiene por decisión
explícita de su autor, que además no recomienda ninguna alternativa (2.5). Cambiar de tema por
un eje de navegación que 2.2 muestra innecesario es el peor negocio de esta lista.

### 7.2 De verificación

**`sybil`.** Es la herramienta que uno esperaría acá, está viva (10.1.0, junio de 2026) y trae
parsers MyST de primera clase. Y aun así no aplica: **medido, hay 51 bloques de código cercados
en toda la prosa, de los cuales exactamente uno es `python` y ninguno trae un doctest.** Sybil
existe para verificar ejemplos ejecutables, y este proyecto casi no tiene. El día que
`docs/ejemplos.md` traiga código Python que se pueda correr, se reevalúa; hoy sería una
dependencia para un solo bloque.

**`pytest --doctest-glob='*.md'`.** Descartado por una razón que este repositorio reconoce de
memoria: **no entiende las cercas ```` ```python ````, sólo prompts `>>>` sueltos**
([pytest](https://docs.pytest.org/en/stable/how-to/doctest.html)). Como acá no hay ni un `>>>`,
correría, no verificaría nada y pasaría en verde. Es el guardia que no puede fallar, de manual.

**`sphinx.ext.doctest`.** Su documentación habla de reStructuredText y no menciona MyST. Además
exige un builder aparte y sus fallos no salen por `pytest`.

**`pytest-examples`.** `0.0.18`, mayo de 2025, quince meses sin publicar, y arrastra `black` y
`ruff` como opinión sobre los ejemplos.

**`myst_substitutions` como reemplazo de los guardias.** Los tres motivos están en 4.1, y el que
decide es que vaciaría los guardias existentes sin cubrir `README.md` ni `AGENTS.md`.

**`sphinx linkcheck`.** Necesita red por definición: el builder recorre los enlaces
**externos**. Hay 29 URL externas distintas en `docs/`, y el job de tests corre con
`egress-policy: block` y siete destinos permitidos, ninguno de ellos las alcanza. Y hay una
razón más fuerte: la prosa nombra `salas.pjud.cl`, así que un `linkcheck` mal acotado haría
justo la petición que la regla 2 regula. Si alguna vez entra, entra con `linkcheck_ignore` para
`pjud.cl` y con su propio guardia.

**`lychee --offline`.** Es la opción técnicamente correcta para validar enlaces locales y anclas
sin red, y la bandera existe. Se descarta por costo, no por capacidad: **no está en PyPI**, es un
binario Rust, o sea queda fuera de `uv` y de `uv.lock` para un repositorio que fija todo lo
demás. Y hay un riesgo específico que nadie documenta: los títulos de este proyecto llevan
tildes y eñes, y el generador de anclas de lychee no tiene por qué coincidir con
`myst_heading_anchors`. Si alguna vez se evalúa, la primera prueba tiene que ser un título
acentuado, porque una discrepancia de slug se ve exactamente igual que "sin hallazgos".

**`--keep-going` junto a `-W`.** Redundante: desde Sphinx 8.1 el build ya no se detiene en el
primer aviso, y en la 9.1 que usa este repositorio la bandera **ya no aparece en `--help`**.
Verificado: `-W` solo reportó los cuatro avisos y salió en 1. Recomendar `-W --keep-going` sería
citar una bandera vieja.

**`mutmut` para verificar los guardias de documentación.** No muta archivos `.md`, y
`paths_to_mutate` es `src/mcp_pjud/`. Sirve por el otro lado y no dice nada sobre si el guardia
sigue enganchado al texto (4.4).

**Validar los ejemplos JSON con `Actuacion.model_validate`.** Falla hoy, y no porque los
ejemplos estén mal: están **recortados a propósito**. Un guardia estricto estaría midiendo el
recorte, no la vigencia. La comprobación de subconjunto de 5.4 es la que corresponde, y está
verificada en rojo.
