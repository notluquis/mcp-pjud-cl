# Hoja de ruta y estado de verificación

## Qué está verificado y qué no

Esta tabla es lo más importante de la página. Distingue tres cosas que suelen confundirse:
lo que se probó **contra el sistema real**, lo que sólo se probó **contra fixtures**, y lo que
está **mapeado en el código de la plataforma pero nunca ejecutado**.

### Verificado contra el sistema real

| Qué | Cómo se verificó |
|---|---|
| Búsqueda de causas en **laboral** | Una causa real, columnas confirmadas, con fixture propia |
| Búsqueda de causas en **cobranza** | Ídem, y publica RUC que civil no tiene |
| El detalle de cobranza existe y sus columnas son otras | `historiaCob`, `diligenciaCob`, `litigantesCob`, `deudaCob`, `liquidacionCob`. Trae `Estado Firma` y no trae `Foja` ni `Georref.` |
| Una búsqueda del buscador de fallos tarda 47,8 s, y hasta 177,0 s | Contra 4,3 s de la página del mismo host. Es Solr con facetas sobre más de un millón de documentos. Los 47,8 s eran una sola muestra, y tomarla por techo dejó el timeout en 90 s: con eso, tres citas que respondían en 81, 102 y 39 segundos se daban por perdidas |
| Búsqueda de causas en **suprema** y **Cortes de Apelaciones** | Las cuatro búsquedas de cada una. Lo que las bloqueaba era `radio-group`, el radio RIT/RUC del formulario, que las otras cuatro competencias toleran ausente |
| Qué exige cada competencia para acotar | `tribunal` en las cuatro de primera instancia, `corte` en apelaciones (avisa "Por favor seleccione una Corte"), nada en suprema |
| Buscador de fallos de Cortes de Apelaciones | Rol 1504-2019, tres sentencias. Dos consultas al mismo buscador tardaron 115,6 s y 177,0 s |
| Buscador de fallos Laborales | 20 de agosto de 2026, texto libre: 106.068 sentencias visibles y las tres primeras con rol, caratulado, fecha y juzgado bien mapeados. Tardó **1,6 s**, o sea el techo de espera está dimensionado por Suprema y no por el resto |
| Códigos de cobranza | Competencia 6, tribunal `1332` (Jdo. de Cobranza Laboral y Previsional de Concepción), tipos de causa `A C D E J L P R` |
| Entrada pública sin Clave Única | `sesion-consultaunificada.php` → 200 |
| Derivación de prefijo de rutas y token | Tres sesiones distintas, token distinto en cada una |
| Búsqueda por RIT en civil | E-468-2026 y C-1156-2026 |
| Detalle de causa | Ambas causas |
| La lectura combinada del detalle | C-1156-2026 el 20 de agosto de 2026: 6 peticiones, todas 200, con los dos cuadernos, 23 actuaciones, 6 litigantes, cero notificaciones y el exhorto a Chillán. `liquidaciones` y `materias` llegaron en nulo, que es lo correcto: civil no publica esos paneles |
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

Las rutas se extrajeron del código de la plataforma y siguen sin ejecutarse. El cliente las
rechaza en vez de adivinar sus parámetros:

- El panel `diligenciaCob`, donde cobranza guarda de verdad sus diligencias
- `familia`, que la propia plataforma declara reservada y sólo entrega por Clave Única
- `detalleExhortos.php`, `causaOrigenCivil.php`, `geoReferenciaCivil.php`
- `anexoCausaCivil.php` y la descarga de documentos por `docuN.php`
- `receptorCivil.php`, que devuelve la tabla de **retiro** de documentos, no la de
  actuaciones. Se ejecutó una vez y se descartó por no ser lo que se buscaba

Las cuatro búsquedas (`consultaRit*`, `consultaNombre*`, `consultaJuridica*` y
`consultaFecha*`) salieron de esta lista: están verificadas en las seis competencias que el
servidor expone.

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
un listado**. Doce causas son unas sesenta peticiones, y bajo el régimen sostenido de una cada
5 segundos eso son unos cinco minutos: la ráfaga alcanza para la primera causa y no cambia el
total. La respuesta correcta es devolver el listado para que el usuario elija cuál abrir.

### 0.3: jurisprudencia — hecho parcialmente

Existe `buscar_jurisprudencia` contra el buscador de Corte Suprema. Lo que falta está en la
sección de jurisprudencia, más abajo.

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

