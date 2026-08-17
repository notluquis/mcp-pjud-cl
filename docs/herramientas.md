# Referencia de herramientas

Las cinco están anotadas en el protocolo como `readOnlyHint: true` y `destructiveHint: false`.

:::{note}
Las anotaciones MCP son **pistas**, no garantías verificables por el cliente. La garantía real
de que este servidor no escribe es que **el código de escritura no existe**, y hay un job de
CI que lo comprueba en cada cambio.
:::

## Directiva operativa

El servidor expone una directiva por el campo `instructions` del protocolo. Cualquier cliente
que se conecte la recibe **antes** de poder llamar una herramienta, así que la distinción
entre las dos fechas llega antes que cualquier resultado:

> Al informar fechas de actuaciones de receptor, distinguir siempre:
>
> - `fecha_diligencia`: cuándo el ministro de fe practicó la diligencia. **Es la que corre los
>   plazos procesales.**
> - `fecha_registro`: cuándo se registró en el sistema. **No** corre plazos.
>
> Suelen diferir en varios días. [...] Las causas reservadas no aparecen en la consulta
> pública: un resultado vacío no prueba que la causa no exista.

:::{note} Qué revisión del protocolo habla este servidor
La que trae el SDK de MCP instalado, que hoy es **2026-07-28**. Desde esa revisión el protocolo
es sin estado y los servidores deben implementar `server/discover`, donde éste publica su
nombre, su versión y estas herramientas.

El número no está escrito a mano: `tests/test_documentacion.py` lo compara contra
`LATEST_PROTOCOL_VERSION` del SDK, así que actualizar la dependencia y no esta página deja la
suite en rojo.
:::

## `buscar_causa_por_rit`

Busca causas por rol en la consulta pública.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `tipo` | str | Letra del rol. En civil: `C`, `V`, `E`, `A`, `F` o `I` |
| `rol` | int | Número, sin la letra ni el año |
| `anio` | int | Año, cuatro dígitos |
| `competencia` | str | Verificadas: `civil`, `laboral`, `cobranza`, `penal`, `suprema`, `apelaciones` |
| `tribunal` | int, opcional | Código del tribunal. Omitir para buscar en todos |
| `corte` | int, opcional | **Omitir salvo certeza** |
| `paginas` | int | Cuántas páginas recorrer como máximo. Al excederlo levanta excepción en vez de recortar |

:::{warning}
`corte` no tiene valor por defecto a propósito. Fijarla produce **falsos negativos**: en una
prueba real, una búsqueda con la corte puesta en Concepción omitió una causa del 11º Juzgado
Civil de Santiago que sí existía.
:::

Devuelve una lista de causas con `rol`, `fecha_ingreso`, `caratulado`, `tribunal` y una
`referencia` opaca que caduca a los 30 minutos.

```{include} _generado/buscar_causa_por_rit.md
```

:::{note} Con qué hay que acotar la búsqueda
Las tres búsquedas de abajo (nombre, RUT y fecha) exigen acotar, y **con qué depende de la
competencia**. Está medido una por una contra el sistema real:

| Competencia | Exige |
|---|---|
| `civil`, `laboral`, `cobranza`, `penal` | `tribunal` |
| `apelaciones` | `corte` |
| `suprema` | nada |

En apelaciones la plataforma responde *"Por favor seleccione una Corte para la búsqueda"* y no
entrega resultados. En suprema las tres andan sin corte ni tribunal.
:::

## `buscar_causa_por_nombre`

Busca causas por nombre de litigante.

Reglas de la plataforma, medidas probando cada combinación contra el sistema real:

- Exige **al menos dos de los tres campos de nombre** (nombre, apellido paterno, apellido
  materno). El **año no cuenta** para ese mínimo: `paterno + año` es rechazado, `paterno +
  materno` es aceptado.
- Exige **acotar la búsqueda** según la competencia (ver el cuadro de arriba). Donde el
  tribunal es obligatorio eso limita la utilidad de la herramienta: hay que saber dónde está
  la causa antes de poder buscarla.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `apellido_paterno` | str | Apellido paterno del litigante |
| `apellido_materno` | str | Apellido materno |
| `nombre` | str | Nombres |
| `anio` | int, opcional | Año de ingreso. **No cuenta** para el mínimo de dos campos |
| `competencia` | str | Verificadas: `civil`, `laboral`, `cobranza`, `penal`, `suprema`, `apelaciones` |
| `tribunal` | int | Obligatorio salvo en `suprema` y `apelaciones` |
| `corte` | int | Obligatorio en `apelaciones`. En el resto, **omitir salvo certeza** |
| `paginas` | int | Tope de páginas a recorrer |

