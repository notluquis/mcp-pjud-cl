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

- **Rama `stable`, que apunta siempre a la última versión publicada.** La instalación que la
  documentación mostraba no fijaba nada, y `uvx --from git+...` sin referencia toma la rama
  principal: quien la seguía corría cambios sin publicar sin forma de notarlo, porque nada en
  la salida distingue una versión publicada de la rama principal. En una herramienta que se usa
  para computar plazos eso es exactamente al revés de lo que conviene.

  El flujo de publicación la avanza a cada etiqueta, y sólo después de crear la versión sin
  errores: si una publicación falla, `stable` se queda donde estaba y quien instale sigue en la
  anterior, que es la que funciona. Se mueve sin `force`, porque avanzarla es siempre un avance
  y retroceder a la gente en silencio sería peor que fallar.

### Corregido

- **El servidor MCP se presentaba sin versión.** La especificación exige desde la revisión
  2026-07-28 implementar `server/discover`, donde viaja `serverInfo` con nombre y versión, y la
  nuestra iba en su valor por defecto: vacía. Es el mismo descuido que el User-Agent tenía con
  el Poder Judicial, y ahora sale de la misma fuente única. Se declaran además el título y la
  dirección de la documentación, que la misma respuesta publica.

- **Las notas de la publicación salían en inglés.** `--generate-notes` usa una plantilla fija
  de GitHub que imprime "What's Changed" y "by X in Y", sobre un proyecto cuyo idioma es el
  español de Chile. Ahora se arman desde el tramo del CHANGELOG que corresponde a la etiqueta,
  y la lista categorizada que GitHub genera se conserva debajo, con sus dos encabezados
  traducidos. La publicación falla si el CHANGELOG no trae la sección de esa versión, en vez de
  publicar una release con el cuerpo vacío.

- **La búsqueda por rol no funcionaba en `suprema`, `apelaciones` ni `penal`**, que la 0.2.0
  anuncia como verificadas. Suprema y apelaciones respondían "Por favor ingrese sólo números
  para el Tipo de Búsqueda" y penal devolvía un cuerpo sin listado ni aviso: al formulario le
  faltaba el campo propio de cada una (`conTipoBus`, `conTipoBusApe` y `radio-groupPenal`).

  Quien haya fijado `@v0.2.0` tiene esas tres competencias rotas en la búsqueda por rol. Las
  otras tres búsquedas (nombre, RUT y fecha) sí funcionan en las seis.

  Cómo pasó, porque el modo de falla importa más que el campo: se midieron con peticiones
  armadas a mano y los tests usan dobles, así que **nada ejercitó `buscar_por_rit` contra la
  plataforma**. Verificar la petición no es verificar el cliente. Los campos ahora salen de la
  tabla de competencias y hay un test que compara el formulario enviado contra lo que ella
  declara.

## [0.2.0] - 2026-08-17

Primera versión publicada. La `0.1.0` de abajo quedó documentada pero nunca llegó a tener
etiqueta, así que su enlace apuntaba a una publicación que no existía: ahora apunta al commit.

Preparándola aparecieron cuatro copias de la versión escritas a mano, todas atrasadas. La que
importa es el **User-Agent**: cada petición se identificaba ante el Poder Judicial como
`mcp-pjud/0.1`. La regla 2 de este proyecto exige un agente identificable, y esa cadena es lo
único que tiene la institución para saber qué software la consulta. Ahora sale del paquete
instalado. Las otras tres (la instalación fijada del README y de la guía, que apuntaban a una
etiqueta inexistente, y `CITATION.cff`) siguen escritas a mano, con un guardia que las ata.

### Agregado

- Búsqueda de causas en **Corte Suprema** y **Cortes de Apelaciones**, con sus cuatro
  búsquedas cada una. Lo que las bloqueaba no era ningún parámetro exótico: faltaba
  `radio-group`, el radio RIT/RUC del formulario, en el que su PHP se ramifica para saber por
  cuál de los dos se busca. Sin el campo responde HTTP 200 con el cuerpo **vacío**, sin aviso.
  Las otras cuatro competencias lo toleran ausente, así que el hueco no rompía nada de lo que
  estaba expuesto.

  Verificar la búsqueda no verifica el detalle: las dos siguen con `historia=None`, así que
  pedirles actuaciones se rechaza en vez de adivinar el panel.

