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
# comentario y hacía `1 + 3N` llamadas seriales: el `gh pr list`, más una GraphQL y DOS
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
consulta='query($duenio: String!, $nombre: String!, $cursor: String) { repository(owner: $duenio, name: $nombre) { pullRequests(states: OPEN, first: 25, after: $cursor) { pageInfo { hasNextPage endCursor } nodes { number reviewThreads(first: 100) { nodes { id isResolved path line comments(first: 1) { nodes { author { login } body } } } } } } } }'
filtro='.[].data.repository.pullRequests.nodes[] | .number as $n | .reviewThreads.nodes[] | select(.isResolved == false) | select(.comments.nodes[0].author.login == "chatgpt-codex-connector") | "\($n)\t\(.id)\t\(.path):\(.line)\t\(.comments.nodes[0].body | split("\n")[0] | sub("^.*</sub></sub>\\s*"; "") | gsub("\\*\\*"; ""))"'

# El filtro va por una tubería a `jq` y no por `--jq`: `gh` rechaza `--slurp` junto con
# `--jq` («the `--slurp` option is not supported with `--jq`»), y con el error mandado a
# `/dev/null` eso se veía como cero hilos. El hook salía 0 sin avisar de nada.
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

[[ -n "$nuevos" ]] || exit 0

cat >&2 <<MSG
Codex dejó hallazgos sin resolver que todavía no se han mirado:

$nuevos
Léelos con \`gh api graphql\` sobre \`reviewThreads\`, evalúa cada uno por su cuenta, y si
son correctos arregla, verifica en rojo, responde en el hilo y resuélvelo. Si alguno no lo
es, di por qué con evidencia. Cada hallazgo avisa una sola vez: si no se actúa ahora, no
vuelve a aparecer.
MSG
exit 2