- **`diligenciaCob`**: cobranza tiene ministro de fe pero sus diligencias NO viven en la tabla
  de Historia. `historiaCob` trae `Actuación`, `Resolución` y `Escrito`, nunca "Actuación
  Receptor". Las diligencias están en un panel aparte con estructura propia (`Estado
  Diligencia`, `Tipo Diligencia`, `Destinatario`, `Responsable`). Hoy `actuaciones_receptor`
  rechaza cobranza en vez de devolver una lista vacía, que es lo correcto mientras el panel no
  esté medido.

  **Medido, y la respuesta es que hoy no sirve.** De cinco causas de cobranza, sólo una trae
  filas en ese panel, y sus tres diligencias traen `31/12/1969` en la columna de fecha: el
  epoch, o sea el valor cero renderizado. Ninguna trae la fecha doble que este proyecto lee en
  civil. Construir sobre eso entregaría actuaciones sin la fecha que corre los plazos, que es
  peor que no entregarlas. Queda a la espera de encontrar una causa donde el panel sí publique
  fechas.

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

- `litigantesCiv`: quiénes son parte y con qué calidad. **Hecho**, en las cinco competencias
  con detalle mapeado
- `notificacionesCiv`: con su propio estado y su propia fecha de trámite. **Hecho**
- `liquidacionCob` y `materiasLab`: cuánto se debe, y qué se litiga. **Hecho**
- `escritosCiv`: los presentados, y cuáles siguen por resolver. Falta
- `exhortosCiv`: el exhorto visto desde el tribunal de origen. **Hecho**
- `piezasExhortoCiv`: falta, y no por costo. El panel trae seis filas reales en una respuesta
  y **no existe** en las dos de C-1156, que sí traen el exhorto. Cuándo lo renderiza el sitio
  no está entendido, y mapearlo con esa duda haría fallar una causa que hoy funciona

Lo que falta importa más de lo que parece: mientras no estén, la respuesta del detalle NO es
el expediente completo, y su contrato tiene que decirlo para que nadie lea la ausencia de un
escrito como que la causa no lo tiene.

#### Los dos lados del exhorto, medidos

Parecía que `piezasExhortoCiv` faltaba a veces. No es eso: **el juego de paneles depende de si
la causa ES un exhorto**, y las dos mitades se ven desde causas distintas.

| Causa | `Proc.` | `exhortosCiv` | `piezasExhortoCiv` |
|---|---|---|---|
| C-1156-2026, 2º Juzgado Civil de Concepción (tribunal 162) | ordinaria | 1 fila | **sin panel** |
| E-468-2026, 3º Juzgado Civil de Concepción (tribunal 163) | `Exhorto` | 0 filas | **6 filas** |

Medido en vivo el 20 de agosto de 2026, cuatro peticiones. E-468-2026 es ella misma un
exhorto: su cabecera dice `Proc.: Exhorto`, `Etapa: 0 Exhorto`, y nombra a `C-15411-2025` como
causa de origen. Sus seis piezas son la tramitación que el tribunal de origen despachó junto
con el exhorto (`Ordena despachar mandamiento`, `Exhórtese`, `Curso progresivo a los autos`),
o sea **lo que el tribunal que recibe tuvo a la vista**.

`exhortosCiv` se lee desde el origen y ya está cubierto. `piezasExhortoCiv` se lee desde el
destino y no lo está, y mapearlo tiene una decisión de contrato antes que de código: hoy
`None` significa "esta COMPETENCIA no publica el panel", y acá haría falta decir "esta CAUSA
no es un exhorto", que no es lo mismo. Sobrecargar `None` con los dos sentidos es exactamente
la distinción que este proyecto existe para no borrar.

Lo que probablemente lo resuelva es la **cabecera de la causa**, que hoy no se lee de ninguna
competencia: trae `Proc.`, `Etapa`, `Estado Proc.`, `Ubicación` y el tribunal, y de ahí sale si
la causa es un exhorto sin tener que inferirlo de la presencia de un panel.

**Una petición cada uno, con su intervalo.** Son modales que la plataforma carga aparte, y hay
que contarlos en el tiempo total:

- `modal/detalleExhortos.php`, que la fila del exhorto invoca con su propia referencia
- `modal/causaOrigenCivil.php`

### 0.6: Programación de Sala

El "¿cuándo me ven?", que hoy no se cubre y las dos herramientas comerciales sí. Los campos
están mapeados leyendo `automatizador-legal`: `progComp`, `progCorte`, `progRolCausa`,
`progEraCausa`, `progTipoCausa`, botón `btnProgConsulta`, tabla `dtaTableDetalleProgSala`.

Ninguno verificado contra el sistema real todavía, así que vale la misma regla de siempre: se
mide antes de exponerlo.

### 0.7: documentos

- Descarga de documentos por folio vía `docuN.php`

**Decisión pendiente y no trivial:** descargar un PDF significa traer datos de terceros a
disco. Eso cambia el perfil de retención y entra de lleno en la Ley 21.719. Probablemente
requiera consentimiento explícito por llamada, y ruta de destino elegida por el usuario.

### 0.8: el detalle de las competencias ya buscables — hecho, salvo penal

Las cuatro se pidieron y se midieron sobre una causa real. Tres quedaron mapeadas y expuestas
por `obtener_detalle_causa`; penal no, y la razón es la de siempre.

| Competencia | Panel | Qué la distingue |
|---|---|---|
| `laboral` | `movimientoLab` | Como civil, con `Estado` donde civil pone `Foja` |
| `suprema` | `movimientosSup` | Sin `Etapa` ni `Georref.`; agrega `Salas`, `Correlativo` y el año |
| `apelaciones` | `movimientosApe` | Llama `Descripción` y `Fecha` a lo que civil llama `Desc. Trámite` y `Fec. Trámite`, y su georreferencia se escribe `Georeferencia` |
| `penal` | `historiaPen` | **Cero filas**, igual que sus otros tres paneles |

**Penal queda sin mapear a propósito.** El panel existe y sus encabezados están a la vista, pero
la causa medida no trae ninguna fila: declarar sus columnas sería escribir un mapa que nada
comprobó. Hace falta encontrar una causa penal con historia y volver a medir.

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

El mecanismo ya no es el obstáculo: `juris.BUSCADORES` es una tabla que mapea nombre del
modelo a campo Solr, igual que `parser.COMPETENCIAS` para las causas, y `parse_sentencias`
recibe el buscador. Agregar uno es leer su `parametros_buscador` y llenar una fila.

Y hay una razón de uso para priorizar dos. Contadas el 17 de agosto de 2026 sobre las citas de
cuatro casos reales que el titular del proyecto aportó, 84 en total: **32 son de Cortes de
Apelaciones y de juzgados laborales**, o sea alrededor de un tercio de lo que alguien necesita
verificar cae fuera precisamente por estos dos buscadores. Rinden más que cualquier competencia
nueva de la Oficina Judicial Virtual.

Esa cuenta no lleva constante ni guardia en CI, a diferencia de las mediciones de la
plataforma, y la razón es que no es un dato de la plataforma: es el recuento de un conjunto
privado de documentos que el repositorio no contiene ni debe contener. Fijarlo en código
fingiría una verificabilidad que no existe. Lo que corresponde es lo que está escrito: la
fecha, el tamaño del conjunto y de dónde salió, para que quien lea sepa qué peso darle.

| Buscador | Estado |
|---|---|
| Corte Suprema | **Verificado.** `id_buscador` 528 |
| Corte de Apelaciones | **Verificado.** Rol 1504-2019, tres sentencias |
| Civiles | Mapeado, sin ejecutar |
| Laborales | **Verificado** el 20 de agosto de 2026: 106.068 sentencias visibles, y responde en **1,6 s** contra los 47,8 a 177,0 s de Suprema |
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

- **Texto completo: hecho**, con la forma que la decisión exigía. Está en
  `obtener_texto_sentencia`, aparte de la búsqueda y de a una sentencia por llamada. La razón
  es medible: una sentencia de trece páginas son 25.473 caracteres, así que devolver diez con
  cada búsqueda serían 250.000. La búsqueda entrega `texto_preview` y la extensión en palabras
  y páginas, que suele bastar para decidir si vale pedir el resto.

  Sobre los datos personales: la respuesta declara `anonimizada` y `fuente`, o sea si lo
  entregado es la versión con los datos suprimidos por el tribunal y de cuál de los dos campos
  salió. Y si la sentencia existe pero está reservada, se levanta en vez de devolver un texto
  vacío que se leería como una sentencia sin contenido.
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
`consultaUnificada.php`, donde el sitio nombra 189 veces un `.php`, o sea 102 rutas distintas.
Ése es el método a repetir cuando la plataforma cambie, y las dos cifras salen de contarlas
sobre la fixture, no de recordarlas.

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

  Vale la pena decir en qué se distingue este proyecto de lo que esa frase describe: un
  régimen sostenido de una petición cada 5 segundos con una ráfaga acotada a 4, una causa a la
  vez, sin persistencia y sin barrido. No es extracción masiva por diseño, y las dos
  constantes del ritmo están verificadas por un job de CI. Si aun así la institución decide
  cerrar la consulta automatizada, la respuesta es acatar.
- **Puede publicarse la Política de IA del Poder Judicial.** Si define algo incompatible, este
  proyecto se ajusta o se retira.

## Qué más existe

Revisado el 17 de agosto de 2026. Se anota para no re-descubrirlo, y porque si algo de esto
cubre tu caso mejor, conviene que lo uses en vez de esto.

Este proyecto no es el primero que consulta al Poder Judicial de Chile por programa, y decirlo
importa: parte de lo que hay cubre bastante más superficie. Lo que sigue es lo medido, no una
comparación de folleto.

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

Revisadas a fondo el 17 de agosto de 2026: las dos de código abierto leyendo su código, las
dos comerciales leyendo lo que documentan. Se anota con detalle porque marcan el piso: lo que
ellas ya hacen no es una idea para el roadmap, es lo mínimo.

#### CausAlerta

Es el competidor real, y cubre mucho más superficie que esto. SaaS de gestión completa, con
seguimiento diario y resumen por correo.

| | |
|---|---|
| Precio | Gratis hasta 3 causas; 6.500, 10.400 y 31.200 pesos más IVA al mes |
| Competencias | Civil, cobranza, laboral, familia, libre competencia, constitucional, apelaciones y suprema |
| Qué sigue | "Historia, escritos por resolver, **movimientos de receptor** y estado procesal" |
| Además | Banco de jurisprudencia, programación semanal de salas en Cortes de Apelaciones, calendario de plazos y audiencias, importación masiva desde la Oficina Judicial Virtual o Excel, documentos y plantillas, cobros por cliente, registro de horas, equipos |

Conviene subrayar la tercera fila: **sí dice cubrir los movimientos de receptor**. Lo que no
dice, y no se puede saber desde afuera, es si separa la fecha de diligencia de la de registro
o si presenta una sola. Afirmar que no lo hace sería inventar.

#### API de Boostr

Otro producto, no un competidor directo: resuelve "¿esta persona tiene causas en alguna parte
del país?", no "¿qué pasó en esta causa?".

| | |
|---|---|
| Precio | 2.000 pesos **por consulta**, mínimo 10.000 (cinco consultas) |
| Modelo | Asincrónico con `operation_id` y notificación por URL, porque barre todos los tribunales |
| Busca por | RUT en civil, nombre completo en penal |
| Cubre | Penal, civil y apelaciones. Excluye familia y causas reservadas |
| Advertencia propia | "No nos hacemos responsable de la información entregada, todo proviene directamente desde el Poder Judicial" |

Su documentación no describe los campos de cada causa, así que no hay evidencia de que llegue
al detalle ni a las actuaciones.

#### `automatizador-legal`

Ataca un dato que este proyecto no cubre: la **Programación de Sala**, o sea cuándo se ve una
causa. Sin licencia, o sea sin derecho de uso.

Su arquitectura es el contraejemplo de la nuestra, y su README lo dice sin rodeos: Playwright
corre dentro de Docker pero controla un Brave real en el Mac por CDP, "para evitar bloqueos"
y para que una persona pueda resolver el captcha a mano. Entrada por Excel en Google Drive,
salida por correo, orquestado con n8n.

Los campos del formulario quedan mapeados de paso: `progComp`, `progCorte`, `progRolCausa`,
`progEraCausa`, `progTipoCausa`, botón `btnProgConsulta`, tabla `dtaTableDetalleProgSala`.

#### `webscrapthings`

Los bots de ParalegApp. Selenium con la API de la versión 3 (ya retirada), persistencia en
Django, sin licencia y sin mantención desde 2025. Un directorio `botsClave` indica que opera
con Clave Única, o sea del lado autenticado.

Es el que más pestañas cubre, y ahí está lo aprovechable:

| Pestaña, con el selector que usa **su** código | Equivalente acá |
|---|---|
| `#Historia` | `historiaCiv`, cubierto |
| Selector de cuadernos | cubierto |
| `#Litigantes` | `litigantesCiv`, cubierto |
| `#Notificaciones` | `notificacionesCiv`, cubierto |
| `#Escritos` | `escritosCiv`, **no** |
| `#Exhorto` | `exhortosCiv`, **no** |
| `#Diligencias` en laboral, con descarga de PDF | sin equivalente, **no** |