```{include} _generado/buscar_causa_por_nombre.md
```

## `buscar_causa_por_rut_juridica`

Busca causas de una persona jurídica por su RUT. Es la **única vía para empresas**, que no
tienen Clave Única y por lo tanto no aparecen en "Mis Causas".

Exige el dígito verificador, y acotar según la competencia (ver el cuadro de arriba).

| Parámetro | Tipo | Descripción |
|---|---|---|
| `rut` | int | RUT sin dígito verificador ni puntos |
| `digito_verificador` | str | Dígito verificador: 0-9 o K |
| `anio` | int, opcional | Año de ingreso |
| `competencia` | str | Verificadas: `civil`, `laboral`, `cobranza`, `penal`, `suprema`, `apelaciones` |
| `tribunal` | int | Obligatorio salvo en `suprema` y `apelaciones` |
| `corte` | int | Obligatorio en `apelaciones`. En el resto, **omitir salvo certeza** |
| `paginas` | int | Tope de páginas a recorrer |

```{include} _generado/buscar_causa_por_rut_juridica.md
```

## `buscar_causa_por_fecha`

Causas ingresadas en un rango de fechas.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `desde` | str | Fecha inicial, DD/MM/AAAA |
| `hasta` | str | Fecha final, DD/MM/AAAA |
| `tribunal` | int | Obligatorio salvo en `suprema` y `apelaciones` |
| `competencia` | str | Verificadas: `civil`, `laboral`, `cobranza`, `penal`, `suprema`, `apelaciones` |
| `corte` | int | Obligatorio en `apelaciones`. En el resto, **omitir salvo certeza** |
| `paginas` | int | Tope de páginas a recorrer |

Es la cuarta búsqueda que la plataforma ofrece y responde una pregunta que las otras tres no:
qué ingresó contra alguien en un período, sabiendo el tribunal pero no el rol.

Un solo día en un solo tribunal puede devolver decenas de causas, así que conviene acotar el
rango antes de subir el tope de páginas: cada página son 100 resultados y una petición.

## `obtener_actuaciones_receptor`

Actuaciones del ministro de fe con su fecha real de diligencia. Es la razón de existir del
proyecto.

:::{warning}
Sólo **civil** entrega actuaciones por esta vía. En **cobranza** las diligencias del ministro de
fe existen pero viven en un panel propio (`diligenciaCob`) con otra estructura, que este
proyecto todavía no lee, así que la llamada se **rechaza** en vez de devolver la lista vacía que
la Historia produciría. Esa lista se leería como "no hubo actuaciones" cuando lo cierto es "no
las estoy leyendo".

En laboral, penal, apelaciones y suprema no existen: en todo el sitio sólo hay
`receptorCivil` y `receptorCobranza`.
:::

Toma `tipo`, `rol`, `anio`, `competencia`, `tribunal` y `corte`, con el mismo significado que
en `buscar_causa_por_rit`. No toma `paginas`: de la búsqueda sólo usa la primera causa.

Internamente encadena búsqueda, detalle y un pase por cada cuaderno, porque la plataforma no
direcciona el detalle por rol. Son varias peticiones bajo el intervalo mínimo, así que tarda.

### Campos de la respuesta

| Campo | Tipo | Descripción |
|---|---|---|
| `folio` | str | Número de folio |
| `etapa` | str | Etapa procesal |
| `tramite` | str | Siempre `Actuación Receptor` |
| `desc_tramite` | str | Texto literal, sin normalizar |
| `fecha_diligencia` | date \| null | **La que corre los plazos**, ISO 8601 |
| `hora_diligencia` | time \| null | Cuando la descripción la trae |
| `fecha_registro` | date \| null | Ingreso al sistema. No corre plazos |
| `discrepancia_fechas` | bool | Las dos fuentes del sitio no coinciden |
| `cuaderno` | str | A qué cuaderno pertenece |
| `foja` | str | Foja |
| `georreferenciado` | bool | `false` significa **ausente** (art. 9 inc. 3 Ley 20.886) |
| `tiene_documento` | bool | Si el folio trae documento descargable |

### Ejemplo

```json
{
  "folio": "3",
  "etapa": "Apremio",
  "tramite": "Actuación Receptor",
  "desc_tramite": "EMBARGO (Exitosa) Diligencia:31/03/2026 10:34",
  "fecha_diligencia": "2026-03-31",
  "hora_diligencia": "10:34:00",
  "fecha_registro": "2026-04-01",
  "discrepancia_fechas": false,
  "cuaderno": "2 - Apremio Ejecutivo Obligación de Dar",
  "foja": "0",
  "georreferenciado": true,
  "tiene_documento": true
}
```

