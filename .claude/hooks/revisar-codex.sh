#!/usr/bin/env bash
# Avisa cuando Codex dejó hallazgos sin resolver, antes de dar el turno por terminado.
#
# El hook de al lado PIDE la revisión. Éste cierra el otro extremo: sin él, la revisión
# llega minutos después y no la mira nadie hasta que a alguien se le ocurre preguntar. En
# esta sesión eso se resolvió con esperas en segundo plano, una por ronda, a mano.
#
# Se dispara en `Stop`, que es cuando el turno va a terminar, y sale con código 2, que en
# ese evento es lo único que hace dos cosas a la vez: impedir que el turno termine y
# mostrar `stderr` al modelo. Con código 0 el mensaje se va al registro de depuración y no
# lo lee nadie.
#
# Los dos hooks no se realimentan, y conviene dejar escrito por qué. Éste no empuja nada,
# así que no puede disparar al otro por sí solo. El ciclo que sí existe es el deseado: avisa,
# se arregla, se empuja, el otro pide revisión, llegan hallazgos nuevos, vuelve a avisar. Ese
# termina porque cada hallazgo interrumpe una sola vez y arreglarlos es trabajo finito.
#
# El seguro contra quedarse en bucle es una marca POR HILO: cada hallazgo interrumpe como
# mucho una vez en la vida del repositorio. Si se decide no actuar sobre uno, no vuelve a
# aparecer. No se usa `stop_hook_active` porque eso sólo dice "ya bloqueaste una vez",
# que es demasiado grueso: taparía el segundo hallazgo del mismo turno.
set -uo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || exit 0
# Mismo motivo que en el hook de al lado: en un worktree `.git` es un archivo, y la cuenta va
# en el directorio COMÚN porque un hallazgo es de un pull request y no de un worktree. Con la
# ruta privada, el mismo hallazgo interrumpía una vez por cada worktree abierto.
comun=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
marcas="$comun/codex-visto"
mkdir -p "$marcas" 2>/dev/null || exit 0

