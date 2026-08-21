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
marcas=".git/codex-visto"
mkdir -p "$marcas" 2>/dev/null || exit 0

# Una sola consulta para todos los pull requests abiertos: esto corre al final de CADA
# turno, así que una llamada por PR se paga en cada respuesta.
abiertos=$(gh pr list --state open --json number --jq '.[].number' 2>/dev/null) || exit 0
[[ -n "$abiertos" ]] || exit 0

nuevos=""
for n in $abiertos; do
  hilos=$(gh api graphql -f query="
    { repository(owner: \"$(gh repo view --json owner --jq .owner.login 2>/dev/null)\",
                 name: \"$(gh repo view --json name --jq .name 2>/dev/null)\") {
        pullRequest(number: $n) {
          reviewThreads(first: 50) { nodes {
            id isResolved path line
            comments(first: 1) { nodes { author { login } body } }
          } } } } }" \
    --jq '.data.repository.pullRequest.reviewThreads.nodes[]
          | select(.isResolved == false)
          | select(.comments.nodes[0].author.login == "chatgpt-codex-connector")
          | "\(.id)\t\(.path):\(.line)\t\(.comments.nodes[0].body
              | split("\n")[0]
              | sub("^.*</sub></sub>\\s*"; "")
              | gsub("\\*\\*"; ""))"' 2>/dev/null) || continue

  while IFS=$'\t' read -r id donde titulo; do
    [[ -n "$id" ]] || continue
    [[ -f "$marcas/$id" ]] && continue
    : > "$marcas/$id"
    nuevos+="  #$n $donde
      $titulo
"
  done <<< "$hilos"
done

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