Los identificadores de la izquierda son los suyos y no calzan con los nuestros: operan sobre la
vista autenticada con Clave Única, que tiene otro marcado. Los de la derecha son los que trae
la consulta pública, verificados contra la respuesta real.

Y un dato que acota la comparación: la palabra "receptor" no aparece ni una vez en sus 400 KB
de scrapers. Cubre más pestañas, pero no la que a este proyecto le da sentido.

Una comprobación que se intentó y **no** sirvió: buscar en el código de GitHub los nombres de
los endpoints de la plataforma. La consulta de control (`oficinajudicialvirtual.pjud.cl`)
devolvió cero, o sea el buscador no indexa bien cadenas con puntos, y los ceros de las demás
consultas no significaban nada. Queda anotado para que nadie lo repita creyendo que mide algo.

### Qué se toma de cada una

Lo honesto primero: **en superficie estamos muy atrás.** Una competencia contra ocho, sin
seguimiento, sin alertas, sin documentos, sin calendario. Eso no se disimula, se anota.

Lo que sí se puede sostener, y hay que sostenerlo con evidencia y no con adjetivos:

| Dónde ser mejores | Por qué es sostenible |
|---|---|
| Las dos fechas como campos distintos y tipados | Nadie documenta esa separación. La salida es un esquema, no una pantalla: quien la consume no puede confundirlas |
| Declarar lo que falta | `ocultas` en jurisprudencia y `ResultadosTruncados` en listados. Ninguna otra declara completitud, y la plataforma dejó de hacerlo |
| Fallar ruidoso | Un servicio de alertas diarias que deja de parsear manda un resumen vacío que se lee como "no pasó nada". Acá eso levanta excepción |
| Ser auditable | Código a la vista, bitácora de cada petición, y el intervalo verificado por CI. Un SaaS cerrado no permite comprobar ninguna de las tres |
| No guardar nada de terceros | Sin cuenta, sin base de datos, sin retención bajo la Ley 21.719 |
| Hablar MCP | Ninguna de las cuatro lo hace. La herramienta llega adentro del asistente que el abogado ya usa, no a otra pestaña más |

