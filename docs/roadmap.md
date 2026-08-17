# Hoja de ruta y estado de verificación

## Qué está verificado y qué no

Esta tabla es lo más importante de la página. Distingue tres cosas que suelen confundirse:
lo que se probó **contra el sistema real**, lo que sólo se probó **contra fixtures**, y lo que
está **mapeado en el código de la plataforma pero nunca ejecutado**.

### Verificado contra el sistema real

| Qué | Cómo se verificó |
|---|---|
| Entrada pública sin Clave Única | `sesion-consultaunificada.php` → 200 |
| Derivación de prefijo de rutas y token | Tres sesiones distintas, token distinto en cada una |
| Búsqueda por RIT en civil | E-468-2026 y C-1156-2026 |
| Detalle de causa | Ambas causas |
| Cuadernos múltiples | C-1156-2026: principal + apremio |
| Actuaciones de receptor con fecha doble | 8 actuaciones en E-468-2026, 6 en C-1156-2026 |
| Los cuatro tipos de diligencia documentados | Presentes en E-468-2026 |
| Georreferencia presente | Todas las actuaciones de ambas causas |
| El filtro de la plataforma es por User-Agent y no por huella TLS | Tres clientes, mismo handshake, distinto header |
| Búsqueda de jurisprudencia en Corte Suprema | `buscar_sentencias` respondió 200 con JSON de Solr |
| Verificación de una cita por rol y año | Rol y año existentes → exactamente una sentencia, con sala, fecha y enlace |
| El buscador de fallos entrega menos de lo que indexa | 300.005 visibles de 1.223.925, medido sin filtros |
| Su reCAPTCHA no bloquea la búsqueda | Sesión anónima sin token → 200 con resultados reales |
| El tope real de filas por página es 250 | Se pidieron 250 y entregó 250, pese a que su configuración declara `10-20-50` |

### Verificado sólo contra fixtures

Funciona sobre HTML real guardado, pero **nunca se ejercitó contra el sistema en vivo**:

| Qué | Riesgo |
|---|---|
| Discrepancia entre las dos fuentes de fecha | Nunca se vio un caso real de discrepancia. La rama existe y está testeada con HTML sintético, pero no hay evidencia de cómo se ve en la práctica |
| Georreferencia ausente | Todas las actuaciones observadas la traen. No se sabe cómo se ve la celda cuando falta |
| Fecha imposible (31/02) | Defensa preventiva, nunca observada |
| Mensaje de "sin resultados" | Se copió de una respuesta real, pero el camino completo no se ejercitó |

### Mapeado pero nunca ejecutado

Las rutas se extrajeron del código de la plataforma. **No se probó ninguna.** El cliente las
rechaza en vez de adivinar sus parámetros:

- `consultaNombre*.php`, `consultaJuridica*.php`, `consultaFecha*.php` para todas las
  competencias
- Todo lo de `apelaciones`, `suprema`, `laboral`, `penal`, `cobranza`, `familia`
- `detalleExhortos.php`, `causaOrigenCivil.php`, `geoReferenciaCivil.php`
- `anexoCausaCivil.php` y la descarga de documentos por `docuN.php`
- `receptorCivil.php`, que devuelve la tabla de **retiro** de documentos, no la de
  actuaciones. Se ejecutó una vez y se descartó por no ser lo que se buscaba

### Sin cubrir del todo

- **Causas reservadas.** No aparecen y no aparecerán.
- **Expiración de referencias.** Caducan a los 30 minutos. El flujo cabe holgado, pero no hay
  manejo explícito de expiración a mitad de cadena.

## Versionado