- Buscador de fallos de **Cortes de Apelaciones**, verificado. Los cuatro intentos anteriores
  se habían dado por muertos por timeout; la consulta responde, y tardó 115,6 s una vez y
  177,0 s otra.

### Corregido

- El esquema MCP quedaba prometiendo lo viejo. `buscar_causa_por_fecha` declaraba `tribunal`
  como parámetro **obligatorio**, así que en suprema y apelaciones la herramienta se anunciaba
  para seis competencias y sólo se podía llamar para cuatro: no había forma de hacer la llamada
  documentada sin inventar un tribunal. Las descripciones de nombre y RUT decían lo mismo. Ahora
  el texto se deriva de `parser.COMPETENCIAS`, viaja en la directiva del servidor, y hay un
  guardia que impide declarar obligatorio un campo que alguna competencia expuesta no usa.

- Una búsqueda **completa** en suprema o apelaciones pedía una página de más y terminaba en
  error. Sus listados ofrecen "siguiente" aunque estén completos, medido sobre sus dos
  respuestas reales (1 de 1 y 3 de 3, las dos con enlace), y `_paginado` sólo cortaba cuando el
  enlace desaparecía. Civil no lo hace, y por eso la condición alcanzaba hasta ahora. Ahora
  manda el total declarado.

- La hoja de ruta se contradecía sobre lo que está verificado: decía que las cuatro búsquedas
  se probaron en vivo y, más abajo, que ninguna de esas rutas se había ejecutado nunca.

- Con qué hay que acotar las búsquedas por nombre, por RUT y por fecha ahora depende de la
  competencia, y sale de una tabla: `tribunal` en las cuatro de primera instancia, `corte` en
  apelaciones, nada en suprema. Antes el cliente exigía tribunal siempre, y con eso habría
  rechazado por su cuenta consultas que la plataforma acepta. Rechazar de más es más difícil
  de notar que rechazar de menos: no gasta una petición, no deja rastro y se ve igual que "no
  hay causas".

- `ESPERA_MAXIMA` sube de 90 a 240 segundos. Tres citas de Corte Suprema fallaban en todas las
  corridas, y esa consistencia se leyó como "esas consultas no terminan". Respondían en 81,2 s,
  102,0 s y 38,7 s: el tope mataba una sola, y con ella se dieron por perdidas las tres. La
  cifra de 47,8 s que justificaba los 90 era una sola muestra, no un techo.

- Búsqueda de causas en **penal**, verificada. Su tipo de causa va como código numérico y no
  como letra ni como palabra: con `conTipoCausa="1"` aparece la causa, y con `"Ordinaria"`,
  `"O"` o vacío el listado vuelve vacío. Exige además `radio-groupPenal` y el código de
  tribunal, que se pide a `combosJSON/leeTrib.php` por POST y en la raíz del sitio.

- Herramienta `buscar_causa_por_fecha`. Existía en el cliente y no estaba expuesta: es la
  cuarta búsqueda que la plataforma ofrece, y sin ella no había forma de responder "qué
  ingresó contra esta empresa esta semana" sabiendo el tribunal pero no el rol.

  Nadie lo había notado porque nada comparaba las dos listas. Ahora hay un test que exige que
  todo método público de consulta del cliente esté expuesto como herramienta o excluido a
  propósito con la razón escrita.

- Herramienta `obtener_texto_sentencia`: el texto completo de un fallo, de a uno por llamada.

  Está separada de la búsqueda por una razón medida: una sentencia de trece páginas son 25.473
  caracteres, así que devolver diez con cada búsqueda serían 250.000. La búsqueda entrega
  `texto_preview` y la extensión en palabras y páginas, que suele bastar para decidir.

  Declara `anonimizada` y `fuente`: si lo entregado es la versión con los datos de las personas
  naturales suprimidos por el propio tribunal, y de cuál de los dos campos del buscador salió.
  Y si la sentencia existe pero está reservada para consultas anónimas, levanta en vez de
  devolver un texto vacío que se leería como una sentencia sin contenido.

