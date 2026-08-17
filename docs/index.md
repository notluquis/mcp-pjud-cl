# mcp-pjud

Servidor MCP no oficial de solo lectura para la consulta pública de causas del Poder Judicial
de Chile.

:::{warning}
Proyecto independiente, **sin relación alguna** con el Poder Judicial de Chile ni con la
Corporación Administrativa del Poder Judicial.

**Solo consulta información pública.** No permite el ingreso de escritos ni ninguna operación
de escritura, y no existe código para hacerlo, ni siquiera desactivado.
:::

## Lo único que hay que entender antes de usar un dato

La columna `Fec. Trámite` de la plataforma trae **dos fechas en una celda**:

```
31/03/2026 (27/03/2026)
 registro    diligencia  ← ésta corre los plazos
```

`fecha_registro` es cuándo el tribunal anotó el trámite. `fecha_diligencia` es cuándo el
ministro de fe la practicó, y **es la que determina los plazos procesales**. Suelen diferir
varios días, y el ebook que entrega la Oficina Judicial Virtual no trae ninguna de las dos.

Esta herramienta las devuelve como campos separados, en ISO 8601. Si las dos fuentes del sitio
se contradicen, lo informa en `discrepancia_fechas` en vez de elegir una.

## Por dónde empezar

{doc}`Cómo se usa e interpreta <uso>`
: Qué significa cada campo, cuándo desconfiar del resultado, y qué **no** hace. Sin código.

{doc}`Instalación y operación <instalacion>`
: Instalación, arquitectura, y los controles de uso responsable que no se deben tocar.

{doc}`Ejemplos <ejemplos>`
: Casos resueltos de punta a punta, incluidos los modos de falla y cómo leerlos.

## Antes de instalar

La licencia ([PolyForm Strict 1.0.0](https://polyformproject.org/licenses/strict/1.0.0))
permite **ejecutar** el software con fines no comerciales.

**Si facturas a tus clientes necesitas permiso escrito**, aunque uses la herramienta sólo para
tus propias causas. Se pide en un issue y **se otorga caso a caso, sin costo**. El razonamiento
completo está en {doc}`licencia`.

La documentación sigue [Diátaxis](https://diataxis.fr/): **cómo se hace** para resolver una
tarea, **referencia** para consultar un dato exacto, y **explicación** para entender por qué.
Si buscas la respuesta a "¿ya corre el plazo?", empieza por {doc}`ejemplos`.

```{toctree}
:maxdepth: 2
:caption: Cómo se hace
:hidden:

instalacion
ejemplos
```

```{toctree}
:maxdepth: 2
:caption: Referencia
:hidden:

herramientas
```

```{toctree}
:maxdepth: 2
:caption: Explicación
:hidden:

uso
cumplimiento
licencia
roadmap
financiamiento
```

```{toctree}
:caption: Proyecto
:hidden:

Repositorio <https://github.com/notluquis/mcp-pjud-cl>
Cambios <https://github.com/notluquis/mcp-pjud-cl/blob/main/CHANGELOG.md>
Cómo contribuir <https://github.com/notluquis/mcp-pjud-cl/blob/main/.github/CONTRIBUTING.md>
```

---

Esto acerca la fuente oficial. No reemplaza la revisión de un abogado ni la lectura del
expediente.