```{include} _generado/obtener_actuaciones_receptor.md
```

## `obtener_historia_causa`

Todas las actuaciones de la causa, no sólo las del ministro de fe. Recorre **todos los
cuadernos**, no sólo el que la plataforma muestra por defecto.

Existe porque cuatro de las seis competencias no tienen receptor: en `suprema`, `apelaciones`,
`laboral` y `penal` la pregunta que da origen a este proyecto no tiene respuesta, y sin esto lo
único disponible ahí era la búsqueda.

:::{warning}
`fecha_diligencia` viene en **nulo** salvo en `civil` y `cobranza`, porque las demás no publican
la fecha doble. Nulo significa que esa competencia no informa la fecha de diligencia, **no** que
el trámite no se haya practicado, y **no sirve para computar plazos**.
:::

| Parámetro | Tipo | Descripción |
|---|---|---|
| `tipo` | str | Letra del rol |
| `rol` | int | Número, sin la letra ni el año |
| `anio` | int | Año, cuatro dígitos |
| `competencia` | str | Sólo aquellas cuyo panel de historia está medido |
| `tribunal` | int, opcional | Código del tribunal |
| `corte` | int, opcional | **Omitir salvo certeza** |

Columnas que sólo publican algunas competencias, y que por eso vienen en nulo en el resto:

| Campo | Dónde aparece |
|---|---|
| `foja` | civil |
| `estado_firma` | cobranza |
| `estado` | laboral, suprema, apelaciones |
| `sala` | suprema, apelaciones |
| `correlativo`, `anio_tramite` | suprema |

```{include} _generado/obtener_historia_causa.md
```

## `buscar_jurisprudencia`

Sentencias de la Corte Suprema desde el Buscador Unificado de Fallos. Sirve sobre todo para
**verificar que una cita existe** antes de usarla: con `rol` y `anio` devuelve la sentencia con
su caratulado, sala, fecha, ministros y enlace permanente.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `rol` | int, opcional | Rol ante la Corte Suprema, sin el año |
| `anio` | int, opcional | Año del rol |
| `todas` | str, opcional | Texto libre: deben aparecer todas estas palabras |
| `literal` | str, opcional | Frase exacta |
| `excluir` | str, opcional | Palabras que no deben aparecer |
| `desde` / `hasta` | str, opcional | Rango de fechas, DD/MM/AAAA |
| `filas` | int | Cuántas traer, de 1 a 250 |
| `buscador` | str | `suprema`, `apelaciones` o `laborales` |

Exige al menos un criterio: sin ninguno el buscador devuelve el índice entero, y eso no es una
búsqueda.

:::{warning}
**`ocultas` sólo tiene significado en `suprema`, y está medido.**

| Buscador | Rol que existe | Rol imposible | Qué cuenta |
|---|---|---|---|
| `suprema` | 2 y 2 | 0 y 0 | la consulta |
| `laborales` | 8 y **269.264** | 0 y **269.264** | el índice completo |

En `laborales` el número que la plataforma entrega es el tamaño del corpus, así que la
diferencia contra lo visible no son coincidencias reservadas. Informar 269.256 ocultas para una
consulta que encontró 8 haría ver cada resultado como una fracción de un universo oculto que no
existe, así que ahí `ocultas` y `coincidencias` vienen en **nulo**.

**Nulo no es cero.** Cero significa "no hay nada reservado"; nulo significa "en este buscador no
se puede saber", y entonces un resultado vacío puede igual corresponder a algo reservado.
`apelaciones` está en nulo por precaución: los cuatro intentos de medirlo murieron por timeout.
:::

:::{warning}
En `suprema`, el resultado trae **`ocultas`**: cuántas coincidencias existen y no se entregan a una consulta
anónima. Medido el 16 de agosto de 2026 sin filtros, el buscador declaraba **1.223.925**
coincidencias y entregaba **300.005**.

Si `ocultas` es mayor que cero, la lista es un subconjunto. No se puede afirmar que algo no
existe porque no aparezca, y `condiciones_de_publicacion` desglosa **todas** las
coincidencias por su condición (`Excluido salud`, `Anonimizadas`, `Reservado restringido`,
`Publicable`, entre otras). Ese desglose suma `coincidencias`, **no** `ocultas`: incluye a las
visibles. El buscador no publica su regla de visibilidad, así que no se puede decir qué
categorías componen las que faltan.

El propio sitio dejó de mostrar ese aviso: los dos mensajes que lo decían siguen en su
JavaScript, comentados.
:::

### Campos de la respuesta

`sentencias`, más cuatro campos de completitud: `visibles`, `coincidencias`, `ocultas` y
`condiciones_de_publicacion`.