- Buscadores de **Corte de Apelaciones** y **Laborales** en el buscador de fallos, con sus
  campos leídos de `parametros_buscador`. Confirman la premisa de la tabla: Apelaciones
  identifica sus sentencias con `rol_era_ape_s` donde Suprema usa `rol_era_sup_s`. En Laborales
  el origen es un juzgado y no una corte.

- Búsquedas en **laboral** y **cobranza**, verificadas contra el sistema real y con fixtures
  propias. Cobranza publica RUC, que civil no tiene; laboral publica estado de causa.

  Las seis competencias comparten formulario, nombres de campo y una ruta regular: lo único
  que difiere es qué columnas trae el listado. Por eso hay una tabla de datos
  (`parser.COMPETENCIAS`) y no seis parsers, y `parse_resultados` y `parse_historia` reciben la
  competencia. Duplicar el recorrido de filas para cambiar dos índices es la forma más segura
  de que uno de los seis se quede atrás cuando la plataforma cambie.

  Las otras tres se midieron y quedaron fuera con su error anotado: `penal` devuelve un
  listado que el parser no reconoce, y `apelaciones` y `suprema` piden un código numérico de
  libro donde las demás llevan letra.

  Queda declarado en la tabla que en todo el sitio sólo existen `receptorCivil` y
  `receptorCobranza`: en las otras cuatro competencias la pregunta que da sentido a este
  proyecto no tiene respuesta, y pedir actuaciones ahí se rechaza antes de gastar una
  petición en vez de descubrirlo con una lista vacía.

- Separación explícita entre saber leer una competencia y haberla verificado.
  `parser.COMPETENCIAS` sabe leer las seis; `client.MODULOS` dice cuáles se midieron.
  Confundirlas es adivinar, y el cliente ahora da dos errores distintos.

- Herramienta `buscar_jurisprudencia`: sentencias de la Corte Suprema desde el Buscador
  Unificado de Fallos. Sirve para verificar que una cita existe antes de usarla.

  Su resultado declara **`ocultas`**, que es cuántas coincidencias existen y no se entregan a
  una consulta anónima. Medido el 16 de agosto de 2026, sin filtros: 300.005 visibles de
  1.223.925 coincidencias declaradas. El propio sitio dejó de avisarlo (los dos mensajes siguen comentados en su JavaScript), y un listado
  que no diga cuánto falta se lee como el universo completo.

  Sólo el buscador de Corte Suprema está verificado: cada uno de los otros nueve declara sus
  propios campos.

- Chequeo de tipos con `ty` y verificación de formato en CI. El primero encontró que tres de
  las cuatro búsquedas declaraban aceptar `paginas=None` y reventaban con `TypeError`, porque
  sólo la búsqueda por rol implementaba esa rama.

- Reglas `S` (seguridad) y `DTZ` (fechas sin zona horaria) en el linter. La segunda importa
  acá: las fechas deciden plazos procesales.

- El esquema de cada herramienta se genera desde el servidor al construir la documentación,
  así que la referencia publicada es literalmente lo que un cliente MCP recibe por el
  protocolo. No se escribe a mano y no puede quedar vieja.

- Pestañas por cliente en la guía de instalación: Claude Code, Claude Desktop, Cursor, VS Code
  y Codex. Cada uno quiere un formato distinto y hay una trampa real: VS Code usa la clave
  `servers` y el resto `mcpServers`, así que copiar el bloque equivocado no funciona. Los dos
  formatos que faltaban se verificaron contra la documentación de cada herramienta.

- Un test impide publicar RUT de personas naturales en la documentación. El guardia anterior
  sólo miraba las fixtures, y la documentación es igual de pública: un RUT ahí es un
  identificador vivo, y quien lo copie saca las causas de esa persona. Los RUT de empresas sí
  se permiten, declarados uno por uno, porque la Ley 21.719 protege a las personas naturales y
  un ejemplo que corre de verdad vale más que uno inventado.

- Paginación en las cuatro búsquedas. La plataforma pagina por identificador opaco y no por
  número, con 100 resultados por página. Hay un tope de 10 páginas que levanta excepción en
  vez de devolver la lista recortada, porque un listado truncado en silencio se leería como
  "no hay más".

- Herramientas `buscar_causa_por_nombre` y `buscar_causa_por_rut_juridica`. La segunda es la
  única vía para empresas, que no tienen Clave Única y por lo tanto no aparecen en
  "Mis Causas".