Y lo que hay que copiar sin orgullo, en este orden, porque marca el piso de lo que un abogado
espera:

1. **Litigantes, escritos y exhortos** del detalle de causa. `webscrapthings` los cubre desde
   2025 y son una pestaña más de la misma respuesta que ya se pide.
2. **Programación de Sala**, el "¿cuándo me ven?". Los campos ya están mapeados arriba.
3. **Más competencias.** Ocho contra una es la brecha más grande, y cobranza sigue siendo la
   primera por tener actuaciones de ministro de fe.
4. **Detección de cambios**, que ya está más abajo sin versión asignada. Es lo que vende
   CausAlerta y lo que exige resolver antes la pregunta de retención de datos.

### Lo que falta, medido

No es una lista de deseos: cada línea sale de leer la respuesta real, la fixture o el código
del que ya lo hace. Se anota con los nombres exactos para que implementarlo no cueste
re-descubrirlos.

#### Los paneles del detalle que ya llegan y se tiran

El detalle de causa devuelve **una sola respuesta** que trae todos estos paneles. Cubrirlos no
cuesta ni una petición más, y por eso fueron lo primero. Quedan los dos del exhorto y los
escritos.

Conviene no confundirlos con los modales de la sección siguiente: aquéllos **sí** cuestan una
petición cada uno, con su intervalo. Lo gratis es sólo lo de esta tabla.

