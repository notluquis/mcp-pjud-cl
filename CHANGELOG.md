# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado según [SemVer](https://semver.org/lang/es/).

## Sobre el `0.` inicial

La versión mayor es `0`, y eso significa algo concreto: **la API pública puede cambiar sin
aviso entre versiones menores**. No se llegará a `1.0.0` hasta que se cumplan las tres
condiciones de la [hoja de ruta](https://mcp-pjud-cl.readthedocs.io/es/latest/roadmap.html):
más de una competencia verificada, esquema de salida estable, y varios meses sin que un
cambio de la Oficina Judicial Virtual rompa el parser.

Hay una razón adicional para no apurar el `1.0.0`: este software depende del HTML de un
tercero que puede cambiar cualquier día. Prometer estabilidad sería mentir.

## [No publicado]

### Agregado

- El detalle lee tres paneles más: los escritos pendientes y la liquidación de laboral, y las
  causas agregadas de suprema. De ninguno se ha visto una fila en sesenta y una causas, así que
  sus columnas salen del encabezado: `SIN_FILAS_OBSERVADAS` los nombra y la referencia lo
  advierte.

## [0.11.0] - 2026-08-22

### Agregado

- El detalle de una causa laboral trae `diligencias`, con el oficio despachado y el que volvió.
  Que falte el segundo es el dato de que el oficio todavía no vuelve.
- El detalle de una causa de cobranza trae `diligencias`, el panel donde vive de verdad el
  ministro de fe. Su fecha viene **nula** cuando el sitio imprime el epoch `31/12/1969`, que es
  el valor cero y no una diligencia de ese día.
- El detalle de causa trae `escritos_pendientes` en civil: los escritos presentados que el
  tribunal todavía no resuelve, con su fecha de ingreso, quién los presentó y con qué pedir el
  documento y sus anexos. La lista vacía significa que no queda nada por proveer.
- Queda medida la ruta de anexos de un escrito por resolver, `anexoCausaSolEscritoCivil.php`,
  que sólo ese panel ofrece: son cuatro paneles de anexo pedibles.
- El detalle de una causa de la Corte Suprema trae `causa_de_origen`, la causa de la Corte de
  Apelaciones desde la que subió el recurso. La corte llega por su nombre, así que para
  consultarla hay que resolver el código con `listar_cortes`.

### Corregido

- La referencia enumeraba menos paneles de los que el detalle trae, y decía que los escritos no
  están medidos cuando ya se leen. Ahora un guardia la compara contra los campos del modelo.
- Tres nombres reales de personas seguían en las fixtures versionadas, invisibles para los
  cuatro guardias porque venían en mayúscula y minúscula o con un sufijo entre paréntesis. Se
  reemplazaron, y hay un guardia nuevo que mira la COLUMNA en vez de la forma del texto.

## [0.10.0] - 2026-08-22

### Agregado

- `listar_audios_audiencia` dice qué audios de audiencia tiene la causa y con qué enlace se
  bajan. **No trae los archivos**: entrega los enlaces para que la persona los abra.
- El detalle de causa trae `audio_referencia`, que además de servir para pedir el listado dice
  que hubo audiencia grabada. Sólo laboral está medida.
- Queda medido el detalle de las causas penales: se abre por `unificado`, no por la ruta que
  lleva el nombre de la competencia, y ésa responde 200 con los paneles vacíos. La medición y
  sus trampas quedan en la documentación de verificación.
- `obtener_anexos_escrito` trae los documentos que un escrito acompañó, que son un canal
  distinto del de la resolución y hasta ahora no se podían pedir. Tres paneles ofrecidos y
  otros cuatro medidos sin ofrecer, porque su referencia no cuelga de un folio.
- Cada actuación trae `anexo_ruta` y `anexo_referencia`, que es con qué se piden sus anexos.
  Nulas donde el folio no tiene anexo o donde su panel no está medido.

### Decidido

- El detalle de las causas penales **queda fuera de alcance**, después de medirlo y no antes.
  Penal sigue siendo buscable, que es lo que ya estaba; lo que no se expone es el contenido de
  la causa.

### Corregido

- El detalle combinado se anunciaba como "todo lo que la respuesta publica" y deja nueve
  paneles sin leer, distintos en cada competencia. Ahora su contrato dice cuáles, y que los
  anexos y los audios cuestan una petición aparte.
- La hoja de ruta explicaba la falta de penal con un diagnóstico que resultó falso, y no
  nombraba ni los anexos ni los audios.
- `verificacion` nombraba seis de las veinticinco rutas de documento que el servidor acepta.
- Pedir una georreferencia de una competencia que no la ofrece, o sin referencia, levantaba
  `EstructuraInesperada`, que la referencia documenta como "la plataforma cambió, reportar".
  Son errores de la llamada y ahora levantan `ValueError`, como el resto.

## [0.9.0] - 2026-08-22

### Agregado

- Un arnés que rompe cada cifra de la documentación y exige que algún test se caiga. `mutmut`
  muta el código y nada mutaba lo medido, que es lo que este proyecto publica.

### Corregido

- El rechazo de `obtener_actuaciones_receptor` en cobranza explicaba una razón falsa: decía que
  la Historia nunca nombra receptores y los nombra tres veces. Se rechaza igual, y el mensaje
  ahora dice por qué de verdad.
- La referencia decía "las once herramientas MCP" en su descripción publicada, y son doce desde
  la 0.8.0.
- La hoja de ruta presentaba como exacto un producto que no lo es: diez sentencias de 25.473
  caracteres son más de 250.000, no 250.000.
- Dos hooks cierran el ciclo de la revisión: uno la pide a Codex y a Gemini después de cada
  `git push` que llega al remoto, y otro avisa antes de terminar el turno cuando hay hallazgos
  sin mirar. Los dos revisores se disparan al abrir el pull request y nunca en un push.
- Los workflows que corren la suite clonan la historia completa. Sin ella la publicación se
  caía al etiquetar.

## [0.8.0] - 2026-08-21

### Agregado

- Campo `tiene_anexo` en cada actuación y en cada pieza de exhorto: la columna `Anexo` del
  detalle es un segundo canal de documentos del que no se leía ninguna celda. Se declara aunque
  todavía no se pueda pedir, porque un escrito entregaba su PDF y dejaba el anexo sin nombrar.
- Herramienta `obtener_georreferencia`: dónde y cuándo el ministro de fe registró que practicó
  una diligencia. Trae la única hora del proyecto, que es una tercera fuente para contrastar la
  fecha que corre los plazos.
- Campo `no_entregadas` en el resultado de `buscar_jurisprudencia`: cuántas coincidencias
  visibles quedaron fuera porque `filas` acota cuántas se piden. `ocultas` sólo cubre lo que la
  plataforma reserva, y viene en nulo en dos de los tres buscadores.

### Cambiado

- `tiene_documento` ya no se anuncia como "trae documento descargable": con `documento_ruta`
  en nulo la celda abre un modal cuyo endpoint no está medido, así que verdadero no garantiza
  que este servidor pueda traerlo.
- La referencia y la directiva ya no dan a entender que `ocultas` en cero signifique lista
  completa. Una búsqueda de 400 coincidencias con `filas` en 10 devolvía diez sentencias sin
  nada que dijera que había 390 más.
- El bloque de configuración que se pega en el cliente MCP se genera desde un solo lugar: eran
  cuatro copias que sólo diferían en la clave externa.
- Cada página publicada declara de qué trata, y la portada nombra sus dos lecturas en vez de
  hablarle sólo a quien va a computar un plazo.
- La hoja de ruta se partió en tres: lo medido va a `verificacion`, el ecosistema a
  `ecosistema`, y queda un plan de versiones. Los anclajes que publicaba se conservan.

### Corregido

- **`georreferenciado: false` no probaba que la diligencia no se georreferenciara.** En
  suprema significa que la competencia no publica la columna. Quien haya informado una
  ausencia de georreferencia sobre una causa de suprema con 0.7.0 o anterior tiene que
  revisarlo: el art. 9 inc. 3 de la Ley 20.886 la vuelve alegable.
- **`docuN.php` y `docuS.php` estaban al revés.** `docuS.php` es la resolución y `docuN.php`
  el escrito, así que `documento_ruta` nombraba el tipo equivocado.
- `obtener_georreferencia` deja de ofrecerse en `penal`, donde no puede existir una referencia
  que pedir, y distingue "no publica la columna" de "no está medida".

## [0.7.0] - 2026-08-20

### Agregado

- Campos `documento_ruta` y `documento_referencia` en las actuaciones: con qué pedir el
  documento. Antes sólo se decía que existía.
- Herramientas `listar_cortes` y `listar_tribunales`: los códigos que las búsquedas exigen y
  que antes había que saberse de memoria.
- Campos `piezas_exhorto` y `causa_es_exhorto` en el detalle: qué le mandó el tribunal de
  origen a una causa exhortada, y si la causa es un exhorto o no.
- Herramienta `obtener_documento`: el archivo de una actuación. Uno chico viaja entero y uno
  grande como enlace, así que el expediente completo no gasta el contexto de la conversación.
- Un PDF sin capa de texto se declara escaneo y se entrega igual, sin transcribirlo. Uno
  mixto dice cuántas de sus páginas traen texto, porque las otras no se pueden citar.
- Diagramas en la documentación: qué panel publica cada competencia, los tres estados de un
  campo del detalle, la cadena de peticiones y qué activa la detención total.

### Corregido

- El estado de la parte en laboral llegaba siempre nulo: el sitio lo publica como icono y no
  como texto. Ahora viaja la clase del icono, sin interpretar.
- Un panel de materias con encabezados y cero filas se publicaba como lista vacía, que se lee
  como que la causa no litiga nada.

## [0.6.0] - 2026-08-20

### Agregado

- Campo `exhortos` en el detalle de causa civil: qué causas despachó este tribunal a otro, con
  el rol y el tribunal destino donde viven esas actuaciones.

### Cambiado

- La lectura combinada del detalle se ejercitó por primera vez contra la plataforma real. La
  cuenta de peticiones ahora dice si incluye las dos que abren la sesión: son cuatro sin ellas
  y seis con ellas.

## [0.5.1] - 2026-08-20

### Agregado

- La rama `estadisticas` guarda una foto diaria del tráfico, que GitHub retiene sólo catorce
  días, y publica un resumen legible al abrirla.

### Corregido

- Un corte de conexión no activaba la detención total: un cortafuegos que rechaza a nivel de
  red no manda un 403, corta la conexión, y eso llegaba como error de transporte. ([#34])
- El cortafuegos también rechaza con HTTP 200, mandando un desafío de F5 BIG-IP APM en vez de
  la página. Se tomaba por bueno y el fallo aparecía recién en la petición siguiente. ([#34])
- Las estadísticas de tráfico dejaban de contar las descargas pasadas las 30 versiones
  publicadas, porque la consulta no paginaba.

## [0.5.0] - 2026-08-20

### Agregado

- Herramienta `obtener_detalle_causa`: historia, litigantes, notificaciones, liquidaciones y
  materias de una sola cadena de peticiones, recorriendo todos los cuadernos.
- Litigantes en las cinco competencias con detalle mapeado, y materias en laboral. Los
  litigantes traen RUT de personas naturales.
- La liquidación del crédito en cobranza: cuánto se debe y a qué fecha. El monto viene en dos
  campos, uno en pesos para calcular y otro con el texto tal como aparece en el expediente.
- Campo `causa_encontrada`: distingue una causa que no aparece de una competencia que no
  publica ese panel. Antes las dos respondían con todo en nulo.

### Cambiado

- **Se retiran `obtener_historia_causa`, `obtener_notificaciones_causa` y
  `obtener_liquidaciones_causa`**: pasan a ser campos de `obtener_detalle_causa`. Preguntar las
  cuatro cosas de una causa con dos cuadernos costaba dieciséis peticiones y ahora cuesta
  cuatro, más las dos que abren la sesión.
- Un panel que la competencia no publica viaja en nulo y no en lista vacía: "acá no se informa"
  y "no ocurrió" son cosas distintas.

### Corregido

- La portada listaba dos de las ocho herramientas y decía "ambas", así que además de
  incompleta afirmaba que eso era todo.
- Insertar o reordenar una columna en el sitio corría los datos sin que nada avisara. Los
  encabezados ahora se comparan por cantidad y posición.
- `tests/test_resistencia.py`: deforma las fixtures como podría deformarlas la plataforma y
  exige el fallo ruidoso. Dieciocho de sus cuarenta y cinco casos pasaban en silencio.

## [0.4.0] - 2026-08-19

### Agregado

- Herramienta `obtener_notificaciones_causa`: las notificaciones de la causa con sus fechas,
  medida en `civil`, `cobranza` y `laboral`. Incluye las NO practicadas, que se distinguen por
  `estado`: una fila pendiente no hizo correr ningún plazo.
- Cobranza publica la fecha de notificación y la de trámite por separado, y difieren: una carta
  midió tres días. Donde la competencia no la publica, `fecha_notificacion` va nula y no
  copiada de la de trámite.


## [0.3.0] - 2026-08-17

### Agregado

- Herramienta `obtener_historia_causa`: todas las actuaciones de una causa, no sólo las del
  ministro de fe, recorriendo todos los cuadernos. ([#28])
- Detalle de causa en `suprema`, `apelaciones` y `laboral`, con fixture real de cada una. ([#28])
- Campos `estado`, `sala`, `correlativo` y `anio_tramite` en las actuaciones. ([#28])

### Corregido

- En Cortes de Apelaciones se abría la primera causa del listado, que puede ser otra: el mismo
  rol existe en varios libros. Ahora hay que indicar el libro en `tipo` y, si queda ambiguo, se
  levanta en vez de elegir. ([#29])
- El esquema MCP describía `tipo` como "letra del rol", sin mencionar el libro. ([#29])

### Seguridad

- El anonimizador borra las consultas SQL que la plataforma imprime en una celda del detalle de
  Cortes de Apelaciones. ([#28])

## [0.2.1] - 2026-08-17

### Agregado

- Rama `stable`, que apunta a la última versión publicada y es lo que la documentación
  recomienda instalar. Antes la instalación no fijaba referencia y seguía la rama principal.
  ([#26])

### Corregido

- La búsqueda por rol no funcionaba en `suprema`, `apelaciones` ni `penal`: faltaba el campo
  propio de cada una (`conTipoBus`, `conTipoBusApe` y `radio-groupPenal`). ([#26])
- El servidor MCP se presentaba sin versión en `server/discover`. ([#26])
- El User-Agent se identificaba como `mcp-pjud/0.1` ante el Poder Judicial. Ahora sale del
  paquete instalado. ([#26])
- El README y la guía recomendaban fijar `@v0.1.0`, una etiqueta que nunca existió. ([#26])
- Las notas de publicación salían en inglés. Ahora se arman desde este archivo. ([#26])
- Seis datos que se escribían a mano en dos lugares quedan comparados contra su fuente: versión
  de Python, nombre de la variable de entorno, licencia, revisión del protocolo MCP, cuenta de
  buscadores y descripción del servidor. ([#26])

## [0.2.0] - 2026-08-17

Primera versión publicada. La `0.1.0` quedó documentada pero nunca llegó a tener etiqueta, así
que su enlace apuntaba a una publicación que no existía.

### Agregado

- Búsqueda de causas en las seis competencias: se suman `laboral`, `cobranza`, `penal`,
  `suprema` y `apelaciones`. ([#20], [#21], [#24])
- Herramientas `buscar_causa_por_nombre`, `buscar_causa_por_rut_juridica` y
  `buscar_causa_por_fecha`. La segunda es la única vía para empresas. ([#11], [#21])
- Herramientas `buscar_jurisprudencia` y `obtener_texto_sentencia`, sobre el Buscador Unificado
  de Fallos. ([#15], [#21])
- Buscadores de Corte Suprema, Cortes de Apelaciones y Laborales en jurisprudencia. ([#21], [#24])
- Paginación en las cuatro búsquedas. Al exceder el tope levanta excepción en vez de recortar
  la lista en silencio. ([#12])
- Validación de campos antes de consultar, mapeada probando cada combinación contra el sistema
  real. ([#11])
- Con qué acotar cada búsqueda depende de la competencia: `tribunal`, `corte` o nada. ([#24])
- Separación explícita entre saber leer una competencia y haberla verificado. ([#20])
- Acuerdo de contribución ([CLA.md](CLA.md)) redactado contra la Ley 17.336.
- Instalación sin clonar con `uvx --from git+...`, con pestañas por cliente. ([#7], [#8])
- Documentación consumible por agentes: cada página se publica también en Markdown.
- El esquema de cada herramienta se genera desde el servidor al construir la documentación.
- Publicación automática al empujar una etiqueta `v*`, con inventario de dependencias.
- Chequeo de tipos con `ty`, reglas de seguridad y fechas en el linter, y verificación de
  formato en CI.
- Testing de mutación con mutmut, fuzzing con Atheris y pruebas de propiedades con Hypothesis.
- OpenSSF Scorecard, CodeQL con `security-extended`, análisis de los propios workflows con
  zizmor y bloqueo del tráfico saliente en CI. ([#4], [#19])
- Un test impide publicar RUT de personas naturales en el repositorio. ([#17], [#18])

### Cambiado

- El control de ritmo pasa de intervalo plano a balde de fichas: una ráfaga de hasta 4
  peticiones y después una cada 5 segundos. El promedio sostenido no cambia. ([#20])
- La espera máxima de una respuesta sube de 30 a 240 segundos, medida contra el buscador de
  fallos. ([#24])
- Todas las acciones de CI fijadas por SHA de commit en vez de etiqueta.
- Los archivos de comunidad se mueven a `.github/`. ([#8])

### Corregido

- Cobranza prometía actuaciones de ministro de fe leyéndolas de la tabla de Historia, donde no
  están: viven en un panel aparte que este proyecto todavía no lee. ([#22])
- El intervalo entre peticiones se reiniciaba en cada llamada de herramienta, porque el
  contador era del cliente y no del proceso. ([#14])
- La detención tras un bloqueo no alcanzaba a las llamadas en cola. ([#13])
- Las fechas centinela que la plataforma imprime cuando el campo está vacío ya no se devuelven
  como fechas reales. ([#21])
- Una fila del listado con el control de detalle ilegible se saltaba en silencio. ([#13])
- El parser levanta excepción cuando la tabla de Historia trae encabezados y cero filas.
- Un aviso de captcha quedaba clasificado como error de parámetros, o sea reintentable. ([#6])
- Un `assert` acotaba un tipo en código de producción, y bajo `python -O` desaparece. ([#6])
- Las peticiones que mueren por timeout quedan en la bitácora, con estado 0. ([#21])
- El esquema anunciaba al modelo competencias que el cliente rechaza. ([#20])
- Las fixtures traían 87 JWT de la plataforma. ([#9])
- El piso de `mcp` decía `>=1.12` y el código usa `MCPServer`, que existe desde la 2.0.

## [0.1.0] - 2026-08-16

Primera versión. Cubre lo mínimo que justifica el proyecto: exponer las actuaciones del
receptor con la fecha de diligencia correcta.

### Agregado

- Herramienta MCP `obtener_actuaciones_receptor`: actuaciones del ministro de fe con
  `fecha_diligencia` y `fecha_registro` como campos separados, en ISO 8601.
- Herramienta MCP `buscar_causa_por_rit`.
- Recorrido de **todos los cuadernos** de la causa. La interfaz web muestra uno a la vez;
  leer sólo el que viene por defecto omitía el requerimiento de pago y el embargo del
  cuaderno de apremio.
- Campo `discrepancia_fechas`: se reporta cuando las dos fuentes de fecha del sitio no
  coinciden, en vez de elegir una en silencio.
- Campo `georreferenciado`: se expone siempre, también cuando está ausente. Su falta puede
  ser jurídicamente relevante (art. 9 inc. 3 de la Ley 20.886).
- Directiva operativa expuesta por el campo `instructions` del protocolo MCP, para que
  cualquier cliente reciba la distinción entre ambas fechas antes de llamar nada.
- Anotaciones `readOnlyHint` y `destructiveHint=false` en ambas herramientas.
- Intervalo mínimo de 5 segundos entre peticiones, no configurable hacia abajo.
- Detención total ante 403 y 429, sin reintento.
- Fallo ruidoso ante estructura desconocida: excepción, nunca lista vacía.
- Bitácora de peticiones en memoria.
- 39 tests contra HTML real, sin red.

### Decisiones que conviene conocer

- **Sin navegador.** Se midió que el filtro de la plataforma actúa sobre el string del
  User-Agent y no sobre la huella TLS, así que ni Playwright ni impersonación TLS aportan
  nada. HTTP plano con user agent identificable.
- **Fechas en ISO 8601** y no en formato chileno: `06/09/2026` es ambiguo para quien lea la
  salida, y confundir día con mes acá cuesta un plazo.
- **`corte` sin valor por defecto**, porque fijarla produce falsos negativos al excluir
  causas radicadas en otra jurisdicción.
- **Prefijo de rutas y token derivados en caliente** desde el HTML: se verificó que el token
  rota en cada sesión. Hardcodearlo habría roto veinte rutas a la vez.

### Limitaciones conocidas

- Sólo competencia **civil** verificada. Las otras seis se rechazan en vez de adivinar sus
  parámetros.
- Las causas reservadas no aparecen en la consulta pública.
- Sin paginación: se procesa el primer resultado de la búsqueda.

[No publicado]: https://github.com/notluquis/mcp-pjud-cl/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.11.0
[0.10.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.10.0
[0.9.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.9.0
[0.8.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.8.0
[0.7.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.7.0
[0.6.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.6.0
[0.5.1]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.5.1
[0.5.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.5.0
[0.4.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.4.0
[0.3.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.3.0
[0.2.1]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.2.1
[0.2.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.2.0
[0.1.0]: https://github.com/notluquis/mcp-pjud-cl/commit/506b5b7
[#4]: https://github.com/notluquis/mcp-pjud-cl/pull/4
[#6]: https://github.com/notluquis/mcp-pjud-cl/pull/6
[#7]: https://github.com/notluquis/mcp-pjud-cl/pull/7
[#8]: https://github.com/notluquis/mcp-pjud-cl/pull/8
[#9]: https://github.com/notluquis/mcp-pjud-cl/pull/9
[#11]: https://github.com/notluquis/mcp-pjud-cl/pull/11
[#12]: https://github.com/notluquis/mcp-pjud-cl/pull/12
[#13]: https://github.com/notluquis/mcp-pjud-cl/pull/13
[#14]: https://github.com/notluquis/mcp-pjud-cl/pull/14
[#15]: https://github.com/notluquis/mcp-pjud-cl/pull/15
[#17]: https://github.com/notluquis/mcp-pjud-cl/pull/17
[#18]: https://github.com/notluquis/mcp-pjud-cl/pull/18
[#19]: https://github.com/notluquis/mcp-pjud-cl/pull/19
[#20]: https://github.com/notluquis/mcp-pjud-cl/pull/20
[#21]: https://github.com/notluquis/mcp-pjud-cl/pull/21
[#22]: https://github.com/notluquis/mcp-pjud-cl/pull/22
[#24]: https://github.com/notluquis/mcp-pjud-cl/pull/24
[#26]: https://github.com/notluquis/mcp-pjud-cl/pull/26
[#28]: https://github.com/notluquis/mcp-pjud-cl/pull/28
[#29]: https://github.com/notluquis/mcp-pjud-cl/pull/29
[#34]: https://github.com/notluquis/mcp-pjud-cl/issues/34
