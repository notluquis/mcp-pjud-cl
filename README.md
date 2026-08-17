# mcp-pjud

Servidor MCP no oficial de solo lectura para la consulta pública de causas del Poder Judicial
de Chile.

[![tests](https://github.com/notluquis/mcp-pjud-cl/actions/workflows/tests.yml/badge.svg)](https://github.com/notluquis/mcp-pjud-cl/actions/workflows/tests.yml)
[![docs](https://readthedocs.org/projects/mcp-pjud-cl/badge/?version=latest)](https://mcp-pjud-cl.readthedocs.io)
[![licencia](https://img.shields.io/badge/licencia-PolyForm%20Strict%201.0.0-lightgrey)](LICENSE.md)

## Aviso

Proyecto independiente, sin relación alguna con el Poder Judicial de Chile ni con la
Corporación Administrativa del Poder Judicial.

Esta herramienta **solo consulta información pública**. No permite el ingreso de escritos,
demandas ni ninguna otra operación de escritura sobre los sistemas del Poder Judicial. No
existe código para hacerlo, ni siquiera desactivado.

## Qué resuelve

Consulta cualquier causa civil pública y devuelve sus **actuaciones del ministro de fe con la
fecha real de diligencia**, que es la que corre los plazos procesales.

Ese dato no viene en el ebook que entrega la Oficina Judicial Virtual, y en la interfaz web
aparece en un formato que se presta a confusión:

```
Fec. Trámite:  31/03/2026 (27/03/2026)
                registro    diligencia
```

Las dos fechas van juntas en una celda y sólo la del paréntesis corre plazos. Acá salen como
campos separados y en ISO 8601, más una marca cuando las dos fuentes del sitio se contradicen.

Tres cosas que hace y que a mano se pasan por alto:

| Qué | Por qué importa |
|---|---|
| Separa las dos fechas | `fecha_diligencia` y `fecha_registro` como campos distintos, en vez de un texto con paréntesis que hay que interpretar |
| Recorre todos los cuadernos | La interfaz muestra uno a la vez. En una causa ejecutiva, el cuaderno de apremio es el que contiene el requerimiento de pago y el embargo |
| Marca las contradicciones | Si el paréntesis y el `Diligencia:` de la descripción no coinciden, lo informa en vez de elegir una |

<details>
<summary>Ejemplo con una causa real</summary>

C-1156-2026 del 2º Juzgado Civil de Concepción, seis actuaciones repartidas en dos cuadernos:

| Cuaderno | Folio | Trámite | Diligencia | Registro |
|---|---|---|---|---|
| Principal | 9 | NOTIFICACIÓN DE DEMANDA (Exitosa) | **27/03/2026 17:40** | 31/03/2026 |
| Apremio | 2 | Requerimiento de Pago (Ficto) | **30/03/2026 10:31** | 31/03/2026 |
| Apremio | 3 | EMBARGO (Exitosa) | **31/03/2026 10:34** | 01/04/2026 |

Leer sólo el cuaderno que la web abre por defecto habría devuelto las tres del principal y
ninguna del apremio.

</details>

## Licencia: léela antes de usarlo

[PolyForm Strict 1.0.0](LICENSE.md). Permite **ejecutar** el software para propósitos no
comerciales, y nada más.

> **Si eres abogado y facturas a tus clientes, necesitas permiso escrito**, aunque uses la
> herramienta sólo para tus propias causas. También lo necesitas para modificarla o
> distribuirla.

Se pide [abriendo un issue](https://github.com/notluquis/mcp-pjud-cl/issues/new/choose) con la
plantilla "Solicitud de permiso de uso". **Se otorga caso a caso y sin costo**: la licencia
restrictiva existe para saber quién usa esto y para qué, no para cobrar.

Sobre forks: GitHub no permite deshabilitarlos en repositorios públicos. Que puedas forkear
**no te otorga derecho a redistribuir ni a modificar**; eso lo define la licencia, no el botón.

**No es open source** en sentido estricto: la licencia restringe modificación, distribución y
uso comercial, así que no cumple la definición de la OSI. El término correcto es
*source-available*. Ver [financiamiento](https://mcp-pjud-cl.readthedocs.io/es/latest/financiamiento.html).

**Pero los pull requests sí son bienvenidos.** El [acuerdo de contribución](CLA.md) te da
permiso para modificar el código con el fin de contribuir, y tú conservas la propiedad de tu
aporte. La idea es que se pueda contribuir *al* proyecto, no que cualquiera publique su propia
versión.

## Documentación

[mcp-pjud-cl.readthedocs.io](https://mcp-pjud-cl.readthedocs.io), organizada por tarea:

- **[Cómo se usa](https://mcp-pjud-cl.readthedocs.io/es/latest/uso.html)**: qué
  resuelve, cómo leer los resultados, qué no hace. Sin código.
- **[Instalación y operación](https://mcp-pjud-cl.readthedocs.io/es/latest/instalacion.html)**:
  instalación, arquitectura, controles de uso responsable.

Además: [referencia de herramientas](https://mcp-pjud-cl.readthedocs.io/es/latest/herramientas.html),
[cumplimiento](https://mcp-pjud-cl.readthedocs.io/es/latest/cumplimiento.html) y
[hoja de ruta](https://mcp-pjud-cl.readthedocs.io/es/latest/roadmap.html).

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `buscar_causa_por_rit` | Busca causas por rol en la consulta pública |
| `obtener_actuaciones_receptor` | Actuaciones del ministro de fe con su fecha real de diligencia |

Ambas anotadas como `readOnlyHint` y `destructiveHint: false` en el protocolo.

## Uso

```bash
uv sync
export MCP_PJUD_CONTACTO="tu@correo.cl"   # obligatorio
uv run mcp-pjud
```

El contacto viaja en el `User-Agent` para que el Poder Judicial pueda identificar a quien
consulta. Sin esa variable el servidor no opera.

En `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pjud": {
      "command": "uv",
      "args": ["--directory", "/ruta/a/mcp-pjud-cl", "run", "mcp-pjud"],
      "env": { "MCP_PJUD_CONTACTO": "tu@correo.cl" }
    }
  }
}
```

## Uso responsable

- **Una consulta cada 5 segundos como mínimo.** No es configurable hacia abajo. Es la cláusula
  CUARTA de las condiciones de uso de la Oficina Judicial Virtual, que prohíbe sobrecargar el
  portal, implementada en código.
- **Detención total ante 403, 429 o captcha.** Sin reintento, sin rotación de IP, sin evasión.
- **Sin persistencia.** Se consulta y se devuelve.
- **Bitácora de peticiones** en memoria, para acreditar uso razonable.

Perder el acceso a la consulta mientras corren plazos en un litigio activo es peor que no
obtener el dato. Ese criterio manda sobre cualquier ganancia de velocidad. Ver
[ACCEPTABLE_USE.md](ACCEPTABLE_USE.md) y
[cumplimiento](https://mcp-pjud-cl.readthedocs.io/es/latest/cumplimiento.html).

## Límites conocidos

- Sólo competencia **civil** verificada. Las otras seis se rechazan en vez de adivinar sus
  parámetros.
- **Las causas reservadas no aparecen.** Un resultado vacío no prueba que la causa no exista.
- Sin paginación: se procesa el primer resultado de la búsqueda.
- `corte` sin valor por defecto a propósito: fijarla produce falsos negativos.
- Si la plataforma cambia, el parser **levanta excepción en vez de devolver vacío**. Una lista
  vacía se lee como "no hubo actuaciones", y así se pierden plazos.

El estado detallado de qué está probado contra el sistema real y qué no está en la
[hoja de ruta](https://mcp-pjud-cl.readthedocs.io/es/latest/roadmap.html).

## Desarrollo

```bash
uv run pytest        # 50 tests, sin red
uv run ruff check .
```

Los tests corren contra HTML real guardado en `tests/fixtures/`. Ninguno consulta al Poder
Judicial.

Antes de proponer cambios lee [cómo contribuir](.github/CONTRIBUTING.md). El
[acuerdo de contribución](CLA.md) te da el permiso para modificar que la licencia por sí sola
no otorga, y tú conservas la propiedad de tu aporte.

## Otros documentos

[Cómo contribuir](.github/CONTRIBUTING.md) ·
[Acuerdo de contribución](CLA.md) ·
[Uso aceptable](ACCEPTABLE_USE.md) ·
[Financiamiento](https://mcp-pjud-cl.readthedocs.io/es/latest/financiamiento.html) ·
[Seguridad](.github/SECURITY.md) ·
[Soporte](.github/SUPPORT.md) ·
[Código de conducta](.github/CODE_OF_CONDUCT.md) ·
[Cambios](CHANGELOG.md)

---

Esto acerca la fuente oficial. No reemplaza la revisión de un abogado ni la lectura del
expediente.
