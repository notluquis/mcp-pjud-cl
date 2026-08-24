---
myst:
  html_meta:
    description: "Qué se va a hacer y en qué orden, con lo que se decidió no hacer y por qué. Para quien evalúa hacia dónde va."
---

# Hoja de ruta y estado de verificación

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
   El contador va en cero, y se reinició cinco veces seguidas: la 0.10.0 agregó `anexo_ruta`,
   `anexo_referencia` y `audio_referencia`; la 0.11.0, `diligencias`, `escritos_pendientes` y
   `causa_de_origen`; la 0.12.0, `causas_agregadas`; la 0.13.0, `desplazamiento` y los campos
   nuevos del PDF. Cada canal nuevo que se abre lo reinicia, y eso es esperable mientras queden
   canales sin leer.
3. **Seis meses sin que un cambio de la plataforma rompa el parser**, o con al menos un cambio
   detectado y corregido dentro de la semana.

## Hoja de ruta

### 0.2: paginación y varias causas — hecho

Los controles de paginación se parsean, el listado se recorre entero y existen las búsquedas
por nombre y por RUT de persona jurídica. El recorrido levanta `ResultadosTruncados` al llegar
al tope en vez de devolver una lista recortada.

Quedó decidido lo que estaba en duda: **no se encadenan las actuaciones de todas las causas de
un listado**. Doce causas son unas sesenta peticiones, y bajo el régimen sostenido de una cada
5 segundos eso son unos cinco minutos: la ráfaga alcanza para la primera causa y no cambia el
total. La respuesta correcta es devolver el listado para que el usuario elija cuál abrir.

### 0.3: jurisprudencia — hecho parcialmente

`buscar_jurisprudencia` anda contra siete de los diez buscadores: Corte Suprema, Cortes de
Apelaciones, Laborales, Civiles, Cobranza, Familia y Salud CS. El de Penales está medido y no se
expone, por decisión y por lo mismo que el detalle de las causas penales. Con la paginación
medida, una búsqueda ya no se corta en la coincidencia 250.

Los tres que quedan fuera están medidos, así que ninguno espera trabajo: penales y el compendio
de extranjería publican un dato de una persona en cada fila, y líneas jurisprudenciales no
entrega fallos sino temas. La sección de jurisprudencia, más abajo, lo detalla.

### 0.4: las seis competencias buscables — hecho

Las cuatro búsquedas (`consultaRit*`, `consultaNombre*`, `consultaJuridica*` y
`consultaFecha*`) están verificadas en las seis competencias que el servidor expone, cada una
con su fixture real anonimizada.

Lo que las bloqueaba resultó ser un solo campo, y conviene dejar escrito el diagnóstico
equivocado porque era plausible y costó dos intentos: se creyó que sobraban los campos que el
sitio deshabilita (`conTipoCausa`, `conCorte`, `conTribunal`), y que faltaba un código de libro
en `conTipoCausa`. **Las dos cosas eran falsas.** El combo de libros existe
(`json/cmbTipos.php`) y devuelve cero bytes para suprema, y la búsqueda anda igual con o sin
los campos deshabilitados. Faltaba `radio-group`, el radio RIT/RUC del formulario, en el que su
PHP se ramifica para saber por cuál de los dos se busca.

Se encontró bisectando desde el juego de campos que fallaba, no leyendo más JavaScript.

**Y el arreglo salió incompleto, que es la parte que conviene no olvidar.** `radio-group`
desbloqueó a suprema y apelaciones, pero `penal` tiene su propio radio (`radio-groupPenal`) y
siguió rota; las tres se declararon verificadas y se publicaron así en la 0.2.0. La causa es
una sola: se midieron con peticiones armadas a mano y los tests usan dobles, así que nada
ejercitó `buscar_por_rit` contra la plataforma. Verificar la petición no es verificar el
cliente. Los campos propios de cada competencia salen ahora de la tabla, con un test que
compara el formulario enviado contra lo que ella declara.

**Lo que sigue pendiente es lo que da valor**, y es más chico de lo que parecía:

- **`diligenciaCob`**: cobranza tiene ministro de fe y sus diligencias viven en un panel
  aparte, con estructura propia (`Estado Diligencia`, `Tipo Diligencia`, `Destinatario`,
  `Responsable`). Su Historia **sí nombra algunas**: tres filas dicen `Actuacion - Receptor`,
  sin tilde y con guion, y ninguna trae fecha de diligencia. Por eso `actuaciones_receptor`
  rechaza cobranza: no se sabe si esas tres son todas, y entregarlas se leería como el total.

  **El panel se lee, y no entrega actuaciones.** El detalle de causa lo trae en `diligencias`:
  qué diligencia hay, en qué estado, a quién se dirige y quién figura a cargo. Lo que **no**
  trae es la fecha en que se practicó: la columna publica `31/12/1969`, el epoch, o sea el
  valor cero renderizado, y ese cero se entrega en **nulo** en vez de como fecha. Informarlo
  como `31/12/1969` haría computar un plazo desde 1969, que es peor que no informarlo.

  Lo que sigue pendiente es más chico que antes: encontrar una causa donde ese panel **sí**
  publique fechas. Hasta entonces, la fecha que corre los plazos en cobranza no está en ninguna
  parte de la respuesta, y decirlo es lo único cierto que se puede decir.