# Una sola consulta para todos los pull requests abiertos: esto corre al final de CADA
# turno, así que una llamada por PR se paga en cada respuesta.
# UNA consulta para todo, no una por pull request. La versión anterior prometía eso en un
# comentario y hacía `1 + 3N` llamadas seriales: una lista, más una GraphQL y DOS
# `gh repo view` por PR, dentro del bucle. Corre al final de CADA turno, así que el costo se
# paga en cada respuesta aunque no haya nada que avisar.
#
# Y con paginación: `reviewThreads(first: 50)` incluye los ya resueltos, así que en un pull
# request con muchas rondas un hallazgo nuevo podía quedar fuera de la página y no aparecer
# nunca. Acá hay uno con más de veinte hilos y este flujo los acumula rápido.
repo=$(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"' 2>/dev/null) || exit 0

# La consulta y el filtro en variables de una línea. Pasarlos con saltos de línea dentro de
# `-f query=` hacía que `gh` no reconociera sus propias banderas y devolviera el texto de uso:
# fallaba en silencio, con salida 0 y sin hilos, o sea el hook no avisaba nunca.
# La variable se llama `$endCursor` y no otra cosa: `gh api --paginate` exige ese nombre
# exacto («requires that the original query accepts an `$endCursor: String` variable»). Con
# `$cursor`, la segunda página fallaba, el error iba a `/dev/null` y el hook no avisaba ni
# siquiera de los hilos de la primera.
#
# Y los hilos van con `last`, no con `first`. `--paginate` sólo recorre la conexión externa,
# así que la interna se trunca igual por mucho que se suba el número. `last` trae los MÁS
# RECIENTES, que es exactamente lo que este hook busca: hallazgos nuevos. Uno viejo sin
# resolver ya tiene su marca, así que perderlo no cambia nada.
consulta='query($duenio: String!, $nombre: String!, $endCursor: String) { repository(owner: $duenio, name: $nombre) { pullRequests(states: OPEN, first: 50, after: $endCursor) { pageInfo { hasNextPage endCursor } nodes { number reviewThreads(last: 100) { nodes { id isResolved path line comments(first: 1) { nodes { author { login } body } } } } } } } }'
filtro='.[].data.repository.pullRequests.nodes[] | .number as $n | .reviewThreads.nodes[] | select(.isResolved == false) | select(.comments.nodes[0].author.login == "chatgpt-codex-connector") | "\($n)\t\(.id)\t\(.path):\(.line)\t\(.comments.nodes[0].body | split("\n")[0] | sub("^.*</sub></sub>\\s*"; "") | gsub("\\*\\*"; ""))"'

# El filtro va por una tubería a `jq` y no por `--jq`: `gh` rechaza `--slurp` junto con
# `--jq` («the `--slurp` option is not supported with `--jq`»), y con el error mandado a
# `/dev/null` eso se veía como cero hilos. El hook salía 0 sin avisar de nada.
# Pedidos sin responder: el último pedido de revisión de cada pull request abierto que no
# tenga respuesta después. Los dos revisores se piden distinto -`@codex review` y
# `/gemini review`- y el hook mira los dos, porque un push debería despertarlos a ambos.
# El login de Codex se compara con `test("codex")` y no por igualdad, y la razón es del
# ESQUEMA y no del bot: REST siempre devuelve `chatgpt-codex-connector[bot]`, GraphQL lo
# devuelve sin sufijo en `reviews.author` y `comments.author` -que son de tipo `Actor`- y CON
# sufijo en `reactions.user`, que es de tipo `User`. Medido sobre el mismo pull request con
# las dos APIs. Le pasa a cualquier App, y una misma consulta mezcla los dos tipos sin avisar.
#
# Las respuestas de Codex llegan por TRES superficies y hay que mirar las tres. Una pasada
# con hallazgos deja una review con hilos; una limpia, a veces un comentario; y a veces sólo
# una REACCIÓN de pulgar arriba en el pull request, que no aparece ni en `comments` ni en
# `reviews`. Medido acá: el #79 quedó aprobado a las 12:20:47 con reacción y nada más, así que
# mirar dos superficies lo daba por pendiente para siempre.
consulta_pedidos='query($duenio: String!, $nombre: String!, $endCursor: String) { repository(owner: $duenio, name: $nombre) { pullRequests(states: OPEN, first: 50, after: $endCursor) { pageInfo { hasNextPage endCursor } nodes { number headRefOid comments(last: 60) { nodes { createdAt body author { login } } } reviews(last: 60) { nodes { submittedAt body author { login } commit { oid } } } reactions(last: 20) { nodes { createdAt user { login } } } } } } }'
# Responder no basta: la respuesta tiene que ser SOBRE el commit de ahora. Un revisor puede
# contestar en segundos con una revisión de un commit anterior, que es justamente el problema
# que estos hooks existen para cerrar; tomarla por respuesta lo reintroduce.
#
# El campo que lo dice es `reviews.nodes[].commit.oid`, y es estrictamente mejor que buscar
# un sha en la prosa: lo traen los DOS revisores (Codex imprime `Reviewed commit` en el
# cuerpo, Gemini no imprime ninguno) y no depende del orden temporal, que da falso positivo
# cuando la revisión llega tarde y ya hubo otro push.
#
# Cuenta como respondido: una revisión DE UN REVISOR sobre el commit de ahora -el filtro
# por autor importa: una revisión humana en el mismo commit no es la respuesta que se pidió-, una reacción posterior al
# pedido (una pasada limpia de Codex no deja más que eso), o un comentario posterior cuyo
# cuerpo nombre el commit, que es como Codex publica su veredicto limpio.
filtro_pedidos='.[].data.repository.pullRequests.nodes[] | .number as $n | (.headRefOid[0:10]) as $sha | ((.comments.nodes | map(select(.body == "@codex review" or .body == "/gemini review")) | last) // empty) as $p | ([.reactions.nodes[] | select(.user.login | test("codex|gemini")) | .createdAt] | map(select(. > $p.createdAt)) | length) as $ok_reaccion | ([.reviews.nodes[] | select(.author.login | test("codex|gemini")) | select(.commit.oid | startswith($sha))] | length) as $ok_review | ([.comments.nodes[] | select(.author.login | test("codex|gemini")) | select(.createdAt > $p.createdAt) | .body] | map(select(contains($sha))) | length) as $ok_sha | ([.comments.nodes[] | select(.author.login | test("codex|gemini")) | select(.createdAt > $p.createdAt) | .body] | map(select(test("usage limits|reached your Codex"))) | length) as $sin_cuota | if ($ok_reaccion + $ok_review + $ok_sha) == 0 then "\($n)\t\($p.createdAt)\t\(if $sin_cuota > 0 then "cuota" else "espera" end)" else empty end'

hilos=$(gh api graphql --paginate --slurp -f query="$consulta" \
  -F duenio="${repo% *}" -F nombre="${repo#* }" 2>/dev/null | jq -r "$filtro" 2>/dev/null) || exit 0

nuevos=""
while IFS=$'\t' read -r n id donde titulo; do
  [[ -n "$id" ]] || continue
  [[ -f "$marcas/$id" ]] && continue
  : > "$marcas/$id" 2>/dev/null || continue
  nuevos+="  #$n $donde
      $titulo
"
done <<< "$hilos"

# Si no hay hallazgos nuevos, todavía puede haber un pedido EN VUELO. Ése es el agujero que
# el diseño tenía: cuando lo último del turno es un push, este hook consulta una vez, la
# revisión todavía no llegó, el turno termina y no hay otro evento `Stop` cuando Codex
# publica minutos después. O sea el caso más común -empujar y dar por terminado- era
# justamente el que se perdía.
#
# Se interrumpe una vez por pedido, no por turno: la marca lleva el instante del pedido, así
# que el mismo no vuelve a frenar y uno nuevo sí. Sin eso, o se frena para siempre o se frena
# una sola vez y el segundo push del turno queda sin cubrir.
if [[ -z "$nuevos" ]]; then
  pendiente=$(gh api graphql --paginate --slurp -f query="$consulta_pedidos" \
    -F duenio="${repo% *}" -F nombre="${repo#* }" 2>/dev/null \
    | jq -r "$filtro_pedidos" 2>/dev/null) || exit 0
  [[ -n "$pendiente" ]] || exit 0

  while IFS=$'\t' read -r n cuando motivo; do
    [[ -n "$cuando" ]] || continue
    marca="$marcas/pedido-$n-${cuando//[:.]/-}"
    [[ -f "$marca" ]] && continue
    : > "$marca" 2>/dev/null || continue
    # Sin cuota NO es lo mismo que en camino, y es el estado que cuela un pull request sin
    # revisar: en las demás superficies se ve idéntico a "pendiente", así que uno espera algo
    # que no va a llegar. Se separan porque piden cosas distintas.
    if [[ "$motivo" == "cuota" ]]; then
      cat >&2 <<MSG
La revisión pedida en #$n NO va a llegar: Codex respondió que se agotó la cuota de
revisiones ($cuando).

Esperarla es perder el tiempo. Se puede volver a pedir más tarde, cuando la ventana se
reponga, o mezclar sabiendo que va sin revisar y dejándolo dicho.
MSG
    else
      cat >&2 <<MSG
Hay una revisión de Codex pedida en #$n y todavía sin responder ($cuando).

Llega en minutos y este es el último aviso: si el turno termina acá, nadie la va a mirar.
Espérala en segundo plano y revisa los hallazgos antes de cerrar. Cada pedido avisa una
sola vez.
MSG
    fi
    exit 2
  done <<< "$pendiente"
  exit 0
fi

cat >&2 <<MSG
Codex dejó hallazgos sin resolver que todavía no se han mirado:

$nuevos
Léelos con \`gh api graphql\` sobre \`reviewThreads\`, evalúa cada uno por su cuenta, y si
son correctos arregla, verifica en rojo, responde en el hilo y resuélvelo. Si alguno no lo
es, di por qué con evidencia. Cada hallazgo avisa una sola vez: si no se actúa ahora, no
vuelve a aparecer.
MSG
exit 2
