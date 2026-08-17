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

[No publicado]: https://github.com/notluquis/mcp-pjud-cl/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/notluquis/mcp-pjud-cl/releases/tag/v0.1.0
