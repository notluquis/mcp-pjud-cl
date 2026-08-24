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

**2. El ritmo de las consultas no se relaja.** Régimen sostenido de una petición cada 5
segundos, con una ráfaga máxima de 4. `INTERVALO_MINIMO` y `RAFAGA_MAXIMA` en
`src/mcp_pjud/client.py` implementan juntos la cláusula CUARTA de las condiciones de uso, que
prohíbe sobrecargar la plataforma. No son constantes de rendimiento. El constructor rechaza
intervalos menores y hay un job de CI que verifica las dos, porque subir la ráfaga vacía la
garantía sin tocar el número que todos miran.

La ráfaga existe porque la sobrecarga es una propiedad del régimen: al portal le importa
cuántas peticiones recibe, no cómo se reparten dentro de un minuto. Una consulta de
actuaciones son cinco peticiones encadenadas para responder una sola pregunta, y con un
intervalo plano tardaba veinticinco segundos. El tope de 4 la acota a esa cadena: alcanza para
responder de una vez, no para barrer.

**3. Ante 403, 429 o captcha: detención total.** Sin reintento, sin rotación de IP, sin
evasión, sin impersonación de fingerprint TLS. Si el sistema bloquea, la respuesta correcta es
parar y avisar.

Total significa del proceso, no del host que rechazó. Se evaluó acotarla por host cuando entró
el buscador de fallos y se descartó al medir: los dos responden con la cookie `TS<hex>` de F5
BIG-IP, o sea comparten cortafuegos y el 403 llega antes de la aplicación.

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
  client.py    `Transporte` (ritmo, detención, bitácora) y la consulta de causas
  juris.py     Buscador de fallos. Comparte el transporte, no la sesión
  parser.py    Extracción de tablas. Sin red: se prueba offline
tests/
  fixtures/    Respuestas reales anonimizadas. Ningún test consulta al Poder Judicial
docs/          Documentación publicada en Read the Docs
```

## Comandos

```bash
uv sync --all-groups
uv run pytest              # sin red
uv run ruff check . && uv run ruff format --check .
uv run ty check            # sin chequeador de tipos pasaban firmas que reventaban
uv run cog --check README.md docs/instalacion.md      # bloques generados, sin editar a mano
uv run sphinx-build -W -b html docs docs/_build/html   # -W: un aviso es un error
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

**Documentación:** `docs/` sigue [Diátaxis](https://diataxis.fr/), que separa cuatro cosas que
se suelen mezclar. Antes de escribir una página nueva, decide cuál es y ponla donde va:

| Tipo | Sirve para | Acá |
|---|---|---|
| Cómo se hace | resolver una tarea concreta | `instalacion`, `ejemplos` |
| Referencia | consultar un dato exacto | `herramientas` |
| Explicación | entender por qué | `uso`, `cumplimiento`, `licencia`, `roadmap` |
| Tutorial | aprender haciendo | no hay, y no hace falta |

Mezclarlas es lo que produce una página que no sirve para nada: una referencia con opiniones
no se puede consultar rápido, y una explicación con tablas de parámetros no se puede leer.

**Un dato repetido es un dato que va a quedar viejo.** Las cifras medidas, el intervalo mínimo
y los topes viven en el código y se interpolan donde se pueda. Donde no se puede, porque la
prosa se escribe a mano, `tests/test_documentacion.py` compara cada dato repetido contra su
única fuente. Si agregas una afirmación verificable a la documentación, agrégale el test.

**Commits:** [Conventional Commits](https://www.conventionalcommits.org/es/) en español.

**El registro de cambios no es el lugar para contar la historia.** Cada entrada de
`CHANGELOG.md` dice QUÉ cambió y, si hace falta, qué tiene que hacer distinto quien actualiza.
**Una o dos frases**, no una o dos líneas ajustadas. Cómo se encontró el problema, qué
hipótesis fallaron y por qué se eligió una versión y no otra van en el PR y en el mensaje del
commit, que es donde alguien los busca.

Se degradó solo una vez: las entradas pasaron a ser párrafos, una versión llegó a 333 líneas
con 67 viñetas, y encima repetían lo que la sección de al lado ya decía. `test_documentacion.py`
acota el largo de cada viñeta.

Ojo con lo que ese guardia puede y no puede hacer: cuenta líneas, así que atrapa el desborde y
no el contenido. Una viñeta que justo cabe en el límite y enumera cómo funciona algo lo pasa sin
problema, y aun así sobra. Eso ya se coló dos veces.

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
- Agregar competencias sin verificarlas contra el sistema real. Hay seis verificadas y son las
  que `MODULOS` nombra; lo que no está ahí se rechaza a propósito en vez de adivinar sus
  parámetros. El detalle se lee en cinco: en penal se busca y no se abre, por decisión.
- Levantar un segundo servidor MCP para jurisprudencia. Serían dos procesos con dos
  semáforos, o sea el doble de peticiones contra la misma institución, y `ACCEPTABLE_USE.md`
  prohíbe correr instancias en paralelo. Por eso `juris.py` comparte el transporte.
- Agregar buscadores de `juris.pjud.cl` sin verificarlos. Cada uno declara sus propios campos
  Solr, y diez de los diez están medidos. Se exponen siete, y los tres que quedan fuera es por
  decisión y no por falta de medición: penales y el compendio de extranjería publican datos de
  una persona (el nombre del imputado, la nacionalidad del recurrente), y líneas
  jurisprudenciales no es un buscador de fallos, sino de temas que reusan los mismos campos
  Solr con otro significado.
- Presentar la salida como información oficial del Poder Judicial.
