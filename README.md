# mcp-pjud

Servidor MCP no oficial de solo lectura para la consulta pública de causas del Poder Judicial
de Chile.

[![tests](https://github.com/notluquis/mcp-pjud-cl/actions/workflows/tests.yml/badge.svg)](https://github.com/notluquis/mcp-pjud-cl/actions/workflows/tests.yml)
[![codeql](https://github.com/notluquis/mcp-pjud-cl/actions/workflows/codeql.yml/badge.svg)](https://github.com/notluquis/mcp-pjud-cl/actions/workflows/codeql.yml)
[![scorecard](https://api.scorecard.dev/projects/github.com/notluquis/mcp-pjud-cl/badge)](https://scorecard.dev/viewer/?uri=github.com/notluquis/mcp-pjud-cl)
[![docs](https://readthedocs.org/projects/mcp-pjud-cl/badge/?version=latest)](https://mcp-pjud-cl.readthedocs.io)
[![licencia](https://img.shields.io/badge/licencia-PolyForm%20Strict%201.0.0-lightgrey)](LICENSE.md)
[![source available](https://img.shields.io/badge/source--available-no%20es%20open%20source-orange)](https://mcp-pjud-cl.readthedocs.io/es/latest/licencia.html)

> Proyecto independiente, sin relación alguna con el Poder Judicial de Chile ni con la
> Corporación Administrativa del Poder Judicial.
>
> **Solo consulta información pública.** No permite el ingreso de escritos ni ninguna
> operación de escritura, y no existe código para hacerlo, ni siquiera desactivado.

## Qué resuelve

Consulta cualquier causa civil pública y devuelve sus **actuaciones del ministro de fe con la
fecha real de diligencia**, que es la que corre los plazos procesales.

Ese dato no viene en el ebook que entrega la Oficina Judicial Virtual, y en la interfaz web
aparece en un formato que se presta a confusión:

```
Fec. Trámite:  31/03/2026 (27/03/2026)
                registro    diligencia
```

Las dos fechas comparten una celda y sólo la del paréntesis corre plazos. Acá salen como campos
separados y en ISO 8601.

| Qué hace | Por qué importa |
|---|---|
| Separa las dos fechas | `fecha_diligencia` y `fecha_registro` como campos distintos, en vez de un texto con paréntesis que hay que interpretar |
| Recorre todos los cuadernos | La interfaz muestra uno a la vez. En una causa ejecutiva, el de apremio contiene el requerimiento de pago y el embargo |
| Marca las contradicciones | Si el paréntesis y el `Diligencia:` de la descripción no coinciden, lo informa en vez de elegir una |

<details>
<summary>Ejemplo con una causa real</summary>

C-1156-2026 del 2º Juzgado Civil de Concepción, seis actuaciones en dos cuadernos:

| Cuaderno | Folio | Trámite | Diligencia | Registro |
|---|---|---|---|---|
| Principal | 9 | NOTIFICACIÓN DE DEMANDA (Exitosa) | **27/03/2026 17:40** | 31/03/2026 |
| Apremio | 2 | Requerimiento de Pago (Ficto) | **30/03/2026 10:31** | 31/03/2026 |
| Apremio | 3 | EMBARGO (Exitosa) | **31/03/2026 10:34** | 01/04/2026 |

Leer sólo el cuaderno que la web abre por defecto habría devuelto las tres del principal y
ninguna del apremio.

</details>

## Antes de instalar: la licencia

[PolyForm Strict 1.0.0](LICENSE.md) permite **ejecutar** el software con fines no comerciales,
y nada más.

> **Si facturas a tus clientes necesitas permiso escrito**, aunque uses la herramienta sólo
> para tus propias causas. También para modificarla o distribuirla.
>
> Se pide [abriendo un issue](https://github.com/notluquis/mcp-pjud-cl/issues/new/choose) y
> **se otorga caso a caso, sin costo**. La licencia restrictiva existe para saber quién usa
> esto y para qué, no para cobrar.

Dos aclaraciones que suelen hacer falta:

- **No es open source** en sentido estricto, porque restringe modificación, distribución y uso
  comercial. El término correcto es *source-available*. Que GitHub permita forkear **no otorga
  derecho a redistribuir**: eso lo define la licencia, no el botón.
- **Los pull requests sí son bienvenidos.** El [acuerdo de contribución](CLA.md) te da el
  permiso para modificar que la licencia por sí sola no otorga, y conservas la propiedad de tu
  aporte. La idea es que se contribuya *al* proyecto, no que cualquiera publique su versión.

El razonamiento completo, con las familias de licencia que se descartaron y por qué, está en
[la página de licencia](https://mcp-pjud-cl.readthedocs.io/es/latest/licencia.html).

## Instalación

No hace falta clonar: `uvx` descarga y ejecuta. Requiere [uv](https://docs.astral.sh/uv/) y
Python 3.13 o superior.

**Reemplaza `tu@correo.cl` por tu correo real** en cualquiera de las formas de abajo. Ese dato
viaja en el `User-Agent` para que el Poder Judicial pueda identificar a quien consulta, y sin
él el servidor no arranca.

**Claude Code**

```bash
claude mcp add mcp-pjud-cl -e MCP_PJUD_CONTACTO=tu@correo.cl \
  -- uvx --from git+https://github.com/notluquis/mcp-pjud-cl@stable mcp-pjud
```

**Cursor y VS Code**

[![Instalar en Cursor](https://img.shields.io/badge/Cursor-instalar-000?logo=cursor&logoColor=white)](https://cursor.com/en/install-mcp?name=mcp-pjud-cl&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL25vdGx1cXVpcy9tY3AtcGp1ZC1jbEBzdGFibGUiLCJtY3AtcGp1ZCJdLCJlbnYiOnsiTUNQX1BKVURfQ09OVEFDVE8iOiJ0dUBjb3JyZW8uY2wifX0%3D)
[![Instalar en VS Code](https://img.shields.io/badge/VS_Code-instalar-0098FF?logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=mcp-pjud-cl&config=%7B%22name%22%3A%22mcp-pjud-cl%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22git%2Bhttps%3A//github.com/notluquis/mcp-pjud-cl%40stable%22%2C%22mcp-pjud%22%5D%2C%22env%22%3A%7B%22MCP_PJUD_CONTACTO%22%3A%22tu%40correo.cl%22%7D%7D)

Los botones dejan el correo como marcador. Edítalo en la configuración del editor, o el
servidor falla con un mensaje que te lo recuerda.

**Claude Desktop, Codex y cualquier otro cliente**

<!-- [[[cog
import sys; sys.path.insert(0, 'docs')
from _bloques import configuracion
cog.out('\n```json\n' + configuracion(contacto='tu@correo.cl') + '\n```\n')
]]] -->

```json
{
  "mcpServers": {
    "mcp-pjud-cl": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/notluquis/mcp-pjud-cl@stable", "mcp-pjud"],
      "env": { "MCP_PJUD_CONTACTO": "tu@correo.cl" }
    }
  }
}
```
<!-- [[[end]]] -->

El transporte es stdio: no abre puertos ni escucha en la red.

`@stable` apunta siempre a la última versión publicada, así que se actualiza sola al instalar.
Si prefieres quedarte en una versión concreta, cambia esa referencia por la etiqueta, por
ejemplo `@v0.19.0`. Sin ninguna referencia se sigue la rama principal, que trae cambios sin
publicar: no es lo recomendado.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `listar_cortes` | Las Cortes de Apelaciones con su código |
| `listar_tribunales` | Los tribunales de una corte con su código, que las búsquedas exigen |
| `buscar_causa_por_rit` | Busca por rol, en las seis competencias |
| `buscar_causa_por_nombre` | Busca por nombre de una persona natural |
| `buscar_causa_por_rut_juridica` | Busca por RUT de una empresa |
| `buscar_causa_por_fecha` | Busca por fecha de ingreso |
| `obtener_actuaciones_receptor` | Actuaciones del ministro de fe con su fecha real de diligencia |
| `obtener_georreferencia` | Dónde y cuándo el ministro de fe registró que practicó una diligencia, con hora |
| `obtener_anexos_escrito` | Los documentos que un escrito acompañó, que son otro canal distinto del de la resolución |
| `listar_audios_audiencia` | Qué audios de audiencia tiene la causa y con qué enlace se bajan. No los trae |
| `obtener_documento` | El archivo de una actuación: resolución, escrito, certificado o el expediente entero |
| `obtener_detalle_causa` | Todos los paneles que la competencia publique, de una sola cadena y recorriendo todos los cuadernos. La referencia enumera cuáles |
| `buscar_jurisprudencia` | Busca sentencias en el buscador de fallos |
| `obtener_texto_sentencia` | El texto completo de una sentencia |

Todas anotadas como `readOnlyHint` y `destructiveHint: false` en el protocolo. No hay ninguna
que escriba: [por qué](https://mcp-pjud-cl.readthedocs.io/es/latest/cumplimiento.html).
[Referencia completa de campos](https://mcp-pjud-cl.readthedocs.io/es/latest/herramientas.html)
y [ejemplos resueltos](https://mcp-pjud-cl.readthedocs.io/es/latest/ejemplos.html).

## Cómo se comporta

### Uso responsable

- **Una consulta cada 5 segundos en régimen sostenido**, con una ráfaga de hasta 4 al
  inicio para que una pregunta se responda de una vez. Ninguno de los dos es configurable
  hacia abajo. Es la cláusula
  CUARTA de las condiciones de uso de la Oficina Judicial Virtual, que prohíbe sobrecargar el
  portal, implementada en código.
- **Detención total ante 403, 429 o captcha.** Sin reintento, sin rotación de IP, sin evasión.
- **Sin persistencia.** Se consulta y se devuelve.
- **Bitácora de peticiones** en memoria, para acreditar uso razonable.

Perder el acceso mientras corren plazos en un litigio activo es peor que no obtener el dato.
Ese criterio manda sobre cualquier ganancia de velocidad.

### Límites conocidos

- Sólo competencia **civil** verificada. Las otras seis se rechazan en vez de adivinar sus
  parámetros.
- **Las causas reservadas no aparecen.** Un resultado vacío no prueba que la causa no exista.
- Una búsqueda muy amplia **levanta excepción en vez de devolver una lista recortada**.
  Acota la consulta o sube el tope de páginas.
- `corte` sin valor por defecto a propósito: fijarla produce falsos negativos.
- Si la plataforma cambia, el parser **levanta excepción en vez de devolver vacío**. Una lista
  vacía se leería como "no hubo actuaciones", y así se pierden plazos.

## Documentación

[mcp-pjud-cl.readthedocs.io](https://mcp-pjud-cl.readthedocs.io), organizada por tarea:

| Página | Para qué |
|---|---|
| [Cómo se usa](https://mcp-pjud-cl.readthedocs.io/es/latest/uso.html) | Cómo leer cada campo y qué no hace. Sin código |
| [Instalación y operación](https://mcp-pjud-cl.readthedocs.io/es/latest/instalacion.html) | Arquitectura y controles, para quien administra los sistemas |
| [Ejemplos](https://mcp-pjud-cl.readthedocs.io/es/latest/ejemplos.html) | Casos resueltos de punta a punta, incluidos los modos de falla |
| [Herramientas](https://mcp-pjud-cl.readthedocs.io/es/latest/herramientas.html) | Parámetros y campos de respuesta |
| [Cumplimiento](https://mcp-pjud-cl.readthedocs.io/es/latest/cumplimiento.html) | Condiciones de uso, robots.txt, Ley 21.719 |
| [Licencia](https://mcp-pjud-cl.readthedocs.io/es/latest/licencia.html) | Qué se eligió, qué se descartó y qué cuesta |
| [Hoja de ruta](https://mcp-pjud-cl.readthedocs.io/es/latest/roadmap.html) | Qué está probado contra el sistema real y qué no |

En el repositorio: [cómo contribuir](.github/CONTRIBUTING.md) ·
[acuerdo de contribución](CLA.md) · [uso aceptable](ACCEPTABLE_USE.md) ·
[seguridad](.github/SECURITY.md) · [soporte](.github/SUPPORT.md) ·
[código de conducta](.github/CODE_OF_CONDUCT.md) · [cambios](CHANGELOG.md) ·
[instrucciones para agentes de IA](AGENTS.md)

## Desarrollo

```bash
git clone https://github.com/notluquis/mcp-pjud-cl && cd mcp-pjud-cl
uv sync --all-groups
uv run pytest        # sin red
uv run ruff check .
```

Los tests corren contra HTML real guardado en `tests/fixtures/`, anonimizado. Ninguno consulta
al Poder Judicial.

`main` exige pull request. Antes de proponer cambios, lee
[cómo contribuir](.github/CONTRIBUTING.md).

---

Esto acerca la fuente oficial. No reemplaza la revisión de un abogado ni la lectura del
expediente.
