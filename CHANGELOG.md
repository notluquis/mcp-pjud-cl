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

- Acuerdo de contribución ([CLA.md](CLA.md)) redactado contra la Ley 17.336: los pull requests
  quedan abiertos sin exigir cesión de derechos ni renuncia a derechos morales.
- Financiamiento, con la aclaración de que donar no otorga licencia comercial.
- Análisis estático de los propios workflows con zizmor, y auditoría del tráfico saliente del
  runner con harden-runner. Esto último deja verificable la promesa de que CI nunca consulta al
  Poder Judicial.
- Testing de mutación con mutmut, mensual y a pedido.
- Cuatro tests nacidos de mutantes que sobrevivieron: el respaldo cuando `Fec. Trámite` viene
  sin paréntesis y la fecha sale de la descripción, la detección de documento adjunto, y la
  hora inválida.

### Cambiado

- Todas las acciones de CI fijadas por SHA de commit en vez de etiqueta. Una etiqueta se puede
  mover; un SHA no. En `setup-uv` además dejó de ser opcional: desde su v8 no publican
  etiquetas de versión mayor.
- `permissions: {}` por defecto en los workflows, con permisos por job.
- `persist-credentials: false` en los checkout, que no hacen push.

### Corregido

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