`coincidencias` es lo que el buscador declara **antes** de aplicar su filtro de condición de
publicación. No es el tamaño del índice: el Poder Judicial habla públicamente de más de un
millón y medio de sentencias, y esa diferencia no está explicada.

Cada sentencia trae `rol`, `caratulado`, `fecha_sentencia` (ISO 8601), `sala`, `tipo_recurso`,
`resultado_recurso`, `corte_origen`, `rol_corte_apelaciones`, `redactor`, `ministros`,
`condicion_publicacion`, `anonimizada` y `url`.

No trae el texto completo del fallo. La respuesta del buscador lo incluye, pero diez sentencias
serían megabytes con nombres y cédulas de personas naturales: se entrega el enlace permanente y
quien lo necesite entra.

Están verificados tres de los diez buscadores: **suprema**, **apelaciones** y **laborales**.
Se eligen con el parámetro `buscador`.

Cada uno declara sus propios campos, y ésa es la razón de que esto sea una tabla y no un
parser por buscador: Corte Suprema identifica sus sentencias con `rol_era_sup_s` y Apelaciones
con `rol_era_ape_s`, así que un cliente que asumiera los campos del primero devolvería el rol
vacío en el segundo sin que nada reviente. En **laborales** el origen es un juzgado y no una
corte, así que `corte_origen` trae el juzgado.

Los siete restantes se rechazan en vez de adivinar sus campos.

:::{warning}
En **laborales** el rol que el buscador publica **no lleva la letra del tipo de causa**. Medido:
pedir el rol 364 del año 2020 devuelve `O-364-2020` aunque lo buscado sea `T-364-2020`, que es
otra causa. Una respuesta con el mismo número **no prueba** que sea la misma causa: hay que
comparar el caratulado.

Es el falso positivo simétrico del que motivó el proyecto. Acá no es que falte un dato: es que
sobra uno que parece el correcto.
:::

```{include} _generado/buscar_jurisprudencia.md
```

## `obtener_texto_sentencia`

El texto completo de una sentencia, de una en una.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `rol` | int | Rol de la sentencia, sin el año |
| `anio` | int | Año del rol |
| `buscador` | str | `suprema`, `apelaciones` o `laborales` |

Está separado de la búsqueda a propósito, y la razón es de tamaño: **una sentencia de trece
páginas son unos 25.000 caracteres**, medido. Devolver diez con cada búsqueda serían 250.000.
La búsqueda entrega `texto_preview`, más la extensión en palabras y páginas, que suele bastar
para decidir si vale pedir el resto.

:::{warning}
El texto trae los nombres de quienes fueron parte, y cuando el fallo no está anonimizado
también sus cédulas.

`anonimizada` dice si lo entregado es la versión con los datos suprimidos por el propio
tribunal, y `fuente` dice cuál de los dos campos del buscador se leyó (`texto_sentencia` o
`texto_sentencia_anon`). Se informan las dos cosas para que quien lea sepa qué está leyendo.
:::

### Campos de la respuesta

`rol`, `anonimizada`, `fuente`, `palabras`, `paginas` y `texto`.

Si la sentencia existe en el índice pero está reservada para consultas anónimas, se levanta
`PlataformaRechaza` con el número de coincidencias reservadas, en vez de devolver un texto
vacío. Distinguir "existe y no se publica" de "no existe" es el punto.

## Errores

| Excepción | Qué significa | Qué hacer |
|---|---|---|
| `PjudBloqueado` | 403 o 429, o no se pudo derivar el prefijo de rutas | **Detenerse.** Revisar si la IP quedó bloqueada antes de reintentar nada |
| `PlataformaRechaza` | La plataforma rechazó la consulta por sus propias reglas | El mensaje es el suyo, textual. Corregir los parámetros |
| `ValueError` sobre campos | Faltan campos que la plataforma exige | Se detecta antes de consultar, sin gastar una petición |
| `EstructuraInesperada` | El HTML no tiene la forma esperada | La plataforma cambió. Reportar con la plantilla correspondiente |
| `ValueError` | Competencia o buscador no verificado, o falta `MCP_PJUD_CONTACTO` | Corregir la llamada o la configuración |
| `httpx.HTTPStatusError` | La plataforma respondió 5xx | Error suyo, no de la consulta. No está envuelto en una excepción propia porque no hay nada que interpretar: se reintenta más tarde, respetando el intervalo |

El SDK de MCP convierte una excepción en un resultado con `is_error: true` y el mensaje como
contenido, así que el cliente ve el error en vez de recibir una lista vacía que parecería
decir "no hubo actuaciones".