- **Las notificaciones son otra fuente de fechas, y no son uniformes.** Buscando lo anterior
  apareció que cobranza publica `notificacionCob` con DOS columnas de fecha, `Fec.Not.` y
  `Fec.Tram.`, que difieren: las notificaciones por correo electrónico coinciden y las por
  carta van con un día de diferencia. Civil publica otra cosa: el panel se llama
  `notificacionesCiv`, tiene ocho columnas y **una sola** fecha.

  Es la lección de cobranza repetida: mismo concepto, estructura distinta por competencia.
  **Resuelto en la 0.4.0**, cuando apareció una causa civil con tres notificaciones reales y
  se pudo medir en vez de adivinar: los dos paneles se leen, cada uno con sus columnas, y
  `fecha_notificacion` va nula donde la competencia no la publica en vez de copiar la de
  trámite.

- **Laboral, penal, suprema y apelaciones no tienen receptor.** En todo el sitio sólo existen
  `receptorCivil` y `receptorCobranza`. Queda declarado en la tabla y se rechaza antes de
  gastar una petición.

### 0.5: el resto del detalle de causa — hecho parcialmente

`webscrapthings` cubre esto desde 2025 y un abogado lo espera. Se divide en dos, porque el
costo no es el mismo:

**Sin peticiones nuevas.** Ya vienen en la respuesta del detalle que el cliente pide, y ése
era el punto: `obtener_detalle_causa` los lee todos de una sola cadena. Preguntar las cuatro
cosas de una causa con dos cuadernos costaba dieciséis peticiones y ahora cuesta cuatro.

La cadena entera, medida en vivo con C-1156-2026 el 20 de agosto de 2026. Las dos primeras
abren la sesión, y por eso el total es seis y no cuatro:

```mermaid
graph LR
  S1["1· sesion-consultaunificada.php"] --> S2["2· consultaUnificada.php<br/><i>de acá salen el prefijo y el token</i>"]
  S2 --> B["3· consultaRit<br/><i>encuentra la causa</i>"]
  B --> D["4· detalle<br/><i>trae la lista de cuadernos</i>"]
  D --> C1["5· cuaderno Principal"]
  D --> C2["6· cuaderno Apremio"]
  C1 --> R["una respuesta"]
  C2 --> R
```

Los paneles que NO son la historia se deduplican por contenido: no llevan el cuaderno en la
fila, así que si el sitio los repite en cada uno llegarían dos veces.

- `litigantesCiv`: quiénes son parte y con qué calidad. **Hecho**, en las cinco competencias
  con detalle mapeado
- `notificacionesCiv`: con su propio estado y su propia fecha de trámite. **Hecho**
- `liquidacionCob` y `materiasLab`: cuánto se debe, y qué se litiga. **Hecho**
- `escritosCiv`: **hecho**, y resultó ser otra cosa de la que esta página suponía. No es el
  listado de los escritos presentados: el sitio rotula la pestaña "Escritos por Resolver", o
  sea es la COLA de lo que espera proveído. Por eso las causas viejas lo traen vacío con
  escritos de sobra en su Historia, y una causa de esta semana trae dos
- `exhortosCiv`: el exhorto visto desde el tribunal de origen. **Hecho**
- `piezasExhortoCiv`: el exhorto visto desde el otro lado. **Hecho**, con un campo aparte que
  dice si la causa es un exhorto. Ver abajo

La respuesta del detalle sigue sin ser el expediente completo, y su contrato lo dice desde la
0.10.0: quedan paneles sin leer y son distintos en cada competencia. Que el de escritos ya esté
no cambia esa advertencia, la acorta.

Los dos lados del exhorto están medidos y la tabla vive en {doc}`verificacion`.

`exhortosCiv` se lee desde el origen y `piezasExhortoCiv` desde el destino: los dos están
cubiertos. Mapear el segundo tenía una decisión de contrato antes que de código, porque en
`DetalleCausa` el `None` ya significaba "esta COMPETENCIA no publica el panel" y acá hacía
falta decir "esta CAUSA no es un exhorto", que no es lo mismo. Sobrecargar `None` con los dos
sentidos es exactamente la distinción que este proyecto existe para no borrar.