- Validación de campos antes de consultar, mapeada probando cada combinación contra el
  sistema real. La plataforma no responde con código de error cuando faltan campos: devuelve
  HTTP 200 con un aviso dentro de un `<script>`. Ahora eso se detecta y se levanta
  `PlataformaRechaza` en vez de llegar al usuario disfrazado de resultado.

- Acuerdo de contribución ([CLA.md](CLA.md)) redactado contra la Ley 17.336: los pull requests
  quedan abiertos sin exigir cesión de derechos ni renuncia a derechos morales.
- Financiamiento, con la aclaración de que donar no otorga licencia comercial.
- Análisis estático de los propios workflows con zizmor, y auditoría del tráfico saliente del
  runner con harden-runner. Esto último deja verificable la promesa de que CI nunca consulta al
  Poder Judicial.
- Testing de mutación con mutmut, mensual y a pedido.
- El parser levanta excepción cuando la tabla de Historia trae encabezados y cero filas.
  Esa forma la produce una respuesta truncada, y antes devolvía una lista vacía que se
  leería como que la causa no tiene actuaciones. Lo destapó Hypothesis.
- Harness de fuzzing con Atheris en `tests/fuzz_parser.py`, con el mismo oráculo que la
  invariante central. No corre en CI; se ejecuta a mano al tocar el parser.
- Pruebas basadas en propiedades con Hypothesis sobre el parser de fechas. La invariante
  central es que nunca devuelva una fecha que no venga en la entrada: una fecha de diligencia
  inventada se computa como plazo, y eso es peor que no devolver ninguna.
- OpenSSF Scorecard y revisión de dependencias en pull requests.
- CodeQL por workflow con `security-extended`. Pasó por dos estados en este ciclo: primero se
  quitó el workflow porque chocaba con el modo gestionado que estaba activo, y después se
  restituyó tras deshabilitar ese modo. Queda una dependencia de configuración fuera del
  repositorio: si alguien reactiva el modo gestionado, el workflow falla.
- Período de enfriamiento en Dependabot: una versión recién publicada ya no llega como pull
  request el mismo día, que es la ventana que aprovechan los ataques de cadena de suministro.
- Publicación automática al empujar una etiqueta `v*`, con notas generadas e inventario de
  dependencias adjunto.
- `AGENTS.md` con las reglas del proyecto para agentes de IA, más `CLAUDE.md` que lo importa y
  `copilot-instructions.md` que lo referencia. Una sola fuente en vez de tres que se
  desincronizan.
- Documentación consumible por agentes: cada página se publica también en Markdown
  (`uso.html.md`, etc.), más `llms.txt` y `llms-full.txt`, vía la extensión `sphinx-llm`.
- Página de ejemplos con casos resueltos de punta a punta.
- Badges de CodeQL, OpenSSF Scorecard y source-available en el README.
- `GEMINI.md`, para la única herramienta además de Claude Code que todavía no lee `AGENTS.md`.
- Instalación sin clonar, con `uvx --from git+...`. Verificado levantando el servidor y
  listando sus herramientas por stdio. Habilita el comando de una línea para Claude Code y
  los botones de un clic para Cursor y VS Code.
- Cuatro tests nacidos de mutantes que sobrevivieron: el respaldo cuando `Fec. Trámite` viene
  sin paréntesis y la fecha sale de la descripción, la detección de documento adjunto, y la
  hora inválida. Con las de propiedades, la suite queda en 50 tests.

### Cambiado

- El control de ritmo pasa de un intervalo plano a un balde de fichas: hasta 4 peticiones
  seguidas y después una cada 5 segundos. El régimen sostenido no cambia; lo que cambia es
  que una consulta de actuaciones, que son cinco peticiones encadenadas para responder una
  sola pregunta, baja de 25 segundos a 5.

  Hay que decir qué se cambió, porque contradice una decisión anterior de este mismo
  proyecto: se habían descartado las librerías de control de ritmo justo por implementar un
  balde que permite ráfagas. Lo que cambió no es la opinión sobre la librería sino la
  especificación. Antes era "al menos 5 segundos entre peticiones consecutivas"; ahora es "a
  lo más una cada 5 segundos en régimen, con ráfaga acotada a 4". La sobrecarga que la
  cláusula CUARTA prohíbe es una propiedad del régimen, no de dos peticiones sueltas.

  El tope de la ráfaga es lo único que separa esto de no tener control, así que tiene su
  propio guardia: un test que lo acota a la cadena más larga que hace el cliente, y un job de
  CI que verifica las dos constantes. Los tests de ritmo dimensionan sus bucles con la
  constante, o sea crecen con ella y no pueden detectar que crezca: ese piso lo pone el test
  del tope y nada más.

