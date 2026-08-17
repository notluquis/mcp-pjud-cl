# Instalación y operación

## Qué es

Un servidor [Model Context Protocol](https://modelcontextprotocol.io) en Python que expone la
consulta pública de causas del Poder Judicial de Chile como herramientas invocables por un
cliente MCP.

Solo lectura. Cuatro dependencias. Sin base de datos, sin navegador, sin credenciales.

## Instalación

No hace falta clonar el repositorio: `uvx` lo descarga y lo ejecuta. Requiere
[uv](https://docs.astral.sh/uv/) y Python 3.13 o superior.

### La variable de contacto es obligatoria

```bash
MCP_PJUD_CONTACTO="informatica@estudio.cl"
```

Sin ella el servidor **no arranca**. Ese correo viaja en el `User-Agent` de cada petición:

```
User-Agent: mcp-pjud/0.2.1 (+contacto: informatica@estudio.cl)
```

Es deliberado. El Poder Judicial debe poder identificar y contactar a quien consulta. No hay
forma de omitirlo.

### Según tu cliente

::::{tab-set}

:::{tab-item} Claude Code
```bash
claude mcp add pjud -e MCP_PJUD_CONTACTO=informatica@estudio.cl \
  -- uvx --from git+https://github.com/notluquis/mcp-pjud-cl@stable mcp-pjud
```
:::

:::{tab-item} Claude Desktop
En `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pjud": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/notluquis/mcp-pjud-cl@stable", "mcp-pjud"],
      "env": { "MCP_PJUD_CONTACTO": "informatica@estudio.cl" }
    }
  }
}
```
:::

:::{tab-item} Cursor
En `~/.cursor/mcp.json`, o por el botón de un clic del README:

```json
{
  "mcpServers": {
    "pjud": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/notluquis/mcp-pjud-cl@stable", "mcp-pjud"],
      "env": { "MCP_PJUD_CONTACTO": "informatica@estudio.cl" }
    }
  }
}
```
:::

:::{tab-item} VS Code
En `.vscode/mcp.json`. **Ojo con la diferencia**: acá la clave es `servers`, no `mcpServers`
como en el resto. Pegar el bloque de Claude Desktop no funciona.

```json
{
  "servers": {
    "pjud": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/notluquis/mcp-pjud-cl@stable", "mcp-pjud"],
      "env": { "MCP_PJUD_CONTACTO": "informatica@estudio.cl" }
    }
  }
}
```
:::

:::{tab-item} Codex
```bash
codex mcp add pjud --env MCP_PJUD_CONTACTO=informatica@estudio.cl \
  -- uvx --from git+https://github.com/notluquis/mcp-pjud-cl@stable mcp-pjud
```

O a mano, en `~/.codex/config.toml`:

```toml
[mcp_servers.pjud]
command = "uvx"
args = ["--from", "git+https://github.com/notluquis/mcp-pjud-cl@stable", "mcp-pjud"]
env = { MCP_PJUD_CONTACTO = "informatica@estudio.cl" }
```
:::

::::

El [README](https://github.com/notluquis/mcp-pjud-cl) trae además botones de instalación
de un clic para Cursor y VS Code. Dejan el correo como marcador y hay que editarlo.

El transporte es stdio. No abre puertos ni escucha en la red.

### Qué versión se instala

Lo que va después de `@` en la URL de git decide qué código corre, y las tres opciones tienen
consecuencias distintas:

| Referencia | Qué corre | Cuándo conviene |
|---|---|---|
| `@stable` | La última versión **publicada**. Se actualiza sola al instalar | Es lo que la documentación recomienda y lo que traen los ejemplos |
| `@v0.2.1` | Esa versión y ninguna otra | Cuando el entorno exige que nada cambie sin revisión |
| sin `@` | La rama principal, con cambios **sin publicar** | Para desarrollar sobre el proyecto, no para trabajar con causas |

`stable` se mueve sola: el flujo de publicación la avanza a cada etiqueta, y sólo después de
que la versión se creó sin errores. Si una publicación falla, `stable` se queda donde estaba.

Para fijar una versión concreta:

```
"args": ["--from", "git+https://github.com/notluquis/mcp-pjud-cl@v0.2.1", "mcp-pjud"]
```

### Desde un clon, para desarrollar

```bash
git clone https://github.com/notluquis/mcp-pjud-cl
cd mcp-pjud-cl
uv sync --all-groups
```

### Verificar

```bash
uv run pytest        # sin red
uv run ruff check .
```

Los tests corren contra HTML real guardado en `tests/fixtures/`. **Ninguno consulta al Poder
Judicial**, así que se pueden correr en CI sin generar tráfico a la plataforma.

## Arquitectura

Tres módulos, unas 508 líneas de código.

```
src/mcp_pjud/
  server.py    Herramientas MCP, anotaciones, directiva operativa
  client.py    Cadena HTTP, control de ritmo, detención
  parser.py    Extracción de las tablas. Sin red: se prueba offline
```

### La cadena de peticiones

```
GET  includes/sesion-consultaunificada.php   →  sesión pública (sin Clave Única)
GET  consultaUnificada.php                   →  se derivan prefijo de rutas y token
POST {prefijo}/civil/consultaRitCivil.php    →  listado + referencia opaca de la causa
POST {prefijo}/civil/modal/causaCivil.php    →  detalle + lista de cuadernos
     ... una vez por cada cuaderno ...
```

La plataforma **no direcciona el detalle por rol**: cada fila del listado trae una referencia
opaca que caduca a los 30 minutos. Por eso `obtener_actuaciones_receptor` encadena
internamente en vez de ser una llamada suelta.

El prefijo de rutas y el token de los modales **se derivan en caliente** del HTML de
`consultaUnificada.php`. Se verificó que el token rota en cada sesión; hardcodearlo habría
roto todas las rutas a la vez y sin aviso.

### Por qué no hay navegador

Se midió antes de decidir:

| Cliente | User-Agent | Resultado |
|---|---|---|
| curl | `curl/8.x` | **403 Forbidden** |
| curl | `python-requests/2.32 bot` | 200 |
| curl | `mcp-pjud/0.1 (+contacto)` | 200 |

Mismo binario, mismo handshake TLS, misma huella JA3. Lo único que cambió fue un header: el
filtro actúa sobre el **string del User-Agent**, no sobre la huella TLS.

Consecuencias: Playwright es innecesario, e impersonar un fingerprint TLS (`curl_cffi`,
`Impit`) no aporta nada, porque no hay nada en la capa TLS que sortear. HTTP plano con user
agent identificable pasa, que además es lo que exige la política de uso responsable del
proyecto. El camino que cumple es el mismo que funciona.

## Controles que no se deben tocar

Están en `client.py` y existen por razones jurídicas y operacionales, no de rendimiento.

### Ritmo: 5 segundos sostenidos, ráfaga de 4

```python
INTERVALO_MINIMO = 5.0
```

Es la implementación de la **cláusula CUARTA** de las condiciones de uso de la Oficina
Judicial Virtual, que prohíbe "dañar, inutilizar, **sobrecargar**, deteriorar el Portal o
impedir su normal utilización".

El constructor **rechaza** cualquier valor menor. Hay un test que lo verifica, y un job de CI
que falla si la constante cambia.

### Detención total ante bloqueo

Ante 403 o 429 se levanta `PjudBloqueado` y se detiene. **Sin reintento, sin rotación de IP,
sin evasión.**

El riesgo que esto protege es concreto: si la IP del estudio queda bloqueada, se pierde el
acceso a la consulta de las causas propias mientras corren plazos en litigios activos. Eso
pesa más que cualquier dato que se quisiera obtener.

### Fallo ruidoso

Si el parser no encuentra la tabla o las columnas esperadas, levanta `EstructuraInesperada`.
**Nunca devuelve una lista vacía.**

Una lista vacía se lee como "no hubo actuaciones". Un falso negativo acá significa dar por no
corrido un plazo que sí corrió.

### Sin persistencia

Se consulta y se devuelve. No hay base de datos ni caché en disco. La `bitacora` del cliente
guarda timestamp, URL y código de estado en memoria, y se pierde al terminar el proceso.

Si tu organización decide almacenar resultados, pasa a ser responsable del tratamiento bajo
la Ley 21.719. Ver {doc}`cumplimiento`.

## Operación

### Cuánto demora

Una consulta de actuaciones son 4 o 5 peticiones, y la ráfaga está dimensionada justo para
esa cadena: **la primera consulta sale casi de inmediato**, unos 5 segundos. La segunda
seguida ya espera, y sin ráfaga disponible son entre 20 y 30 segundos por causa.

El régimen sostenido **no es optimizable**: el cuello es el control de ritmo y es deliberado.
Lo que la ráfaga cambió no es ese régimen sino la latencia de responder una pregunta suelta;
sobre una tanda larga el tiempo total es prácticamente el mismo.

Esto descarta de entrada cualquier uso masivo. Si necesitas revisar 200 causas, son unas dos
horas de reloj, y correr instancias en paralelo para acelerarlo va contra la cláusula CUARTA.

### La bitácora

`cliente.bitacora` guarda una tupla por petición: momento, URL y estado. Es lo que permite
acreditar cuánto se consultó, que es la contracara del compromiso de no sobrecargar.

Las peticiones que mueren por timeout se anotan con **estado 0**, que ningún código HTTP usa.
Importa porque una petición sin respuesta igual salió a la red: sin registrarla, el registro
subestimaría el tráfico justo en las corridas donde la plataforma va peor, que son las que uno
querría poder explicar.

### Qué monitorear

- `PjudBloqueado` → revisar si la IP quedó bloqueada **antes** de reintentar nada.
- `EstructuraInesperada` → la plataforma cambió. Reportar con la plantilla correspondiente.
- `discrepancia_fechas: true` en la salida → dato que necesita revisión humana.

### Qué NO hacer

- Correr varias instancias en paralelo contra la plataforma.
- Bajar el intervalo, ni siquiera "para una prueba rápida".
- Reintentar automáticamente después de un 403.
- Barrer rangos de roles.
- Exponer el servidor a la red: está diseñado para stdio local.

## Licencia y permisos

[PolyForm Strict 1.0.0](https://polyformproject.org/licenses/strict/1.0.0). Permite
**ejecutar** el software con fines no comerciales.

**Necesitas permiso escrito para:**

- Usarlo en un estudio que factura a sus clientes
- Modificarlo o adaptarlo, incluido cualquier parche interno
- Instalarlo para terceros fuera de tu organización

Se pide [abriendo un issue](https://github.com/notluquis/mcp-pjud-cl/issues/new/choose), se
otorga caso a caso y sin costo. Si tu departamento legal necesita revisar el texto, PolyForm
es una familia de licencias estándar redactada por abogados de licenciamiento, no un texto a
medida.
