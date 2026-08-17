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

### Verificado sólo contra fixtures

Funciona sobre HTML real guardado, pero **nunca se ejercitó contra el sistema en vivo**:

| Qué | Riesgo |
|---|---|
| Discrepancia entre las dos fuentes de fecha | Nunca se vio un caso real de discrepancia. La rama existe y está testeada con HTML sintético, pero no hay evidencia de cómo se ve en la práctica |
| Georreferencia ausente | Todas las actuaciones observadas la traen. No se sabe cómo se ve la celda cuando falta |
| Fecha imposible (31/02) | Defensa preventiva, nunca observada |
| Mensaje de "sin resultados" | Se copió de una respuesta real, pero el camino completo no se ejercitó |

### Sondeado contra el sistema real, sin implementar

| Qué | Resultado |
|---|---|
| Códigos de cobranza (competencia 6, tribunal 1332, tipos `A C D E J L P R`) | Confirmados |
| Estructura del detalle de cobranza | Difiere de civil: panel `historiaCob`, columna `Estado Firma`, sin `Foja`, panel `diligenciaCob` |
| Actuaciones de receptor en cobranza | **No encontradas** en la causa sondeada |
| Reglas de la búsqueda por nombre | Exige mínimo dos campos y un tribunal; las búsquedas amplias agotan el tiempo de espera |
| `sitemap.xml` y `.well-known/security.txt` | No existen en ninguno de los dos hosts |

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

- **Paginación.** Se procesa el primer resultado de la búsqueda. Una búsqueda con varias
  causas devuelve sólo una.
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

### 0.2: paginación y varias causas

El caso "busco y salen doce causas" hoy no funciona: se procesa la primera.

- Parsear los controles de paginación
- Devolver todas las causas del listado
- Herramienta `buscar_causa_por_nombre`

**Lo que se aprendió sondeando la búsqueda por nombre**, y que cambia el diseño previsto:

| Regla de la plataforma | Consecuencia |
|---|---|
| Exige **mínimo dos campos** llenos. Si no: `Por favor llene mínimo 2 campos para la búsqueda` | Hay que validarlo en el cliente. Si no, el usuario recibe un `<script>swal(...)` como si fuera un resultado |
| Exige **seleccionar un tribunal**. Si no: `Por favor seleccione un Tribunal para la búsqueda` | Contradice el supuesto de que esta búsqueda sirve cuando no se sabe dónde está la causa. Hay que conocer el tribunal igual |
| Una búsqueda amplia por apellido común **agota el tiempo de espera** | Necesita un timeout mayor que el resto, y conviene exigir entradas más específicas |

Ese último punto además marcó el límite del sondeo: insistir con búsquedas amplias es
exactamente la carga que este proyecto se comprometió a no generar, así que se detuvo ahí y
la verificación se retoma con una causa acotada y conocida.

**Riesgo que sigue en pie:** doce causas × 5 peticiones × 5 segundos son cinco minutos. La
respuesta correcta probablemente sea devolver el listado y que el usuario elija, en vez de
encadenar todo.

### 0.3: cobranza laboral y previsional

Sondeada contra el sistema real con `C-208-2019` del Jdo. Cobranza Laboral y Previsional de
Concepción (tribunal `1332`, competencia `6`, tipos de causa `A C D E J L P R`).

**Su estructura difiere de civil**, así que necesita parser propio y no una ampliación de
`MODULOS`:

| | Civil | Cobranza |
|---|---|---|
| Panel de historia | `historiaCiv` | `historiaCob` |
| Columnas | Folio, Doc., Anexo, Etapa, Trámite, Desc. Trámite, **Fec. Trámite, Foja**, Georref. | Folio, Doc., Anexo, Etapa, Trámite, Desc. Trámite, **Estado Firma, Fec. Trámite**, Georref. |
| Paneles propios | Litigantes, Notificaciones, Escritos, Exhortos, Piezas Exhorto | Deuda, **Diligencia**, Liquidación, Litigantes, Notificación |

O sea: entra una columna `Estado Firma`, desaparece `Foja`, y hay un panel `diligenciaCob` que
civil no tiene.

**Lo que no se pudo verificar, y es lo que importa:** esa causa no trae ninguna fila con
`Actuación Receptor`, ninguna fecha doble ni ningún `Diligencia:`. El panel `diligenciaCob`
resultó ser de oficios y liquidaciones, no de actuaciones del ministro de fe.

Así que sigue sin evidencia de que cobranza exponga el dato que da sentido al proyecto. Antes
de implementarla hay que encontrar una causa de cobranza que sí lo traiga; si no existe, la
competencia no vale el esfuerzo por más que sus rutas estén mapeadas.

### 0.4: exhortos y documentos

- `detalleExhortos.php`: seguimiento de exhorto de origen a destino
- `causaOrigenCivil.php`
- Descarga de documentos por folio vía `docuN.php`

**Decisión pendiente y no trivial:** descargar un PDF significa traer datos de terceros a
disco. Eso cambia el perfil de retención y entra de lleno en la Ley 21.719. Probablemente
requiera consentimiento explícito por llamada, y ruta de destino elegida por el usuario.

### 0.5: laboral y apelaciones

Las dos competencias que siguen en volumen de uso real.

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

**Jurisprudencia.** Descartada de forma permanente por el bloqueo nominal de `juris.pjud.cl`.
Sólo reviviría por Ley 20.285 o fuente licenciada.

## Lo que se va a romper

No es pesimismo, es planificación:

- **La plataforma va a cambiar.** El prefijo de rutas y el token ya se derivan en caliente por
  esto. Cuando cambie la estructura de tablas, el parser falla ruidosamente y hay que
  arreglarlo.
- **Pueden activar la validación del captcha.** Hoy la consulta funciona sin ella. Si se
  activa, la cadena se cae entera y no se va a evadir: el proyecto se detiene y se busca la
  vía institucional.
- **Puede publicarse la Política de IA del Poder Judicial.** Si define algo incompatible, este
  proyecto se ajusta o se retira.

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