Se resolvió con la **cabecera de la causa**, que hasta entonces no se leía de ninguna
competencia: el rótulo `Proc.` dice `Exhorto` cuando la causa lo es, y de ahí sale la respuesta
sin inferirla de qué paneles llegaron. Al lado de `piezas_exhorto` viaja `causa_es_exhorto`,
con el mismo oficio que `causa_encontrada`: nombrar cuál de los dos silencios es éste.

Las dos lecturas se contrastan y una contradicción levanta, porque las dos salidas silenciosas
pierden datos. Si el sitio renombra el `id` del panel, creerle al panel diría "esta causa no es
un exhorto" y las piezas desaparecerían sin error; al revés, un panel que llegue en una causa
que la cabecera no declara exhorto no se descarta por la cabecera.

**Una petición cada uno, con su intervalo.** Son modales que la plataforma carga aparte, y hay
que contarlos en el tiempo total:

- `modal/detalleExhortos.php`, que la fila del exhorto invoca con su propia referencia
- `modal/causaOrigenCivil.php`

### 0.6: Programación de Sala — medido, y no es lo que esta página decía

Acá había un mapeo listo para implementar, sacado de leer `automatizador-legal`: `progComp`,
`progCorte`, `progRolCausa`, `progEraCausa`, `progTipoCausa`, `btnProgConsulta` y
`dtaTableDetalleProgSala`. **Ninguno de los siete existe.** Medido el 20 de agosto de 2026:
cero ocurrencias en `consultaUnificada.php` y cero en la página real.

Tres cosas resultaron distintas de lo que decía:

**Está en otro host.** `https://salas.pjud.cl/monitor/monitor.php`, no en la Oficina Judicial
Virtual. Se llega desde la portada, que lo enlaza.

**No comparte cortafuegos con los otros dos.** OJV y `juris.pjud.cl` responden con la cookie
`TS<hex>` de F5 BIG-IP, y por eso la detención total es del proceso y no del host. `salas`
responde `Server: Apache`, sin esa cookie y sin `Via`. Es una diferencia medida, no una
suposición, y habría que decidirla antes de consultarlo desde acá: el motivo de la detención
total no es técnico, es no escalar contra la institución, y eso no cambia con el host.

**Y no es una consulta por causa.** Se llama "Monitor de Salas" y pide *"Seleccione Corte y
Sala que desea visualizar"*: dos desplegables, `corte` (que viaja como `cod_corte`) y `sala`,
que se llena con `controlador/listaSalaPorCorte.php`. **No recibe un rol.** Es un tablero de
qué se está viendo ahora en una sala, no la respuesta a "¿cuándo me ven?".

Un detalle más que conviene tener anotado: los valores del desplegable de corte vienen
cifrados (`t+r7m+HbenMm8+DvHDPmhBvuw50npbnCNFmLW+Sp4RM=`), **no son los códigos numéricos que
usa la Oficina Judicial Virtual**. Son dos sistemas con dos vocabularios.

Queda como pregunta abierta y no como tarea: si lo que se quería era "¿cuándo me ven?", esto no
lo responde, y dónde vive esa consulta, o si existe, no está medido.

### 0.7: documentos

No es una ruta, son siete en civil y **veintisiete** contando las cinco competencias. Todas son
`GET` con un solo parámetro oculto que lleva una referencia opaca, igual que el resto del sitio,
y todas salen del `action` de un formulario de la respuesta.

Siete se han ejecutado de verdad, una por competencia como mínimo; las veinte que faltan esperan
una causa que ofrezca la fila que las entrega. La tabla, con lo que midió cada una, está en
{doc}`verificacion`.

**Y hasta ahora la respuesta no decía cuál documento.** `tiene_documento` era un booleano: la
actuación informaba que HAY documento y no CUÁL, y con eso no se puede pedir. La referencia
estaba en la misma celda, en el campo `dtaDoc` del formulario, y se descartaba. Corregido: cada
actuación trae su `documento_referencia`, que es lo único que permite pedir el archivo sin
volver a consultar el detalle entero.

#### Cómo se devuelve un documento sin reventar el contexto

El ebook es el expediente completo. Meterlo en la respuesta de una herramienta, aunque sea en
base64, gasta el contexto del modelo en algo que probablemente no necesita leer entero, y el
costo lo paga la conversación del abogado.

La especificación del protocolo tiene la pieza para esto y no hace falta inventarla. En la
revisión `2026-07-28` una herramienta puede devolver:

| Forma | Qué es | Cuándo |
|---|---|---|
| `ResourceLink` | Un puntero con `uri`, `mimeType` y `size`, sin el contenido | El ebook y cualquier documento largo. El cliente lo lee con `resources/read` **sólo si lo necesita** |
| `EmbeddedResource` con `BlobResourceContents` | El contenido en base64, dentro de la respuesta | Un documento chico que el modelo sí tiene que leer ahora |

`ResourceLink` trae `size`, así que el cliente puede decidir **antes** de gastar el contexto.
Ésa es la diferencia con devolver el PDF y esperar que a nadie le explote la ventana.

#### Extraer texto: qué biblioteca, y por qué la licencia decide

Lo medido por terceros y publicado, no por este proyecto:

| Biblioteca | Licencia | Velocidad | Nota |
|---|---|---|---|
| PyMuPDF | **AGPL-3.0** | 8 a 12 veces más rápida | Trae OCR y detección de tablas |
| pdfplumber | MIT | La más lenta de las tres | Mejor en tablas de documentos financieros |
| pypdf | BSD-3 | Intermedia | Python puro, sin dependencias binarias |

**La velocidad no decide acá, la licencia sí.** Este proyecto se distribuye bajo PolyForm
Strict, y publicar una rueda que enlaza código AGPL pone las dos licencias en conflicto. Con
eso PyMuPDF queda fuera aunque sea la más rápida, y quedan pypdf y pdfplumber.

#### Un PDF sin capa de texto es un escaneo, y ahí NO se transcribe

Detectarlo es barato: si no se extrae texto, es una imagen. Lo que no corresponde es pasarle
OCR y entregar el resultado como el texto del documento.

Una transcripción automática de una resolución judicial **se ve idéntica a la resolución y no
lo es**. Es peor que la lista vacía de la regla 4: la lista vacía se nota, un texto plausible
con una palabra cambiada no. Lo correcto es decir que el documento es un escaneo y entregar el
documento, no una versión de él.

#### Y la parte que no es técnica

Traer un PDF a disco cambia el perfil de retención del proyecto y entra de lleno en la Ley
21.719. La regla 5 dice que no se persisten datos de terceros, así que si un documento se
guarda, lo guarda quien llama y no este servidor: ruta elegida por el usuario, consentimiento
explícito por llamada, y nada escrito por defecto.

### 0.7a: los códigos de tribunal — hecho

**Era el muro de entrada del proyecto.** Para buscar una causa en primera instancia hay que
pasar `tribunal=162`, y ese número no aparecía en ninguna parte de la respuesta ni de esta
documentación: quien no lo supiera no podía usar el servidor. Lo resuelven `listar_cortes` y
`listar_tribunales`.

Las rutas y lo que devuelven están en {doc}`verificacion`.

Y es lo que hace **seguible** la arista del exhorto. El detalle entrega el tribunal de destino
por su nombre ("1º Juzgado Civil de Chillán") y la búsqueda exige un entero, así que son tres
llamadas: ubicar la corte, sacar el código del tribunal, y buscar la causa por su rol.

El exhorto trae además su propia referencia, que es como la plataforma abre su detalle. Se
guarda sin usarla: `detalleExhortos.php` sigue mapeado y sin ejecutar, y cuando se mida el dato
ya está. **No sirve como identidad**: el mismo exhorto llega con una referencia distinta en
cada cuaderno, así que la deduplicación las ignora a propósito.

(07b-la-georreferencia-medida-y-trae-una-tercera-fecha)=

### 0.7b: la georreferencia — hecha

Hoy la Historia sólo dice si una actuación tiene georreferencia. Detrás del modal hay más de lo
que esta página suponía. Lo medido está en {doc}`verificacion`.

**Y trae fotos y videos.** El modal tiene tres pestañas: `mapasGeoRef`, `imagenesGeoRef` y
`videosGeoRef`. **Las seis actuaciones medidas traen las dos últimas vacías**, así que no hay
ni una imagen observada todavía.

Se anotó una vez que había que decidir si entregarlas, y esa duda estaba mal planteada: el
proyecto ya entrega **RUT de personas naturales**, que identifica más que una fotografía, y lo
justifica porque es lo que la plataforma publica y lo que identifica a una parte sin
ambigüedad. Entregar lo que el Poder Judicial publica es lo que este servidor hace; la regla 5
prohíbe **persistirlo**, que es otra cosa.

Lo que sí sigue en pie, y es la regla 6: si alguna vez se guarda una respuesta con imágenes
como fixture, esa fixture hay que anonimizarla igual que las demás.

Cuesta **una petición por actuación**, con su intervalo. Para las ocho de receptor de
E-468-2026 serían ocho peticiones más, así que va a pedido de una actuación concreta y nunca de
barrido.