[SemVer](https://semver.org/lang/es/). La versión mayor es `0`, y eso significa que **la API
pública puede cambiar sin aviso entre versiones menores**.

Hay una razón adicional para no apurar el `1.0.0`: este software depende del HTML de un
tercero que puede cambiar cualquier día. Prometer estabilidad de interfaz sería prometer algo
que no controlamos.

### Condiciones para llegar a 1.0.0

Las tres, no dos de tres:

1. **Más de una competencia verificada** contra el sistema real, con fixtures propias.
2. **Esquema de salida estable**, sin cambios de campos por al menos dos versiones menores.
3. **Seis meses sin que un cambio de la plataforma rompa el parser**, o con al menos un cambio
   detectado y corregido dentro de la semana.

## Hoja de ruta

### 0.2: paginación y varias causas — hecho

Los controles de paginación se parsean, el listado se recorre entero y existen las búsquedas
por nombre y por RUT de persona jurídica. El recorrido levanta `ResultadosTruncados` al llegar
al tope en vez de devolver una lista recortada.

Quedó decidido lo que estaba en duda: **no se encadenan las actuaciones de todas las causas de
un listado**. Doce causas por cinco peticiones por cinco segundos son cinco minutos, y la
respuesta correcta es devolver el listado para que el usuario elija cuál abrir.

### 0.3: jurisprudencia — hecho parcialmente

Existe `buscar_jurisprudencia` contra el buscador de Corte Suprema. Lo que falta está en la
sección de jurisprudencia, más abajo.

### 0.4: cobranza laboral y previsional

La primera competencia nueva, y la elegida a propósito: `receptorCobranza.php` existe, o sea
que también tiene actuaciones de ministro de fe, que es donde está el valor.

- Verificar si el formato de fecha doble es el mismo
- Parser propio si difiere
- Ampliar `MODULOS` sólo después de verificar, nunca antes

### 0.5: exhortos y documentos

- `detalleExhortos.php`: seguimiento de exhorto de origen a destino
- `causaOrigenCivil.php`
- Descarga de documentos por folio vía `docuN.php`

**Decisión pendiente y no trivial:** descargar un PDF significa traer datos de terceros a
disco. Eso cambia el perfil de retención y entra de lleno en la Ley 21.719. Probablemente
requiera consentimiento explícito por llamada, y ruta de destino elegida por el usuario.

### 0.6: laboral y apelaciones

Las dos competencias que siguen en volumen de uso real.

### 0.7: competencias restantes

Laboral, apelaciones, suprema, penal y familia. Ninguna sondeada. Antes de cada una hay que
confirmar lo mismo que se confirmó en cobranza: el identificador del panel de historia, el
orden y nombre de las columnas, y si esa competencia expone actuaciones de ministro de fe.

Sin esto último, la competencia no vale el esfuerzo por más que sus rutas estén mapeadas.

### Sin versión asignada

**Detección de cambios entre consultas.** Avisar cuando aparece una actuación nueva. Sigue
siendo solo lectura, pero **implica persistencia**, y eso cambia todo el perfil de datos
personales. No se toca hasta que las fases anteriores estén estables y haya una respuesta
clara sobre retención bajo la Ley 21.719.

**Búsqueda de cartera por identificador de abogado.** El campo `Institución` de los listados
permite reconstruir la cartera completa de un abogado. Técnicamente es directo.
**Deliberadamente en duda**: construir perfiles de personas está en la lista de usos que el
proyecto rechaza, aunque el dato sea público. Si se implementa, será con un caso de uso
justificado y no "porque se puede".

**Jurisprudencia de otros buscadores.** Ver la sección propia más abajo: de los diez
buscadores que ofrece `juris.pjud.cl` sólo Corte Suprema está verificado, y cada uno declara
sus propios campos.

## Jurisprudencia: qué hay mapeado y qué falta

El Buscador Unificado de Fallos no es una aplicación de una sola página como se creyó al
principio: es PHP con Laravel y componentes Vue encima, y su búsqueda devuelve JSON de Apache
Solr. Eso lo hace bastante más fácil de consumir que la consulta de causas, que entrega HTML.

### Los diez buscadores

Sólo el primero está verificado. **Cada buscador declara sus propios campos**, y esa es la
razón técnica de no exponer los otros todavía: Corte Suprema entrega `rol_era_sup_s`, mientras
Apelaciones usaría `rol_era_ape_s`. Un cliente que asuma los campos de Suprema devolvería
campos vacíos en vez de un error, que es exactamente el falso negativo que el proyecto evita.

| Buscador | Estado |
|---|---|
| Corte Suprema | **Verificado.** `id_buscador` 528 |
| Corte de Apelaciones | Mapeado, sin ejecutar |
| Civiles | Mapeado, sin ejecutar |
| Laborales | Mapeado, sin ejecutar |
| Penales | Mapeado, sin ejecutar |
| Familia | Mapeado, sin ejecutar |
| Cobranza | Mapeado, sin ejecutar |
| Compendio Extranjería | Mapeado, sin ejecutar |
| Líneas Jurisprudenciales | Mapeado, sin ejecutar |
| Salud CS | Mapeado, sin ejecutar |

El identificador de cada buscador se deriva de su propia página, no se hardcodea. Verificar uno
nuevo es sobre todo comprobar qué campos declara su `parametros_buscador`.

### Endpoints del buscador, mapeados y sin ejecutar

| Ruta | Qué haría |
|---|---|
| `/busqueda/documentos` | Descargar el documento de la sentencia |
| `/busqueda/imprimir` | Versión imprimible |
| `/busqueda/arbol_json` | Índice temático: materias y submaterias |
| `/busqueda/listar_ids_relacionados` | Sentencias relacionadas con una dada |
| `/busqueda/get_suggester_results` | Sugerencias de términos |
| `/busqueda/busqueda_por_texto_autocompletable` | Autocompletado |
| `/busqueda/listar_georeferencia` | Georreferencia de la sentencia |
| `/detalle_sentencia/terminos_juridicos` | Glosario de términos |

Tres rutas más existen y **no se van a implementar**: `sentencias_guardadas` y `cambiar_clave`
escriben en una cuenta de usuario, y `mail_compartir_sentencia` envía correo desde la
infraestructura del Poder Judicial. Que el buscador sea de lectura no las vuelve inofensivas, y
el job de CI que verifica que no exista código de escritura busca esos tres nombres.

### Lo que el buscador no muestra, y que es el hallazgo que importa

Una consulta anónima recibe bastante menos de lo que hay indexado. Medido el 16 de agosto de
2026 sobre Corte Suprema, sin filtros:

| | |
|---|---|
| Visibles para una consulta anónima | 300.005 |
| Coincidencias que declara, antes de su filtro de publicación | 1.223.925 |

La propia respuesta desglosa **todas** las coincidencias por condición de publicación
(`Excluido salud` 829.079, `Publicable` 232.021, `Anonimizadas` 20.924, `Reservado
restringido` 6.677, entre otras), y ese desglose suma el total, no la diferencia. O sea
incluye a las visibles: no dice cuáles faltan, porque el buscador no publica su regla de
visibilidad.

Lo notable es que **el sitio dejó de decirlo**. Los dos mensajes que avisaban de esa diferencia
siguen en su JavaScript, comentados: uno agregaba "sentencias ocultas por limitaciones de
visualización del perfil de usuario" y el otro decía "sus permisos de usuario no permiten la
visualización de esta(s) sentencia(s)".

Esa segunda cifra no es el tamaño del índice: el Poder Judicial habla públicamente de más de
un millón y medio de sentencias, y la diferencia no está explicada. Se registra como lo que
es, una cifra medida en una respuesta, y no como el universo.

Por eso `buscar_jurisprudencia` no devuelve una lista pelada sino un resultado con `ocultas` y
`condiciones_de_publicacion` como campos. Un listado que no diga cuánto falta se lee como el universo
completo, que es el mismo defecto que el ebook de la Oficina Judicial Virtual y la razón de ser
del proyecto entero.

### Lo que falta decidir

- **Texto completo.** La respuesta trae `texto_sentencia` entero, y una búsqueda de diez
  sentencias serían megabytes con nombres y cédulas de personas naturales. Hoy se devuelve
  metadatos y el enlace permanente. Traer el texto es una decisión de datos personales, no de
  comodidad, y va junto con la de descargar PDF.
- **Paginación.** El buscador pagina por desplazamiento numérico, no por identificador opaco
  como la consulta de causas, así que es más simple. Falta el mismo guardia de truncación.
- **Una cuenta.** Con credenciales del Poder Judicial se verían más sentencias. Queda fuera:
  este proyecto consulta lo que es público sin identificarse como funcionario.

## Sobre los identificadores de causa en esta documentación

Las fixtures van anonimizadas: sin nombres, sin RUT, sin los identificadores opacos de la
plataforma. Pero **los roles de causa que aparecen en los ejemplos siguen siendo
identificadores directos**: con un rol y un tribunal, una sola consulta devuelve el nombre
completo de las partes.

O sea la anonimización de las fixtures se deshace si se publica el rol al que corresponden.

Criterio adoptado:

- Los roles del caso propio del autor se conservan, porque el ejemplo trabajado es lo que hace
  entendible el proyecto y la decisión es suya.
- **Los roles de causas de terceros no se publican.** Una causa que aparece sólo porque se
  eligió para un sondeo no debe arrastrar a sus partes a un repositorio indexado.

Vale también para quien reporte un problema: la plantilla de issue pide el rol, y eso es
deliberado porque sin él no se puede reproducir. Quien reporte decide si su causa lo admite.

## Herramientas de descubrimiento que no existen

Verificado el 17 de agosto de 2026, en los dos hosts:

| Ruta | `oficinajudicialvirtual.pjud.cl` | `www.pjud.cl` |
|---|---|---|
| `/sitemap.xml` | 404 | 404 |
| `/.well-known/security.txt` | 404 | 500 |
| `/robots.txt` | `Disallow: /` | 404, no publica |

No hay sitemap, así que el mapeo de endpoints se hizo leyendo el JavaScript de
`consultaUnificada.php`, que es donde el sitio declara sus 169 rutas. Ese es el método a
repetir cuando la plataforma cambie.

La ausencia de `security.txt` refuerza lo que ya dice la política de seguridad: no hay canal
publicado de divulgación de vulnerabilidades, así que va directo a la Corporación
Administrativa.

## Reglas de la plataforma ya mapeadas

Medidas probando combinaciones contra el sistema real. Se registran acá porque son la clase de
dato que se re-descubre a costa de peticiones si no queda escrito.

| Búsqueda | Obligatorio | Opcional | Aviso al faltar |
|---|---|---|---|
| Por rol | número, año | tipo, corte, tribunal | `Por favor ingresar Rol / Año para la búsqueda` |
| Por nombre | dos campos **de nombre**, tribunal | año, corte | `Por favor llene mínimo 2 campos` / `seleccione un Tribunal` |
| Por RUT jurídica | dígito verificador, tribunal | año, corte | `Por favor ingrese dígito verificador` |
| Por fecha | rango completo, tribunal | corte | `Por favor ingrese una Fecha Final` |

Dos cosas contraintuitivas:

- **Omitir el tribunal amplía los resultados.** La misma consulta por rol devolvió dos causas
  sin tribunal y una con él. Acotar de más esconde causas, que es el falso negativo que este
  proyecto existe para evitar.
- **El año no cuenta** para el mínimo de dos campos en la búsqueda por nombre.

Y una limitación de fondo: la búsqueda por nombre **exige tribunal**, así que no sirve para el
caso "sé el nombre pero no dónde está la causa", que era el que se suponía que resolvía.

## Lo que se va a romper

No es pesimismo, es planificación:

- **La plataforma va a cambiar.** El prefijo de rutas y el token ya se derivan en caliente por
  esto. Cuando cambie la estructura de tablas, el parser falla ruidosamente y hay que
  arreglarlo.
- **Pueden activar la validación del captcha.** Hoy la consulta funciona sin ella. Si se
  activa, la cadena se cae entera y no se va a evadir: el proyecto se detiene y se busca la
  vía institucional.

  Esto no es una hipótesis. Tras el colapso de julio de 2026, el Comité de Jueces Civiles
  pidió a la Corte Suprema, por escrito, "medidas tecnológicas adecuadas y urgentes para
  evitar el ingreso masivo de escritos (tales como el uso de un Captcha) **y la extracción
  masiva de datos**". Lo segundo nombra directamente a herramientas de esta clase.

  Vale la pena decir en qué se distingue este proyecto de lo que esa frase describe: una
  petición cada cinco segundos, una causa a la vez, sin persistencia y sin barrido. No es
  extracción masiva por diseño, y el intervalo está verificado por un job de CI. Si aun así
  la institución decide cerrar la consulta automatizada, la respuesta es acatar.
- **Puede publicarse la Política de IA del Poder Judicial.** Si define algo incompatible, este
  proyecto se ajusta o se retira.

## Qué más existe

Revisado el 17 de agosto de 2026. Se anota para no re-descubrirlo, y porque si algo de esto
cubre tu caso mejor, conviene que lo uses en vez de esto.

### Servidores MCP jurídicos

| Proyecto | Jurisdicción |
|---|---|
| [`mcp-legal-ar`](https://github.com/Probanza-ar/mcp-legal-ar) | Argentina. 14 conectores, 203 herramientas, jurisprudencia de la Corte Suprema desde 1863 |
| [`brlaw_mcp_server`](https://glama.ai/mcp/servers/pdmtt/brlaw_mcp_server) | Brasil |
| Entscheidsuche | Suiza |
| Varios | España (CENDOJ) y Colombia |
| [`mcp-dev-latam`](https://github.com/codespar/mcp-dev-latam) | Incluye Chile, pero para comercio y no para tribunales |

**Para Chile no hay ninguno.** Argentina es el ecosistema más maduro de la región y sirve de
referencia de hacia dónde puede ir esto.

### Herramientas chilenas que tocan lo mismo

| Proyecto | Qué hace | Diferencia |
|---|---|---|
| [CausAlerta](https://causalerta.cl/) | SaaS de seguimiento con alertas diarias y calendario de plazos. Desde 6.500 pesos al mes | De pago y cerrado. Su sitio no documenta de dónde saca los datos ni si distingue las dos fechas: **no se puede afirmar que no lo haga** |
| [API de Boostr](https://boostr.cl/poder-judicial) | API REST de consulta de causas | Su demo busca por RUT y persona. No documenta actuaciones de receptor |
| [`automatizador-legal`](https://github.com/ghurtadoarevalo/automatizador-legal) | Programación de sala con FastAPI y Playwright, "extraer audiencias masivamente" | Sin licencia. Es audiencias, no actuaciones |
| [`webscrapthings`](https://github.com/pepelisto/webscrapthings) | Bots de ParalegApp que vigilan actualizaciones de causas | Sin licencia, sin mantención desde 2025 |
| [LemonTech](https://blog.lemontech.com/) y el resto del gremio | Gestión legal completa | Otro producto: esto es una pieza, no una suite |

Lo que ninguna de las públicas documenta es la distinción entre fecha de registro y fecha de
diligencia del ministro de fe, que es lo único que este proyecto reclama como propio. Dicho
con precisión: **que no lo documenten no prueba que no lo hagan**, y las de pago no publican
su esquema. La afirmación defendible es que no hay una fuente pública donde verificarlo.

Una comprobación que se intentó y **no** sirvió: buscar en el código de GitHub los nombres de
los endpoints de la plataforma. La consulta de control (`oficinajudicialvirtual.pjud.cl`)
devolvió cero, o sea el buscador no indexa bien cadenas con puntos, así que los ceros de las
demás consultas no significan nada. Queda anotado para que nadie lo repita creyendo que mide
algo.

### El contexto gremial

Tras el colapso de julio de 2026, la Asociación Gremial Legaltech Chile (Altech A.G.,
21 empresas) respondió al Comité de Jueces rechazando prohibir la IA y pidiendo regular:
sostuvo que "la automatización no implica necesariamente el uso de inteligencia artificial" y
que hay que distinguir "entre inteligencia artificial, automatización de procesos,
robotización y otras herramientas tecnológicas", examinando los antecedentes específicos en
vez de juzgar por volumen.

Esa distinción es la misma que estructura este proyecto, con una diferencia que conviene no
perder: el debate público es sobre **ingresar** escritos. Acá no se ingresa nada.

## Cómo influir en esto

La hoja de ruta la mueve el uso real, no la lista de deseos del autor. Lo más útil:

- Reportar un **dato incorrecto** (máxima prioridad de todas)
- Reportar que **la plataforma cambió**
- Pedir una **competencia** con una causa pública que sirva de fixture
- Contar en Discusiones **qué te falta** para poder usarlo

## Hallazgos de OpenSSF Scorecard que siguen abiertos

Se dejan anotados con su razón, para no re-discutirlos cada vez que aparecen.

| Hallazgo | Estado | Por qué |
|---|---|---|
| `Maintained` | Se resuelve solo | Mide actividad sostenida en 90 días. El repositorio es nuevo |
| `Code-Review` | Se resuelve al usar pull requests | Mide cambios revisados. Hasta ahora los commits fueron directos a `main` |
| `SAST` | Resuelto | Se pasó de modo gestionado a workflow con `codeql-action` fijado por SHA y consultas `security-extended`, que es una de las dos huellas que Scorecard busca |
| `Fuzzing` | Resuelto | Harness de Atheris en `tests/fuzz_parser.py`. Ver abajo por qué también hay pruebas de propiedades |
| `CII-Best-Practices` | **Inalcanzable con esta licencia** | Ver abajo |

Sobre `Code-Review`: en un proyecto de una persona no tiene arreglo técnico, pero para código
que decide plazos procesales vale preguntarse si conviene un segundo par de ojos antes de
tocar el parser. Queda dicho como pregunta abierta y no como casilla marcada.

### Sobre `Fuzzing`

La primera versión de esta nota decía que Scorecard "no reconoce" las pruebas basadas en
propiedades. Es incorrecto, y conviene decirlo bien porque cambia la conclusión.

Scorecard acepta tres señales: inclusión en [OSS-Fuzz](https://google.github.io/oss-fuzz/),
despliegue de ClusterFuzzLite, o funciones de fuzzing definidas por el proyecto. Y en esa
tercera categoría **sí cuenta explícitamente las librerías de pruebas basadas en propiedades**:
QuickCheck, Hedgehog, SmallCheck y validity en Haskell, fast-check en JavaScript y TypeScript,
proper y quickcheck en Erlang, FsCheck en C# y F#, PropCheck y ExUnitProperties en Elixir, y
qcheck en Gleam.

O sea el enfoque que este proyecto usa es exactamente el que Scorecard considera válido. Lo
que falta es que su detector incluya **Hypothesis**, que es el equivalente en Python y no está
en esa lista.

De modo que el hallazgo no dice "a este proyecto le falta fuzzing". Dice "Scorecard todavía no
sabe detectar el fuzzing que este proyecto tiene".

Y hay un detalle que la primera versión de esta nota tampoco tenía: **Scorecard detecta
Atheris con un grep**. Su código (`checks/raw/fuzzing.go`) busca el patrón `import atheris` en
archivos `*.py`, sin exigir inscripción en OSS-Fuzz ni infraestructura alguna. Inscribirse en
OSS-Fuzz son semanas de trámite; un archivo con ese import son minutos. La nota anterior
mandaba por el camino largo.

El repositorio tiene ahora `tests/fuzz_parser.py`, un harness real que corre el parser y
verifica la misma invariante. No corre en CI porque el fuzzing por tiempo no encaja en un
check obligatorio; se ejecuta a mano al tocar el parser.

Conviene precisar en qué se diferencian, porque no es en el oráculo. Un harness de Atheris que
ejecute el parser y afirme que toda fecha devuelta viene en la entrada detecta la misma
infracción que `test_nunca_inventa_una_fecha`: los fuzzers no están limitados a encontrar
corrupción de memoria, y cualquier harness puede llevar el oráculo que se le ponga.

La diferencia real está en cómo se llega a la entrada que rompe. Hypothesis genera desde
estrategias tipadas, así que produce fechas y horas bien formadas y explora el espacio que le
interesa a este parser, y cuando falla **reduce** el caso hasta el ejemplo mínimo. Un fuzzer
guiado por cobertura muta bytes, lo que le permite alcanzar caminos que una estrategia tipada
quizá nunca genere, a cambio de entregar entradas menos legibles.

Son complementarios, y por eso están los dos. La generación estructurada de Hypothesis corre en
cada cambio y rinde más por hora invertida; el harness de Atheris se usa cuando se toca el
parser. La inscripción en OSS-Fuzz, que automatizaría el segundo de forma continua, queda como
paso posterior y no como requisito.

### Sobre `CII-Best-Practices`

La insignia de OpenSSF Best Practices **no se puede obtener con la licencia de este proyecto**,
y conviene dejarlo escrito para no volver a intentarlo.

Entre los criterios obligatorios del nivel `passing` está `floss_license`:

> "The software produced by the project MUST be released as FLOSS"

[PolyForm Strict](licencia.md) no es FLOSS: prohíbe modificar, distribuir y el uso comercial.
No es un criterio sugerido que se pueda saltar, es un MUST.

Marcarlo como cumplido sería falso, y una insignia es una declaración pública. Así que el
hallazgo queda abierto de forma permanente mientras la licencia no cambie.

Es el de severidad más baja de los cinco, y la decisión de licencia se tomó por razones que
pesan más: que nadie publique su propia versión y que todo uso profesional pase por un permiso
explícito. El costo está anotado en la página de licencia junto a los demás.

La serie Baseline de la misma insignia podría no exigir FLOSS, pero sus niveles
(`baseline-1/2/3`) no son los que el check de Scorecard puntúa, que son `passing`, `silver` y
`gold`. O sea tampoco cerraría el hallazgo.