- Todas las acciones de CI fijadas por SHA de commit en vez de etiqueta. Una etiqueta se puede
  mover; un SHA no. En `setup-uv` además dejó de ser opcional: desde su v8 no publican
  etiquetas de versión mayor.
- `permissions: {}` por defecto en los workflows, con permisos por job.
- `persist-credentials: false` en los checkout, que no hacen push.


- La nota sobre el hallazgo `Fuzzing` de Scorecard estaba mal fundada. Su documentación sí
  acepta pruebas basadas en propiedades como fuzzing válido; lo que falta es que su detector
  incluya Hypothesis, que es el equivalente en Python.
- `main` exige pull request. Los commits directos quedan cerrados.
- Las guías dejan de nombrarse por cargo ("para abogados", "para el área de informática") y
  pasan a nombrarse por tarea: uso e interpretación, e instalación y operación.
- Los archivos de comunidad se mueven a `.github/`. En la raíz quedan los operativos: los que
  alguien tiene que poder encontrar sin pasar por el sitio de documentación.

### Corregido

- Las fechas que la plataforma imprime cuando el campo está vacío ya no se devuelven como
  fechas. Medido en `diligenciaCob`: una diligencia de embargo cumplida traía `31/12/1969`, que
  es el epoch de Unix visto desde una zona al oeste de Greenwich, o sea el valor cero
  renderizado.

  Devolverla habría sido peor que devolver nulo, porque alguien computaría un plazo desde 1969.
  Es el error que este proyecto existe para no cometer con el signo invertido: no falta un dato,
  sobra uno que tiene forma de dato.

- Cobranza prometía actuaciones de ministro de fe leyéndolas de la tabla de Historia, y ahí no
  están. Medido sobre una respuesta real: sus trámites son `Actuación`, `Resolución` y
  `Escrito`, nunca "Actuación Receptor", y las diligencias viven en `diligenciaCob` con
  estructura propia. La palabra "receptor" aparece en esa respuesta, o sea existen.

  El efecto era devolver una lista vacía mientras las diligencias estaban en el panel de al
  lado: "no hubo actuaciones" cuando lo cierto era "no las estoy leyendo". Es el falso negativo
  que este proyecto existe para evitar, y estuvo brevemente dentro de él. Ahora la llamada se
  rechaza con esa explicación.

- `ocultas` no significaba lo mismo en todos los buscadores, y se informaba igual. Medido: en
  `suprema` el número que la plataforma entrega cuenta la consulta (2 y 2 para un rol que
  existe, 0 y 0 para uno imposible); en `laborales` cuenta el índice completo, 269.264 en los
  dos casos.

  O sea una búsqueda laboral con 8 resultados reportaba 269.256 ocultas, que hacía ver cada
  resultado como una fracción de un universo oculto que no existe. Ahora `ocultas` y
  `coincidencias` vienen en nulo donde no está medido que cuenten la consulta, y queda dicho
  que **nulo no es cero**: es "acá no se puede saber". Un campo que miente es peor que un campo
  ausente, y éste era el campo del que dependían las conclusiones más fuertes.

- Las peticiones que mueren por timeout ahora quedan en la bitácora, con estado 0. Una
  petición sin respuesta igual salió a la red, y sin registrarla el registro subestimaba el
  tráfico generado justo en las corridas donde la plataforma iba peor, que son las que uno
  querría poder explicar.

- `actuaciones_receptor` no reenviaba la competencia al parser, así que la historia se leía
  siempre con el panel de civil y el guardia que lo protege era inalcanzable. Medido con
  coverage: nunca se ejecutaba.

- El esquema de las herramientas le anunciaba al modelo las seis competencias, incluidas las
  tres que el cliente rechaza. El modelo las intentaba, recibía un error y podía atribuirlo a
  la plataforma. Hay un guardia nuevo que compara el esquema contra lo verificado, porque el
  que existía cubría la documentación y dejaba fuera el esquema, que es lo que el modelo lee
  primero.