### 0.8: el detalle de las competencias ya buscables — hecho, salvo penal

Las cuatro se pidieron y se midieron sobre una causa real. Tres quedaron mapeadas y expuestas
por `obtener_detalle_causa`; penal no, y la razón es la de siempre.

| Competencia | Panel | Qué la distingue |
|---|---|---|
| `laboral` | `movimientoLab` | Como civil, con `Estado` donde civil pone `Foja` |
| `suprema` | `movimientosSup` | Sin `Etapa` ni `Georref.`; agrega `Salas`, `Correlativo` y el año |
| `apelaciones` | `movimientosApe` | Llama `Descripción` y `Fecha` a lo que civil llama `Desc. Trámite` y `Fec. Trámite`, y su georreferencia se escribe `Georeferencia` |
| `penal` | `historiaPen` | **Cero filas**, y la razón no era la que decía acá |

**Penal sigue sin mapear, y ya no por falta de datos.** Lo que esta página afirmaba, que la
causa medida no traía filas, era cierto y el diagnóstico era falso: se estaba pidiendo la ruta
equivocada. Las causas penales **no se abren por `penal/`**. Cada fila del listado llama a
`detalleCausaPenalUnificado`, que va a `unificado/modal/causaUnificado.php`, y ésa responde con
la cabecera llena y los paneles con filas. Medido el 22 de agosto de 2026 sobre nueve causas de
2024 y 2026; la tabla de paneles y columnas está en {doc}`verificacion`.

La ruta que lleva el nombre de la competencia devuelve **200 con los cuatro paneles, sus
encabezados y cero filas**: la forma exacta de "esta causa penal no tiene nada".

**Y la decisión está tomada: penal queda fuera de alcance.** El titular la tomó el 22 de agosto
de 2026, al terminar la medición y no antes: primero se midió para poder decidir con datos, y
lo medido queda escrito en {doc}`verificacion` para quien evalúe esto de nuevo.

No es un pendiente ni una limitación técnica. La respuesta se lee, y aun así no se expone: un
expediente penal nombra imputados y víctimas, y el criterio que sostiene al resto del proyecto,
devolver lo que la plataforma publica sin identificarse, no se traslada solo a ese contenido.
Queda junto a familia, por una razón distinta: familia no se puede leer, penal sí y no se
quiere.

Lo que NO cambia: penal sigue siendo **buscable**, como desde la 0.2.0. Buscar una causa
devuelve rol, tribunal, RUC, caratulado y estado, que es lo mismo que el listado público de la
plataforma muestra. Lo que queda fuera es el **detalle**: la historia, las partes y el panel de
relaciones con el delito.

Y el rechazo del detalle deja de explicarse como falta de medición. Es una decisión.

**Ninguna de las cuatro tiene receptor.** La palabra no aparece ni una vez en las tres
respuestas mapeadas, y ninguna fila trae la fecha doble. Por eso la historia se lee aparte de
las actuaciones del receptor: en esas competencias la pregunta que origina el proyecto no tiene
respuesta, y sin ella lo único disponible ahí era la búsqueda.

Un detalle del recorrido que conviene no perder: el nombre del panel se guarda completo y no
como sufijo. Antes el código anteponía `historia`, lo que funcionaba con dos competencias que se
llamaban así y no generaliza: dos de las nuevas van en plural (`movimientos…`) y una en singular
(`movimiento…`).

### 0.9: familia

La única competencia que no se expone, y no por falta de medición: la propia plataforma
responde que las causas de familia son reservadas y sólo se llega a ellas por Clave Única,
desde "Mis Causas". Queda fuera de alcance mientras eso siga así.

Esto es la competencia de la Oficina Judicial Virtual, o sea las causas en tramitación. El
buscador de fallos de Familia es otra cosa y sí se expone desde la 0.13.0: publica sentencias
ya dictadas, con el caratulado anonimizado por la propia plataforma.

### 0.10: los otros dos canales del folio — hecho parcialmente

La Historia publica más de un canal por folio y hasta la 0.9.0 se leía uno solo.

**Anexos: cuatro paneles ofrecidos de ocho medidos.** La columna `Anexo` es un segundo canal de
documentos, distinto de `Doc.`: ahí va la resolución o el escrito, y acá los papeles que se
acompañaron, o sea donde suele estar la prueba documental. Lo que hacía invisible la falta es
que el folio SÍ entregaba un documento por el otro canal, así que la respuesta parecía completa.

Cada actuación trae ahora `anexo_ruta` y `anexo_referencia`. Van las dos porque una competencia
tiene varios paneles: civil abre dos desde la misma columna, con parámetros distintos.

