---
orphan: true
myst:
  html_meta:
    description: "Auditoría de las doce herramientas MCP: qué cuesta anunciarlas, qué se paga dos veces y qué conviene unir o separar."
---

# Auditoría de la superficie MCP

:::{note}
Documento de trabajo, no publicado. Se borra cuando lo que propone se ejecute o se descarte.

Todo lo que dice "medido" se midió sobre `07005e9` el 20 de agosto de 2026, con
`mcp.list_tools()`, que es exactamente lo que un cliente recibe.
:::

## Lo que cuesta antes de la primera consulta

**16.742 tokens.** Eso es lo que pesa anunciar las doce herramientas con sus esquemas de
entrada y salida, y se paga en cada conversación aunque no se consulte ninguna causa.

| Herramienta | Caracteres | % |
|---|---:|---:|
| `obtener_detalle_causa` | 22.913 | **34,2%** |
| `obtener_actuaciones_receptor` | 7.111 | 10,6% |
| `buscar_jurisprudencia` | 6.349 | 9,5% |
| `obtener_georreferencia` | 4.587 | 6,8% |
| `buscar_causa_por_nombre` | 4.485 | 6,7% |
| `buscar_causa_por_rit` | 4.418 | 6,6% |
| `buscar_causa_por_fecha` | 4.355 | 6,5% |
| `buscar_causa_por_rut_juridica` | 4.305 | 6,4% |
| `obtener_documento` | 3.195 | 4,8% |
| `obtener_texto_sentencia` | 2.414 | 3,6% |
| `listar_tribunales` | 1.863 | 2,8% |
| `listar_cortes` | 973 | 1,5% |

De `obtener_detalle_causa`, **el 84% es su esquema de salida**: 19.120 caracteres que describen
siete modelos anidados, con `Actuacion` sola en 4.742.

## Lo que se paga dos veces

El protocolo no comparte definiciones entre herramientas: cada una lleva su esquema completo.

| Modelo | Tamaño | Aparece en | Se paga de más |
|---|---:|---:|---:|
| `CausaEncontrada` | 1.967 | 4 herramientas | 5.901 |
| `Actuacion` | 4.742 | 2 herramientas | 4.742 |

**2.660 tokens, el 16% de todo lo anunciado**, son copias.

## Unir las cuatro búsquedas: medido y descartado

Unir `buscar_causa_por_rit`, `_nombre`, `_rut_juridica` y `_fecha` en una sola con un
discriminador ahorraría los 5.901 caracteres de `CausaEncontrada` repetido, más los cuatro
parámetros que las cuatro comparten (`competencia`, `corte`, `paginas`, `tribunal`).

No se hace, y la razón no es gusto: **las cuatro exigen cosas distintas.**

| Herramienta | Obligatorios | Propios |
|---|---:|---|
| `buscar_causa_por_rit` | 3 | `tipo`, `rol`, `anio` |
| `buscar_causa_por_nombre` | 0 | `nombre`, `apellido_paterno`, `apellido_materno`, `anio` |
| `buscar_causa_por_rut_juridica` | 2 | `rut`, `digito_verificador`, `anio` |
| `buscar_causa_por_fecha` | 2 | `desde`, `hasta` |

Un esquema único no puede decir "`rol` es obligatorio **si** `por` vale `rit`" de una forma que
todos los clientes entiendan igual. JSON Schema lo expresa con `oneOf`, y ahí el modelo pasa de
leer cuatro firmas inequívocas a inferir qué parámetro va con qué modo. Se cambiaría un 15% de
contexto por llamadas mal formadas, y una llamada mal formada contra esta plataforma no es
gratis: gasta petición y devuelve un aviso que el modelo suele atribuir al Poder Judicial.

## La pregunta que sí queda abierta

`obtener_actuaciones_receptor` cuesta **7.111 caracteres, el 10,6%**, y duplica `Actuacion`
entera. Lo que hace, medido sobre C-1156-2026, es quedarse con 3 de 10 filas: las que traen
`Actuación Receptor` en la columna de trámite.

Un modelo puede hacer ese filtro solo, sobre lo que `obtener_detalle_causa` ya devuelve.

Lo que sí aporta, y hay que ponerlo en la balanza:

- **Achica la respuesta**, no el anuncio. Tres filas en vez de diez, y en una causa larga esa
  diferencia crece mientras el anuncio no.
- **Rechaza antes de consultar** las competencias que no publican actuaciones de ministro de
  fe, en vez de devolver una lista vacía que se leería como "no hubo".
- `AGENTS.md` la llama la razón de existir del proyecto, y sus advertencias de plazos están
  escritas para que el modelo las lea justo antes de esa llamada.

**No se propone retirarla.** Se deja la cifra escrita, que es lo que faltaba para poder
discutirlo: 10,6% del contexto permanente a cambio de un filtro de tres líneas y dos garantías.

## Lo que no está roto

- **Todo método público del cliente está expuesto o excluido a propósito**, y los excluidos
  tienen su razón escrita en `NO_SON_HERRAMIENTAS`. No hay funcionalidad implementada que el
  protocolo no ofrezca.
- **`obtener_documento` es la única sin esquema de salida**, y es correcto: devuelve bloques de
  contenido, no un modelo.
- Las descripciones largas **no son el problema a recortar**. Son lo que hace que el modelo
  distinga `fecha_diligencia` de `fecha_registro`, y esa distinción es el proyecto entero.
  Recortarlas ahorraría contexto empeorando exactamente lo que se vino a cuidar.

## Lo que sigue

La única palanca grande sin costo de calidad es el esquema de salida de
`obtener_detalle_causa`, que son 4.780 tokens. Y ahí lo que hay que medir antes de tocar es si
un cliente real lo usa: si nadie valida contra él, describir siete modelos anidados en cada
conversación es caro y no compra nada.
