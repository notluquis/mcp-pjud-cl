# Ejemplos

Casos resueltos de punta a punta. Los roles son de causas públicas reales y las salidas están
tomadas de consultas verdaderas.

## Revisar si una notificación ya corre plazo

La pregunta más frecuente, y la que originó el proyecto.

**Situación.** Se sabe que la demanda quedó notificada, pero el ebook no dice cuándo se
practicó la diligencia, sólo cuándo el tribunal la registró.

**Consulta:**

```
obtener_actuaciones_receptor(tipo="C", rol=1156, anio=2026, tribunal=162, corte=46)
```

**Respuesta, recortada al folio que interesa:**

```json
{
  "folio": "9",
  "cuaderno": "1 - Principal",
  "tramite": "Actuación Receptor",
  "desc_tramite": "NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:27/03/2026 17:40",
  "fecha_diligencia": "2026-03-27",
  "hora_diligencia": "17:40:00",
  "fecha_registro": "2026-03-31",
  "discrepancia_fechas": false,
  "georreferenciado": true,
  "tiene_documento": true
}
```

**Cómo se lee.** La notificación se practicó el **27 de marzo**, no el 31. Quien cuente desde
la fecha de registro se come cuatro días de plazo. En la web esas dos fechas aparecen juntas
como `31/03/2026 (27/03/2026)`.

## No perder el cuaderno de apremio

**Situación.** Juicio ejecutivo. Interesa saber cuándo se practicó el requerimiento de pago y
cuándo el embargo.

La misma consulta de arriba devuelve **seis** actuaciones, no tres, porque recorre todos los
cuadernos:

| Cuaderno | Folio | Trámite | Diligencia |
|---|---|---|---|
| 1 - Principal | 9 | NOTIFICACIÓN DE DEMANDA (Exitosa) | 27/03/2026 17:40 |
| 1 - Principal | 8 | CERTIFICACIÓN BÚSQUEDAS (Búsqueda positiva) | 27/03/2026 17:40 |
| 1 - Principal | 7 | CERTIFICACIÓN BÚSQUEDAS (Búsqueda positiva) | 24/03/2026 14:29 |
| 2 - Apremio Ejecutivo Obligación de Dar | 4 | Inscripción / Alzamiento registro | 16/04/2026 15:54 |
| 2 - Apremio Ejecutivo Obligación de Dar | 3 | EMBARGO (Exitosa) | 31/03/2026 10:34 |
| 2 - Apremio Ejecutivo Obligación de Dar | 2 | Requerimiento de Pago (Ficto) | 30/03/2026 10:31 |

**Por qué importa.** La interfaz web muestra un cuaderno a la vez, con un desplegable que pasa
inadvertido. Mirando sólo el principal se ven las tres primeras y ninguna del apremio, o sea
faltan justo el requerimiento y el embargo.

## Seguir un exhorto con varias búsquedas negativas

**Situación.** Un exhorto que lleva meses. Interesa la secuencia completa de intentos del
receptor, para saber si corresponde pedir notificación por el artículo 44.

```
obtener_actuaciones_receptor(tipo="E", rol=468, anio=2026, tribunal=163, corte=46)
```

Devuelve ocho actuaciones. La secuencia, de la más reciente a la más antigua:

| Folio | Trámite | Diligencia |
|---|---|---|
| 12 | Requerimiento de Pago (Ficto) | 18/06/2026 09:00 |
| 11 | CERTIFICACIÓN BÚSQUEDAS (Búsqueda positiva) | 17/06/2026 14:24 |
| 10 | NOTIFICACIÓN DE DEMANDA (Exitosa) | 17/06/2026 14:25 |
| 9 | NOTIFICACIÓN DE DEMANDA (Búsqueda negativa) | 09/06/2026 14:42 |
| 8 | CERTIFICACIÓN BÚSQUEDAS (Búsqueda positiva) | 09/06/2026 13:27 |
| 7 | NOTIFICACIÓN DE DEMANDA (Búsqueda negativa) | 25/05/2026 15:30 |
| 6 | NOTIFICACIÓN DE DEMANDA (Búsqueda negativa) | 25/05/2026 15:29 |
| 3 | NOTIFICACIÓN DE DEMANDA (Búsqueda negativa) | 06/04/2026 16:15 |

Cuatro búsquedas negativas antes de la exitosa, con sus fechas y horas exactas.

## Buscar sin saber el tribunal

Si no se sabe en qué tribunal está la causa, **se omite el parámetro**:

```
buscar_causa_por_rit(tipo="C", rol=1156, anio=2026)
```

:::{warning}
No fijes `corte` salvo que tengas certeza. En una prueba real, una búsqueda con la corte puesta
en Concepción omitió una causa del 11º Juzgado Civil de Santiago que sí existía. Por eso el
parámetro no tiene valor por defecto.
:::

## Cuando las dos fechas se contradicen

Si `discrepancia_fechas` viene en `true`, la fecha del paréntesis de `Fec. Trámite` y la del
`Diligencia:` de la descripción **no coinciden en la propia plataforma**.

La herramienta no elige por ti. Informa las dos y marca el conflicto:

```json
{
  "desc_tramite": "NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:15/06/2026 10:00",
  "fecha_diligencia": "2026-06-17",
  "fecha_registro": "2026-06-22",
  "discrepancia_fechas": true
}
```

En ese caso, verifica contra el expediente antes de computar nada.

## Cuando la georreferencia no está

`georreferenciado: false` no es un dato faltante de la herramienta: significa que **la
actuación no tiene registro georreferenciado** en la plataforma.

El artículo 9 inciso 3 de la Ley 20.886 exige ese registro para las actuaciones del receptor,
así que su ausencia puede ser materia de alegación. Por eso el campo se expone siempre, incluso
vacío, en vez de omitirse.

## Cuando algo falla

| Qué ves | Qué significa | Qué hacer |
|---|---|---|
| `PjudBloqueado` con 403 o 429 | La plataforma rechazó la consulta | **Detente.** Revisa si la IP quedó bloqueada antes de reintentar |
| `PjudBloqueado` mencionando el prefijo | No se pudo derivar la ruta desde el HTML | La plataforma cambió su estructura. Reporta con la plantilla correspondiente |
| `EstructuraInesperada` | El HTML no tiene la forma esperada | Lo mismo. Es a propósito: preferimos un error visible a una lista vacía |
| Lista vacía sin error | No hay actuaciones de receptor en esa causa | Puede ser correcto, o la causa puede estar en una competencia sin cubrir |
| `ValueError` sobre competencia | Pediste una competencia no verificada | Sólo civil está implementada |

:::{note}
Un error nunca significa "no hubo actuaciones". Esa distinción es deliberada: una lista vacía
devuelta ante una plataforma que cambió haría creer que un plazo no corrió.
:::