De las dieciocho rutas que el sitio nombra hay siete medidas, más la de suprema, que el sitio
llama "Escrito". Se ofrecen cuatro: las que una fila puede entregar, tres desde un folio de la
Historia y una desde un escrito por resolver. Las otras cuatro respondieron con filas y no se
ofrecen porque su referencia no cuelga de ninguna fila que este servidor lea, o sea no habría de
dónde sacar el parámetro. Las once que faltan siguen sin ejecutarse: se abrieron sesenta y una
causas buscándolas y ninguna las ofrecía. La tabla está en {doc}`verificacion`.

**Audios de audiencia: hecho, y a propósito sin descargar.** `listar_audios_audiencia` dice qué
hay y con qué enlace se baja cada archivo. No trae los archivos, y eso no es una limitación
técnica: un audio de audiencia son las voces de las partes, los testigos y el tribunal, una
transcripción automática no reemplaza oírlo, y no siempre se puede transcribir.

Es el primer canal de la plataforma que no entrega PDF, y viene troceado por acto procesal:
once archivos para una sola audiencia preparatoria. Sólo laboral está medida.

Por lo mismo siguen sin medir, deliberadamente, cuánto pesa un archivo y si el endpoint de
descarga responde a una consulta anónima: ninguna de las dos hace falta para entregar el enlace.

### 0.11: los paneles que quedaban del detalle — hecho

Cuatro paneles que la respuesta ya traía y este servidor tiraba.

**Los escritos por resolver de civil resultaron ser otra cosa** de la que esta página suponía:
no son los escritos presentados sino la COLA de lo que espera proveído, que es lo que el sitio
rotula en la pestaña. Por eso las causas viejas lo traen vacío con escritos de sobra en su
Historia. Responden una pregunta que la Historia no responde, porque ahí el escrito aparece
cuando YA fue resuelto.

**Las diligencias del ministro de fe**, en cobranza y en laboral, cada una con su forma. En
cobranza la fecha viene nula cuando el sitio imprime el epoch `31/12/1969`, que es el valor cero
y no una diligencia de 1969. En laboral, que una diligencia no traiga el oficio de vuelta es el
dato de que todavía no vuelve.

**La causa de origen de suprema** cierra hacia abajo la misma arista que los exhortos cierran
hacia el lado: de qué causa de apelaciones subió el recurso. Su panel falta en tres de dieciséis
causas, porque no todas suben desde una corte, y eso vuelve nulo y no error.

Y una fuga que había que retirar de lo publicado: tres nombres reales de personas seguían en las
fixtures versionadas, invisibles para los cuatro guardias porque venían en mayúscula y minúscula
o con un sufijo entre paréntesis.

### 0.12: los tres paneles sin una fila vista — hecho

Los escritos pendientes y la liquidación de laboral, y las causas agregadas de suprema. De los
tres se midieron los ENCABEZADOS y de ninguno se vio una fila: sesenta y una causas abiertas en
cinco barridos, cero filas.

La distinción con el resto no vive en un comentario: `SIN_FILAS_OBSERVADAS` los nombra, la
referencia lo advierte y un guardia compara esa lista contra las fixtures en las dos
direcciones. Se leen igual para que el día que una causa los traiga la respuesta los incluya, en
vez de descartarlos en silencio.

Quedan dos paneles sin mapear, los de apelaciones, y ahí no hay qué mapear: su tabla son dos
columnas, la primera en blanco y la segunda con el rótulo, y en la mitad de los detalles el
panel ni siquiera aparece.

### 0.13: el buscador de fallos deja de ser una sola página — hecho

**La paginación existía desde siempre y el tope lo poníamos nosotros.** El cuerpo de la
búsqueda mandaba `offset_paginacion` en `"0"` literal, así que la coincidencia 251 no existía
para este servidor. Medido el 22 de agosto de 2026 sobre una búsqueda de 59.819 visibles, con
desplazamientos 0, 10 y 250: tres páginas distintas, cero solapamiento. Más allá del final la
plataforma responde 200 con la lista **vacía**, no un error, y eso es lo que el esquema
advierte.

**Cuatro buscadores más**, con lo que diez de los diez están medidos y siete se exponen: Civiles,
Cobranza, Familia y Salud CS. El de penales queda medido y fuera, por lo mismo que el detalle
de las causas penales: sus caratulados traen el nombre del imputado. Los dos que faltan no
tienen medición y no es lo mismo: el Compendio de Extranjería no tiene ruta conocida y Líneas
Jurisprudenciales responde con otra forma, sin `response.numFound`.

**Una ruta de buscador que no existe devolvía la página de OTRO buscador**, con su
identificador y sus campos, y las búsquedas contestaban ese corpus sin que nada fallara. Es la
misma forma del falso negativo que ya apareció con los audios, con los anexos y con penal, y
por eso ahora se compara el `id_buscador` de la página contra el que se midió.

