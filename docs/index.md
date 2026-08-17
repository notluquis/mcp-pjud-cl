# mcp-pjud

Servidor MCP no oficial de solo lectura para la consulta pública de causas del Poder Judicial
de Chile.

## Aviso

Proyecto independiente, **sin relación alguna** con el Poder Judicial de Chile ni con la
Corporación Administrativa del Poder Judicial.

Esta herramienta **solo consulta información pública**. No permite el ingreso de escritos,
demandas ni ninguna otra operación de escritura. No existe código para hacerlo, ni siquiera
desactivado.

## El problema, en una tabla

El ebook que descarga la Oficina Judicial Virtual **omite las actuaciones del receptor**. Esas
actuaciones traen la fecha en que el ministro de fe practicó realmente la diligencia —la que
corre los plazos— y suele diferir de la fecha en que el trámite se registró en el sistema.

Caso real, C-1156-2026 del 2º Juzgado Civil de Concepción:

| Cuaderno | Folio | Trámite | Diligencia | Registro | Días |
|---|---|---|---|---|---|
| Principal | 9 | NOTIFICACIÓN DE DEMANDA (Exitosa) | **27/03/2026 17:40** | 31/03/2026 | 4 |
| Apremio | 2 | Requerimiento de Pago (Ficto) | **30/03/2026 10:31** | 31/03/2026 | 1 |
| Apremio | 3 | EMBARGO (Exitosa) | **31/03/2026 10:34** | 01/04/2026 | 1 |

En la web esas fechas aparecen así, y hay que saber leerlas:

```
Fec. Trámite:  31/03/2026 (27/03/2026)
                registro    diligencia  ← ésta corre los plazos
```

Esta herramienta las entrega como campos separados y nombrados, para que nadie tenga que
inferirlas de un paréntesis.

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
roadmap
```

## Licencia

[PolyForm Strict 1.0.0](https://polyformproject.org/licenses/strict/1.0.0). Permite
**ejecutar** el software para propósitos no comerciales.

**Si eres abogado y facturas a tus clientes, necesitas permiso escrito**, aunque uses la
herramienta sólo para tus propias causas. Se pide en un issue y se otorga caso a caso, sin
costo. Ver {doc}`cumplimiento`.