| Panel | Columnas exactas |
|---|---|
| `litigantesCiv` | `Participante`, `Rut`, `Persona`, `Nombre o Razón Social`. **Cubierto** |
| `escritosCiv` | `Doc.`, `Anexo`, `Fecha de Ingreso`, `Tipo Escrito`, `Solicitante` |
| `notificacionesCiv` | `ROL`, `Est. Notif.`, `Tipo Notif.`, `Fecha Trámite`, `Tipo Part.`, `Nombre`, `Trámite`, `Obs. Fallida`. **Cubierto** |
| `exhortosCiv` | `Rol Origen`, `Tipo Exhorto`, `Rol Destino`, `Fecha Ordena Exhorto`, `Fecha Ingreso Exhorto`, `Tribunal Destino`, `Estado Exhorto`. **Cubierto** |
| `piezasExhortoCiv` | `Folio`, `Doc.`, `Cuaderno`, `Anexo`, `Etapa`, `Támite`, `Desc. Támite`, `Fec. Támite`, `Foja` |

Tres advertencias que sólo se ven mirando la respuesta:

- **`piezasExhortoCiv` trae los encabezados con errata**: dice `Támite` y `Fec. Támite`, sin la
  erre. Un parser que busque `Trámite` no encuentra nada y devuelve vacío. Hay que calzar con
  el texto que la plataforma emite, no con el correcto.
