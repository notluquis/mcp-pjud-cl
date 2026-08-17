# mcp-pjud

Servidor MCP no oficial de solo lectura para la consulta pública de causas del Poder Judicial
de Chile.

## Aviso

Proyecto independiente, **sin relación alguna** con el Poder Judicial de Chile ni con la
Corporación Administrativa del Poder Judicial.

Esta herramienta **solo consulta información pública**. No permite el ingreso de escritos,
demandas ni ninguna otra operación de escritura. No existe código para hacerlo, ni siquiera
desactivado.

## Qué resuelve

Consulta cualquier causa civil pública y devuelve sus **actuaciones del ministro de fe con la
fecha real de diligencia**, que es la que corre los plazos procesales.

Ese dato no viene en el ebook que entrega la Oficina Judicial Virtual, y en la interfaz web
aparece en un formato que se presta a confusión:

```
Fec. Trámite:  31/03/2026 (27/03/2026)
                registro    diligencia  ← ésta corre los plazos
```

Las dos fechas comparten una celda y sólo la del paréntesis corre plazos. Acá salen como campos
separados y nombrados, en ISO 8601, para que nadie tenga que inferirlas.

A eso se suman dos cosas que a mano se pasan por alto: **se recorren todos los cuadernos** (la
interfaz muestra uno a la vez, y en una causa ejecutiva el de apremio contiene el requerimiento
de pago y el embargo), y **se marcan las contradicciones** cuando las dos fuentes de fecha del
sitio no coinciden.

### Ejemplo con una causa real

C-1156-2026 del 2º Juzgado Civil de Concepción, seis actuaciones en dos cuadernos:

| Cuaderno | Folio | Trámite | Diligencia | Registro | Días |
|---|---|---|---|---|---|
| Principal | 9 | NOTIFICACIÓN DE DEMANDA (Exitosa) | **27/03/2026 17:40** | 31/03/2026 | 4 |
| Apremio | 2 | Requerimiento de Pago (Ficto) | **30/03/2026 10:31** | 31/03/2026 | 1 |
| Apremio | 3 | EMBARGO (Exitosa) | **31/03/2026 10:34** | 01/04/2026 | 1 |

Leer sólo el cuaderno que la web abre por defecto habría devuelto las tres del principal y
ninguna del apremio.

## Por dónde empezar

{doc}`Soy abogado o abogada <para-abogados>`
: Qué resuelve, cómo leer los resultados, qué **no** hace, y qué necesitas pedirle a tu
  informático. Sin código.

{doc}`Administro los sistemas <para-informatica>`
: Instalación, configuración del cliente MCP, arquitectura, y los controles de uso
  responsable que no se deben tocar.

```{toctree}
:maxdepth: 2
:caption: Guías

para-abogados
para-informatica
```

```{toctree}
:maxdepth: 2
:caption: Referencia

herramientas
cumplimiento
licencia
financiamiento
roadmap
```

## Licencia

[PolyForm Strict 1.0.0](https://polyformproject.org/licenses/strict/1.0.0). Permite
**ejecutar** el software para propósitos no comerciales.

**Si eres abogado y facturas a tus clientes, necesitas permiso escrito**, aunque uses la
herramienta sólo para tus propias causas. Se pide en un issue y se otorga caso a caso, sin
costo. Ver {doc}`cumplimiento`.