**El PDF ya se leía entero y se tiraba casi todo.** `obtener_documento` extraía el texto de
cada página para quedarse con un conteo; ahora dice CUÁLES páginas lo traen, por tramos, más
los marcadores del archivo y cuánto mide su página. No cuesta una consulta más. Un PDF cifrado
dejó de informarse con el mismo mensaje que uno truncado.

**Siete de las veintisiete rutas de documento se pidieron de verdad**, en las cinco
competencias, y antes era una sola: las demás se habían leído del `action` de un formulario.
Las veinte que faltan esperan una causa que las ofrezca.

Y dos guardias que faltaban, los dos sobre lo mismo: que una afirmación no se quede vieja
donde nadie la mira. Doce de los veintitrés paneles del detalle no pasaban por el arnés que
comprueba el mapeo posicional, y las dos cuentas de buscadores estaban viejas en cinco lugares,
entre ellos `AGENTS.md`, que es lo que otro agente lee como instrucción.

### Sin versión asignada

**Detección de cambios entre consultas: descartada.** Avisar cuando aparece una actuación
nueva implica persistir datos de terceros, y eso cambia todo el perfil del proyecto bajo la
Ley 21.719. El titular la descartó el 17 de agosto de 2026. Queda anotada como decisión y no
como pendiente, porque es la función que alguien va a pedir mirando lo que vende la
competencia.

**Búsqueda de cartera por identificador de abogado.** El campo `Institución` de los listados
permite reconstruir la cartera completa de un abogado. Técnicamente es directo.
**Deliberadamente en duda**: construir perfiles de personas está en la lista de usos que el
proyecto rechaza, aunque el dato sea público. Si se implementa, será con un caso de uso
justificado y no "porque se puede".

**Jurisprudencia de otros buscadores.** Ver la sección propia más abajo: de los buscadores que
ofrece `juris.pjud.cl` diez de los diez están medidos, y cada uno declara sus propios campos.

## Jurisprudencia: qué hay mapeado y qué falta

El Buscador Unificado de Fallos no es una aplicación de una sola página como se creyó al
principio: es PHP con Laravel y componentes Vue encima, y su búsqueda devuelve JSON de Apache
Solr. Eso lo hace bastante más fácil de consumir que la consulta de causas, que entrega HTML.

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

- **Texto completo: hecho**, con la forma que la decisión exigía. Está en
  `obtener_texto_sentencia`, aparte de la búsqueda y de a una sentencia por llamada. La razón
  es medible: una sentencia de trece páginas son 25.473 caracteres, así que devolver diez con
  cada búsqueda serían más de 250.000. La búsqueda entrega `texto_preview` y la extensión en palabras
  y páginas, que suele bastar para decidir si vale pedir el resto.

  Sobre los datos personales: la respuesta declara `anonimizada` y `fuente`, o sea si lo
  entregado es la versión con los datos suprimidos por el tribunal y de cuál de los dos campos
  salió. Y si la sentencia existe pero está reservada, se levanta en vez de devolver un texto
  vacío que se leería como una sentencia sin contenido.
- **Paginación: hecha, y el diagnóstico anterior era nuestro.** Acá decía que no existe, leído
  de la petición: `offset_paginacion` iba fijo en `0`, así que la coincidencia 251 era
  inalcanzable. Medido el 22 de agosto de 2026 contra el buscador de Corte Suprema, la
  plataforma sí la soporta: con desplazamiento 0, 10 y 250 devuelve tres páginas sin una sola
  sentencia repetida. El límite lo ponía este cliente, no el sitio.

  Entra `desplazamiento` en `buscar_jurisprudencia`, y `no_entregadas` pasa a contar lo que
  queda DESPUÉS de esta página: sin descontarlo, la segunda página declaraba como no entregado
  justo lo que la primera ya había traído. Pedir más allá de `visibles` devuelve una lista vacía
  con 200, no un error.
- **Una cuenta.** Con credenciales del Poder Judicial se verían más sentencias. Queda fuera:
  este proyecto consulta lo que es público sin identificarse como funcionario.

## Herramientas de descubrimiento que no existen

Verificado el 17 de agosto de 2026, en los dos hosts:

| Ruta | `oficinajudicialvirtual.pjud.cl` | `www.pjud.cl` |
|---|---|---|
| `/sitemap.xml` | 404 | 404 |
| `/.well-known/security.txt` | 404 | 500 |
| `/robots.txt` | `Disallow: /` | 404, no publica |

Cómo se mapearon los endpoints, y cuántos son, está en {doc}`verificacion`.