- Una fila del listado con el control de detalle ilegible se saltaba en silencio. Perder una
  causa dentro de un listado que devuelve las demás es peor que no devolver nada: la lista
  parece completa.

- Las pruebas de propiedades corren sin plazo por ejemplo. El de 200 ms que Hypothesis trae
  por defecto mide el reloj de la máquina y no la propiedad: en una corrida con la máquina
  cargada un ejemplo lo excedió, se reportó como propiedad falsificada, y el caso guardado
  pasaba al reproducirlo. Un test que falla según la carga enseña a desconfiar de la suite,
  que es peor que no tenerlo.

- La espera máxima de una respuesta sube de 30 a 90 segundos. Medido: una búsqueda del
  buscador de fallos por rol y año tardó 47,8 segundos en el primer byte, contra 4,3 de la
  página del mismo host. Con 30 segundos, cuatro de cada cinco búsquedas morían por timeout y
  eso se leía como que la plataforma estaba caída.

- El intervalo entre peticiones se reiniciaba solo. `server.py` abre un cliente nuevo en cada
  llamada de herramienta y la marca de tiempo vivía en la instancia, así que la primera
  petición de cada herramienta salía sin esperar: dos herramientas seguidas golpeaban el
  portal sin intervalo alguno. La marca pasa a ser del proceso, bajo un lock que cubre toda la
  petición.

- La detención tras un bloqueo no alcanzaba a las llamadas en cola. El turno se soltaba antes
  de clasificar la respuesta, así que una segunda llamada concurrente esperaba sus cinco
  segundos y consultaba igual cuando la primera ya había recibido el 403. Era reintentar por
  la puerta de al lado.

- La detención sigue siendo del proceso entero, y ahora está medido por qué. Se evaluó
  llevarla por host, para que un bloqueo consultando jurisprudencia no dejara sin consulta de
  causas a quien tiene un plazo corriendo. Se descartó al mirar quién bloquea: los dos hosts
  responden con la cookie `TS<hex>` de F5 BIG-IP, o sea están detrás del mismo cortafuegos y
  el 403 llega antes de la aplicación. Seguir consultando el otro es lo que convierte un
  bloqueo temporal en una IP baneada.

- Un `assert` acotaba un tipo en código de producción. Bajo `python -O` los `assert`
  desaparecen, y ése protegía justo el caso en que se consultarían rutas sin prefijo, que
  devuelven vacío en vez de fallar.

- Un aviso de captcha de la plataforma quedaba clasificado como error de parámetros, o sea
  invitaba a reintentar, que es justo lo que la regla de detención total prohíbe. Ahora se
  distingue y levanta `PjudBloqueado`.

- Las fixtures traían 87 JWT de la plataforma. Caducan a los 30 minutos y no sirven de
  credencial, pero su carga va cifrada y probablemente codifica identificadores de la misma
  causa cuyos nombres y RUT ya se habían anonimizado, así que dejarlos era incoherente.
  Reemplazados por referencias ficticias, con un test que impide reintroducirlos.
- La nota sobre el pin de `github/codeql-action` atribuía mal la causa. `codeql-bundle-v2.26.3`
  sí apunta a ese SHA, pero ese commit **es** de la acción, de época v4; el tag `v2.26.3` de la
  acción apunta a otro. El defecto era un comentario de versión que no correspondía al SHA.
- Las dependencias de documentación estaban en dos listas, un grupo de `uv` y un
  `requirements.txt`, y se desincronizaron: el build de Read the Docs falló por una extensión
  que estaba en una y no en la otra. Ahora van como extra `docs`, que pip y uv leen igual.
- El pin de `github/codeql-action` apuntaba a la release del bundle de CodeQL y no a la
  versión de la acción, así que el comentario de versión decía algo que ese SHA no era.
- El piso de `mcp` decía `>=1.12`, pero el código usa `MCPServer`, que existe desde la 2.0. Con
  una 1.x el servidor no arrancaba.

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

[No publicado]: https://github.com/notluquis/mcp-pjud-cl/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.2.0
[0.1.0]: https://github.com/notluquis/mcp-pjud-cl/commit/506b5b7