- **`notificacionesCiv` tiene su propia `Fecha Trámite`, y no se comporta como la de la
  historia.** La inferencia por el nombre de las columnas (`Est. Notif.`, `Obs. Fallida`) era
  que respondía "¿la notificación resultó?", la pregunta anterior a "¿cuándo corre el plazo?",
  y midiéndola resultó ser eso: tres filas reales, ninguna con el formato de fecha doble. La
  advertencia que queda es otra: **incluye las NO practicadas**, que se distinguen por
  `estado`, y una fila pendiente no hizo correr ningún plazo.
- **`litigantesCiv` trae RUT de personas naturales.** Es el panel con más carga de datos
  personales de todo el detalle, y su fixture tendrá que anonimizarse como el resto.

Estado de la evidencia: `exhortosCiv` está verificado con datos reales (C-1156-2026 despacha
E-875-2026 al 1º Juzgado Civil de Chillán, estado `Generado`). De `escritosCiv` se conoce la
estructura, pero **las causas de la muestra lo traen vacío**: no hay fila real que sirva de
fixture todavía.

#### Modales de la Oficina Judicial Virtual sin usar

Extraídos de `consultaUnificada.php`, ninguno ejecutado:

| Ruta | Qué daría |
|---|---|
| `modal/detalleExhortos.php` | El exhorto visto desde el tribunal exhortado |
| `modal/causaOrigenCivil.php` | La causa de origen cuando ésta viene de otra |
| `modal/geoReferenciaCivil.php` | Las coordenadas de la actuación, no sólo si existen |
| `modal/anexoCausaCivil.php` | Documentos adjuntos de la causa |
| `modal/anexoCausaSolicitudCivil.php` y `anexoCausaSolEscritoCivil.php` | Adjuntos de solicitudes y escritos |
| `modal/anexoCausaSolicitudCivilSII.php` | Adjuntos de solicitudes del Servicio de Impuestos Internos |

#### Programación de Sala

Vive fuera de `consultaUnificada.php`: cuelga del menú lateral de `home/index.php`, o sea es
otra entrada y hay que mapear su sesión aparte. Los campos salen de leer `automatizador-legal`,
y ninguno está verificado contra el sistema real:

`progComp` (competencia), `progCorte`, `progRolCausa`, `progEraCausa`, `progTipoCausa`, botón
`btnProgConsulta`, tabla de resultados `dtaTableDetalleProgSala`.

Un detalle que ahorra un error: cuando no hay audiencias, la tabla devuelve **una sola celda**
con el texto `Ningún dato disponible en esta tabla`. Hay que reconocerlo, porque confundirlo
con un fallo de parseo, o al revés, es el mismo error de siempre.

#### Jurisprudencia: lo que queda del buscador

| Ruta | Parámetros medidos | Qué daría |
|---|---|---|
| `/busqueda/buscar_sentencias` con `id_sentencia` | `_token`, `id_sentencia` | El detalle completo de una sentencia, con su texto |
| `/busqueda/webservices` con `cod_ws=6` | `datos` (la sentencia), `numero_pestanna` 2 o 3 | Las instancias anteriores. Una sentencia de Suprema arrastra la de Apelaciones y la del tribunal de origen |
| `/busqueda/webservices` con `cod_ws=1` | `url_webservice` a `leychile.cl/Consulta/obtxml` | Las normas citadas, resueltas contra LeyChile |
| `/busqueda/listar_ids_relacionados` | `rol_era` | Sentencias relacionadas |
| `/busqueda/arbol_json` | `filtros`, `id_buscador` | Índice temático de materias y submaterias |
| `/busqueda/documentos` e `/busqueda/imprimir` | por medir | El documento y su versión imprimible |
| `/detalle_sentencia/terminos_juridicos` | por medir | Glosario, que el sitio usa para marcar términos en el texto |

Lo de `numero_pestanna` es lo más valioso y no se ve desde la interfaz: **la cadena procesal
completa de una causa cabe en una consulta**. `parametros_buscador` lo confirma con
`ws_2_visible` y `ws_3_visible`, etiquetados "Corte Apelaciones" y "Tribunales".

#### Detección de cambios: el diseño que ya existe

`webscrapthings` resuelve esto con un resumen diario, y su plantilla vale como punto de
partida porque marca **qué dimensión cambió**, no sólo que algo cambió:

| Causa | Caratulado | Inicio | Actualización | Estado | Etapa | Cuaderno | Historia | Litigante | Notificación | Escrito | Exhorto |
|---|---|---|---|---|---|---|---|---|---|---|---|