La ausencia de `security.txt` refuerza lo que ya dice la política de seguridad: no hay canal
publicado de divulgación de vulnerabilidades, así que va directo a la Corporación
Administrativa.

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

  Vale la pena decir en qué se distingue este proyecto de lo que esa frase describe: un
  régimen sostenido de una petición cada 5 segundos con una ráfaga acotada a 4, una causa a la
  vez, sin persistencia y sin barrido. No es extracción masiva por diseño, y las dos
  constantes del ritmo están verificadas por un job de CI. Si aun así la institución decide
  cerrar la consulta automatizada, la respuesta es acatar.
- **Puede publicarse la Política de IA del Poder Judicial.** Si define algo incompatible, este
  proyecto se ajusta o se retira.

## Cómo influir en esto

La hoja de ruta la mueve el uso real, no la lista de deseos del autor. Lo más útil:

- Reportar un **dato incorrecto** (máxima prioridad de todas)
- Reportar que **la plataforma cambió**
- Pedir una **competencia** con una causa pública que sirva de fixture
- Contar en Discusiones **qué te falta** para poder usarlo

## Dónde se fue lo que estaba acá

Esta página tenía 1.159 líneas y era seis documentos. Los anclajes de abajo se conservan
porque un enlace publicado a `roadmap.html#...` seguiría existiendo y llevaría al inicio de la
página **sin avisar**, que es peor que un 404: un enlace roto se nota y uno que va al lugar
equivocado, no.

Son objetivos explícitos y no encabezados: un encabezado por cada sección movida rearmaría el
archivo que este corte vino a deshacer, y además `docutils` le pone un `id` a toda sección,
así que también hacían falta los de nivel 4.

(endpoints-del-buscador-mapeados-y-sin-ejecutar)=
(los-diez-buscadores)=
(los-dos-lados-del-exhorto-medidos)=
(mapeado-pero-nunca-ejecutado)=
(sin-cubrir-del-todo)=
(verificado-contra-el-sistema-real)=
(verificado-solo-contra-fixtures)=

(que-esta-verificado-y-que-no)=
(reglas-de-la-plataforma-ya-mapeadas)=
(sobre-los-identificadores-de-causa-en-esta-documentacion)=
### Se fueron a {doc}`verificacion`

- Endpoints del buscador, mapeados y sin ejecutar
- Los diez buscadores
- Los dos lados del exhorto, medidos
- Mapeado pero nunca ejecutado
- Sin cubrir del todo
- Verificado contra el sistema real
- Verificado sólo contra fixtures

(api-de-boostr)=
(causalerta)=
(competencias)=
(del-mismo-catalogo-que-mas-sirve-y-que-se-rechaza)=
(deteccion-de-cambios-el-diseno-que-ya-existe)=
(el-calendario-de-dias-habiles-la-pieza-que-falta-para-cerrar-el-circulo)=
(el-contexto-gremial)=
(el-diseno-de-su-documentacion-y-que-se-copio)=
(herramientas-chilenas-que-tocan-lo-mismo)=
(jurisprudencia-lo-que-queda-del-buscador)=
(las-diligencias-de-cobranza-no-publican-fecha)=
(las-diligencias-de-cobranza-viven-en-su-propio-panel)=
(lo-que-falta-medido)=
(los-paneles-del-detalle-que-ya-llegan-y-se-tiran)=
(modales-de-la-oficina-judicial-virtual-sin-usar)=
(programacion-de-sala)=
(que-se-toma-de-cada-una)=
(servidores-mcp-juridicos)=
(automatizador-legal)=
(webscrapthings)=

(que-mas-existe)=
### Se fueron a {doc}`ecosistema`

- API de Boostr
- CausAlerta
- Competencias
- Del mismo catálogo: qué más sirve y qué se rechaza
- Detección de cambios: el diseño que ya existe
- El calendario de días hábiles: la pieza que falta para cerrar el círculo
- El contexto gremial
- El diseño de su documentación, y qué se copió
- Herramientas chilenas que tocan lo mismo
- Jurisprudencia: lo que queda del buscador
- Las diligencias de cobranza no publican fecha
- Las diligencias de cobranza viven en su propio panel
- Lo que falta, medido
- Los paneles del detalle que ya llegan y se tiran
- Modales de la Oficina Judicial Virtual sin usar
- Programación de Sala
- Qué se toma de cada una
- Servidores MCP jurídicos
- `automatizador-legal`
- `webscrapthings`

(sobre-cii-best-practices)=
(sobre-fuzzing)=

(hallazgos-de-openssf-scorecard-que-siguen-abiertos)=
### Se fueron a {doc}`cumplimiento`

- Sobre `CII-Best-Practices`
- Sobre `Fuzzing`
