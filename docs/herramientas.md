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

## `buscar_causa_por_rit`

Busca causas por rol en la consulta pública.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `tipo` | str | Letra del rol. En civil: `C`, `V`, `E`, `A`, `F` o `I` |
| `rol` | int | Número, sin la letra ni el año |
| `anio` | int | Año, cuatro dígitos |
| `competencia` | str | Sólo `civil` está verificada |
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

## `buscar_causa_por_nombre`

Busca causas por nombre de litigante.

Reglas de la plataforma, medidas probando cada combinación contra el sistema real:

- Exige **al menos dos de los tres campos de nombre** (nombre, apellido paterno, apellido
  materno). El **año no cuenta** para ese mínimo: `paterno + año` es rechazado, `paterno +
  materno` es aceptado.
- Exige **indicar el tribunal**. No se puede buscar por nombre en todos los tribunales a la
  vez, y eso limita su utilidad: hay que saber dónde está la causa.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `apellido_paterno` | str | Apellido paterno del litigante |
| `apellido_materno` | str | Apellido materno |
| `nombre` | str | Nombres |
| `anio` | int, opcional | Año de ingreso. **No cuenta** para el mínimo de dos campos |
| `competencia` | str | Sólo `civil` está verificada |
| `tribunal` | int | Obligatorio acá |
| `corte` | int, opcional | **Omitir salvo certeza** |
| `paginas` | int | Tope de páginas a recorrer |

## `buscar_causa_por_rut_juridica`

Busca causas de una persona jurídica por su RUT. Es la **única vía para empresas**, que no
tienen Clave Única y por lo tanto no aparecen en "Mis Causas".

Exige el dígito verificador y el tribunal.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `rut` | int | RUT sin dígito verificador ni puntos |
| `digito_verificador` | str | Dígito verificador: 0-9 o K |
| `anio` | int, opcional | Año de ingreso |
| `competencia` | str | Sólo `civil` está verificada |
| `tribunal` | int | Obligatorio acá |
| `corte` | int, opcional | **Omitir salvo certeza** |
| `paginas` | int | Tope de páginas a recorrer |

## `obtener_actuaciones_receptor`

Actuaciones del ministro de fe con su fecha real de diligencia. Es la razón de existir del
proyecto.

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

Exige al menos un criterio: sin ninguno el buscador devuelve el índice entero, y eso no es una
búsqueda.

:::{warning}
El resultado trae **`ocultas`**: cuántas coincidencias existen y no se entregan a una consulta
anónima. Medido el 16 de agosto de 2026 sin filtros, el buscador declaraba **1.223.925**
sentencias indexadas y entregaba **300.005**.

Si `ocultas` es mayor que cero, la lista es un subconjunto. No se puede afirmar que algo no
existe porque no aparezca, y `motivos_de_reserva` dice por qué falta (`Excluido salud`,
`Anonimizadas`, `Reservado restringido`, entre otros).

El propio sitio dejó de mostrar ese aviso: los dos mensajes que lo decían siguen en su
JavaScript, comentados.
:::

### Campos de la respuesta

`sentencias`, más cuatro campos de completitud: `visibles`, `coincidencias`, `ocultas` y
`motivos_de_reserva`.

Cada sentencia trae `rol`, `caratulado`, `fecha_sentencia` (ISO 8601), `sala`, `tipo_recurso`,
`resultado_recurso`, `corte_origen`, `rol_corte_apelaciones`, `redactor`, `ministros`,
`condicion_publicacion`, `anonimizada` y `url`.

No trae el texto completo del fallo. La respuesta del buscador lo incluye, pero diez sentencias
serían megabytes con nombres y cédulas de personas naturales: se entrega el enlace permanente y
quien lo necesite entra.

Sólo el buscador de **Corte Suprema** está verificado. Cada uno de los otros nueve declara sus
propios campos, así que exponerlos sin medirlos devolvería campos vacíos en vez de un error.

## Errores

| Excepción | Qué significa | Qué hacer |
|---|---|---|
| `PjudBloqueado` | 403 o 429, o no se pudo derivar el prefijo de rutas | **Detenerse.** Revisar si la IP quedó bloqueada antes de reintentar nada |
| `PlataformaRechaza` | La plataforma rechazó la consulta por sus propias reglas | El mensaje es el suyo, textual. Corregir los parámetros |
| `ValueError` sobre campos | Faltan campos que la plataforma exige | Se detecta antes de consultar, sin gastar una petición |
| `EstructuraInesperada` | El HTML no tiene la forma esperada | La plataforma cambió. Reportar con la plantilla correspondiente |
| `ValueError` | Competencia no implementada, o falta `MCP_PJUD_CONTACTO` | Corregir la llamada o la configuración |

El SDK de MCP convierte una excepción en un resultado con `is_error: true` y el mensaje como
contenido, así que el cliente ve el error en vez de recibir una lista vacía que parecería
decir "no hubo actuaciones".