Las últimas ocho columnas son una X. Dos cosas se pueden hacer mejor, y las dos se ven en su
código: marca la dimensión pero no **qué** cambió dentro, y decide esas X buscando la palabra
dentro de un comentario en texto libre (`'Estado' in caso.caso.last_chenge_coment`), que falla
en silencio si el texto cambia. Acá lo que corresponde informar no es "cambió la Historia":
es qué folio apareció, y si trae una fecha de diligencia que echó a correr un plazo.

Sigue vigente lo que bloquea esto: implica persistir datos de terceros, o sea entra de lleno
en la Ley 21.719.

#### Las diligencias de cobranza no publican fecha

Medido sobre filas reales, y cierra la pregunta que la sección de abajo dejaba abierta.
`diligenciaCob` sí trae diligencias, y son las que importan:

```
cumplida | Embargo en cuenta corriente | 31/12/1969 | No Asignado | MONICA ...
cumplida | Alzamiento embargo en cta cte | 31/12/1969 | No Asignado | MONICA ...
```

**`31/12/1969` es el epoch de Unix** visto desde una zona al oeste de Greenwich: el valor cero
impreso como fecha. O sea la columna está vacía. Tres diligencias de una causa real, las tres
con el mismo cero.

Consecuencia para el proyecto: en cobranza hay diligencias de embargo, con su estado y con un
responsable identificado, **y sin fecha de diligencia publicada**. Que es justamente el dato por
el que existe este proyecto. Cobranza queda buscable y con detalle, y no puede entregar lo que
civil sí entrega, por una razón de la plataforma y no del cliente.

Y de paso apareció una trampa que ahora tiene guardia: devolver `1969-12-31` como fecha real
sería peor que devolver nulo, porque alguien computaría un plazo desde ahí. `_FECHAS_CENTINELA`
las descarta. Es el error del proyecto con el signo invertido: no falta un dato, sobra uno que
tiene forma de dato.

#### Las diligencias de cobranza viven en su propio panel

Medido sobre una respuesta real, y corrige lo que esta misma hoja afirmó antes: en cobranza las
diligencias del ministro de fe **no están en la tabla de Historia**. Sus trámites son
`Actuación`, `Resolución` y `Escrito`, nunca "Actuación Receptor".

Están en `diligenciaCob`, que tiene estructura propia:

```
Doc. Ida | Doc. Vta. | Estado Diligencia | RIT | RUC | Tipo Diligencia | Fecha Trámite | Destinatario | Responsable
```

Dos cosas que hay que mirar antes de leerlo: si `Fecha Trámite` trae el formato de fecha doble
como en civil, y qué significa `Responsable`, que probablemente identifica al receptor.

Mientras no esté medido, pedir actuaciones de cobranza se **rechaza** en vez de devolver la
lista vacía que la Historia produciría: esa lista se leería como "no hubo actuaciones" cuando
lo cierto es "no las estoy leyendo". Es el mismo falso negativo que motivó el proyecto, y
estuvo brevemente dentro de él.

#### El calendario de días hábiles: la pieza que falta para cerrar el círculo

Revisando el catálogo completo de Boostr apareció lo que este proyecto no tiene y necesita más
que ninguna otra cosa. Su API de feriados responde por fecha y distingue el tipo:

```json
{"status":"success","date":"2025-01-01","is_holiday":true,
 "data":{"title":"Año Nuevo","type":"Civil","inalienable":true,"extra":"Civil e Irrenunciable"}}
```

Por qué importa acá: hoy la herramienta entrega la **fecha de diligencia**, que es el punto de
partida del plazo. Lo que el abogado quiere saber es la fecha de término, y para eso hace falta
el calendario de días inhábiles. Sin él, el dato que este proyecto rescata queda a mitad de
camino.

Y por qué **no** basta con enchufar un calendario:

- El cómputo depende de la regla procesal aplicable, no sólo del almanaque, y esa regla varía
  según la materia y según el tipo de plazo. Decir cuál rige en cada caso es calificación
  jurídica, no aritmética.
- Equivocarse acá es peor que no responder. Entregar "el plazo vence el 12" con un día de
  error produce exactamente la pérdida que el proyecto existe para evitar, y con la confianza
  añadida de venir con forma de respuesta.

Esto último no es prudencia retórica: este documento describe software, y una afirmación sobre
cómo se cuenta un plazo la va a leer un abogado como la posición del proyecto. Acá no se
sostiene ninguna, a propósito.

De modo que la dirección probable no es "calcular el plazo" sino **entregar los insumos con la
misma honestidad que el resto**: la fecha de diligencia, los días inhábiles del período, y la
cuenta en días corridos y en hábiles, dejando la calificación jurídica a quien firma. La
decisión queda abierta y es de las que conviene discutir antes de escribir código.

