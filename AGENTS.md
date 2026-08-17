# Instrucciones para agentes de IA

Este proyecto consulta causas judiciales reales. Lo que devuelve determina el cómputo de
plazos procesales, y un dato mal leído puede costar un plazo. Las reglas de abajo no son
preferencias de estilo.

## Reglas que no se negocian

**1. Nada que escriba en los sistemas del Poder Judicial.** Ni ingreso de escritos, ni
modificación, ni eliminación. No debe existir el código, ni siquiera desactivado ni detrás de
una bandera. Hay un job de CI que busca referencias a endpoints de ingreso y falla si aparecen.

En julio de 2026, un ingreso automatizado masivo hizo colapsar la Oficina Judicial Virtual y
terminó con una IP bloqueada y una solicitud de informe sobre responsabilidades disciplinarias
y penales. La distinción entre **leer** e **ingresar** es la razón por la que este proyecto
puede existir.

**2. El intervalo mínimo entre peticiones no baja de 5 segundos.** `INTERVALO_MINIMO` en
`src/mcp_pjud/client.py` implementa la cláusula CUARTA de las condiciones de uso de la
plataforma, que prohíbe sobrecargarla. No es una constante de rendimiento. El constructor
rechaza valores menores y hay un job de CI que verifica que la constante no cambió.

**3. Ante 403, 429 o captcha: detención total.** Sin reintento, sin rotación de IP, sin
evasión, sin impersonación de fingerprint TLS. Si el sistema bloquea, la respuesta correcta es
parar y avisar.

**4. Fallo ruidoso, nunca lista vacía.** Si el parser no encuentra lo que espera, levanta
`EstructuraInesperada`. Una lista vacía se lee como "no hubo actuaciones", y así se pierden
plazos. Este es el error que el proyecto entero existe para evitar.

**5. Sin persistencia de datos de terceros.** Se consulta y se devuelve.

**6. Las fixtures van anonimizadas.** Las respuestas reales traen RUT y nombres de personas
naturales que son parte en juicios. `tests/test_fixtures.py` lo verifica. El mapeo de
anonimización no se versiona: publicarlo desharía la anonimización.

## Lo que hay que entender antes de tocar el parser

La columna `Fec. Trámite` de la plataforma trae dos fechas en una celda:

```
31/03/2026 (27/03/2026)
 registro    diligencia
```

`fecha_registro` es cuándo el tribunal registró el trámite. `fecha_diligencia` es cuándo el
ministro de fe la practicó, y **es la que corre los plazos**. Nunca las mezcles, nunca las
presentes como una sola, nunca elijas una en silencio cuando las fuentes se contradicen: para
eso existe `discrepancia_fechas`.

El detalle de causa muestra **un cuaderno a la vez**. Leer sólo el que viene por defecto
produce una respuesta que parece completa y omite el cuaderno de apremio, donde viven el
requerimiento de pago y el embargo.

## Estructura

```
src/mcp_pjud/
  server.py    Herramientas MCP, anotaciones, directiva operativa
  client.py    Cadena HTTP, control de ritmo, detención
  parser.py    Extracción de tablas. Sin red: se prueba offline
tests/
  fixtures/    HTML real anonimizado. Ningún test consulta al Poder Judicial
docs/          Documentación publicada en Read the Docs
```

## Comandos

```bash
uv sync --all-groups
uv run pytest              # sin red
uv run ruff check .
uv run sphinx-build -b html docs docs/_build/html
uv run zizmor .github/workflows/ .github/dependabot.yml
uv run mutmut run          # testing de mutación, lento
```

## Cómo se escriben los cambios acá

**Todo cambio de lógica deja un test que puede fallar, y hay que verlo en rojo.** Rompe a
propósito la línea que arreglaste, corre la suite, confirma que se cae, restaura.

No es ritual. Durante el desarrollo esto detectó dos veces guardias que no podían fallar: un
test central que seguía verde con el bug puesto porque otro camino del código tapaba la
regresión, y un chequeo en `grep` cuyo comando erraba y cuya salida vacía se leía como "sin
hallazgos".

**Idioma:** español de Chile en código, comentarios, commits, issues y documentación. Sin
voseo (`tienes`, no `tenés`). Los nombres de campo del modelo también van en español: quien lee
la salida es un abogado chileno.

**Comentarios:** explican por qué, no qué. Un comentario que repite lo que dice la línea
siguiente sobra. Los que valen son los que registran una decisión o una trampa.

**Prosa:** sin guiones largos. Usa comas, paréntesis o dos puntos.

**Commits:** [Conventional Commits](https://www.conventionalcommits.org/es/) en español.

## Licencia y contribuciones

El proyecto usa [PolyForm Strict 1.0.0](LICENSE.md), que no otorga derecho a modificar el
software. El permiso para preparar contribuciones viene del [acuerdo de contribución](CLA.md),
sección 5.

Si actúas por encargo de una persona, esa persona debe aceptar el acuerdo en el pull request.
No lo aceptes en su nombre.

## Qué NO hacer

- Proponer Playwright, Selenium o impersonación TLS. Está medido: el filtro de la plataforma
  actúa sobre el string del User-Agent, no sobre la huella TLS. HTTP plano con user agent
  identificable pasa.
- Agregar competencias sin verificarlas contra el sistema real. Sólo civil está verificada; las
  demás se rechazan a propósito en vez de adivinar sus parámetros.
- Ampliar el alcance a `juris.pjud.cl`. Ese host rechaza nominalmente a los agentes de esta
  clase en su robots.txt.
- Presentar la salida como información oficial del Poder Judicial.