Fuente del calendario: está por decidir. Boostr lo ofrece pero es un tercero de pago. Los
feriados chilenos están fijados por ley, o sea el dato es público y cabe en el paquete sin
depender de nadie. La norma base es la
[Ley 2.977](https://www.bcn.cl/leychile/navegar?idNorma=23530) de 1915, más las posteriores
que la modifican; verificado el 17 de agosto de 2026.

Ese "verificado" es lo único que se puede ofrecer acá, y conviene decir por qué: la suite no
consulta la red por diseño, así que **ninguna cita legal de esta documentación puede
comprobarse en CI**. Lo que sí se comprueba es que venga con enlace y con la fecha en que
alguien la miró, que es lo que permite a quien lea juzgar si sigue vigente. Vale para todas las
leyes que este proyecto cita, que están en una tabla única en la página de cumplimiento.

#### Del mismo catálogo: qué más sirve y qué se rechaza

| Servicio de Boostr | Decisión |
|---|---|
| Feriados | **Sirve**, ver arriba |
| UTM y UF del día y por año | **Sirve.** Las cuantías y multas judiciales se expresan en esas unidades; hoy la salida las deja como texto |
| Generador de dígito verificador | **Sirve, y se hace acá.** La búsqueda por RUT de empresa lo exige, y calcularlo son cinco líneas: no amerita una dependencia ni una llamada |
| Propiedades y vehículos por RUT | **Se rechaza.** Es búsqueda de bienes embargables, y aunque calce con el cuaderno de apremio, convierte la herramienta en un buscador de patrimonio de personas |
| PEP, Interpol, defunción, AFP, AFC | **Se rechaza.** Es perfilamiento de personas, que ya está en la lista de usos que el proyecto no acepta |

Vale anotar por qué se escriben también los rechazos: son las funciones que alguien va a pedir
tarde o temprano, y tener la respuesta escrita evita discutirla de nuevo cada vez.

#### Competencias

Ocho contra una es la brecha más grande. Cobranza sigue primera por tener actuaciones de
ministro de fe; de ella ya se sondeó que el panel es `historiaCob`, que agrega una columna
`Estado Firma`, que no trae `Foja`, y que existe un panel `diligenciaCob`.

### El diseño de su documentación, y qué se copió

La documentación de Boostr está hecha con [readme.com](https://readme.com/), que es una
plataforma de pago especializada en referencias de API. Sus piezas, leídas del propio HTML:

| Pieza | Qué hace |
|---|---|
| `rm-Sidebar` con 98 enlaces en 18 grupos plegables | Navegación por secciones, con el método HTTP como insignia |
| `Playground` | Panel para probar la llamada desde la página |
| `LanguagePicker` y `CodeTabs` | El mismo ejemplo en Shell, Node, Python, Ruby y PHP |
| `APIResponseSchemaPicker` | Elegir el esquema de respuesta por código de estado |
| `Param` con nombre, tipo y descripción | Los parámetros como bloques, no como tabla |
| `ThemeToggle` | Modo claro y oscuro |

Lo que se adoptó, traducido a lo que este proyecto es:

- **Pestañas por cliente en vez de por lenguaje.** Acá no hay cinco lenguajes: hay Claude Code,
  Claude Desktop, Cursor, VS Code y Codex, y cada uno quiere un formato distinto. Es el mismo
  problema que resuelve su `LanguagePicker`. De paso quedó documentada una trampa real: VS Code
  usa la clave `servers` y el resto usa `mcpServers`, así que copiar el bloque equivocado no
  funciona.
- **El esquema de cada herramienta, generado.** Es el equivalente de su
  `APIResponseSchemaPicker`, con una ventaja: no se escribe a mano. Se genera desde el servidor
  al construir la página, así que lo publicado es literalmente lo que un cliente MCP recibe por
  el protocolo, y no puede quedar viejo.
- **Botón de copiar** en cada bloque de código.

Lo que **no** se copia, y conviene decir por qué:

- **El panel para probar en vivo.** En su caso una prueba consulta su API; acá consultaría al
  Poder Judicial desde el navegador de quien lee la documentación, sin intervalo, sin
  identificación y sin bitácora. Es exactamente lo que el proyecto no hace.
- **Migrar a readme.com.** Es de pago y cerrado, y la documentación de este proyecto se publica
  también en Markdown y `llms.txt` para que un agente la lea sin atravesar HTML. Sphinx con
  Furo ya da buscador, modo oscuro y navegación; lo que faltaba eran las tres piezas de arriba.

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
