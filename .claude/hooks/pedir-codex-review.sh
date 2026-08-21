#!/usr/bin/env bash
# Pide una revisión de Codex después de cada `git push` que de verdad llegó.
#
# Por qué existe: Codex se dispara solo al ABRIR un pull request y al sacarlo de borrador,
# NO en cada push. Una revisión contra el primer commit no dice nada de los que vinieron
# después, y este proyecto empuja varias veces por pull request corrigiendo hallazgos.
#
# Tres decisiones que son las que lo vuelven correcto:
#
#   1. Se comprueba contra el REMOTO que el push llegó, no que el comando se escribió.
#      Parsear la salida de `git push` es frágil: cambia de formato, y un push rechazado
#      igual imprime cosas. Comparar `HEAD` con `@{u}` responde la pregunta real.
#   2. Una marca por SHA, para no dejar dos comentarios idénticos cuando hay dos push
#      seguidos o cuando el segundo no cambió nada.
#   3. Sale 0 siempre. Un hook que bloquea un push se termina desactivando, y entonces no
#      protege nada.
set -uo pipefail

entrada=$(cat)
comando=$(printf '%s' "$entrada" | /usr/bin/python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null) || exit 0
[[ "$comando" == *"git push"* ]] || exit 0

cd "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || exit 0

# ¿Llegó? Si el remoto no tiene lo mismo que HEAD, no hay nada nuevo que revisar.
local_sha=$(git rev-parse HEAD 2>/dev/null) || exit 0
remoto_sha=$(git rev-parse '@{u}' 2>/dev/null) || exit 0
[[ "$local_sha" == "$remoto_sha" ]] || exit 0

marca=".git/codex-pedido-$local_sha"
[[ -f "$marca" ]] && exit 0

rama=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
datos=$(gh pr view "$rama" --json number,isDraft,state 2>/dev/null) || exit 0
numero=$(printf '%s' "$datos" | /usr/bin/python3 -c \
  'import json,sys; d=json.load(sys.stdin); print(d["number"] if d.get("state")=="OPEN" and not d.get("isDraft") else "")' 2>/dev/null)
[[ -n "$numero" ]] || exit 0

if gh pr comment "$numero" --body "@codex review" >/dev/null 2>&1; then
  : > "$marca"
  echo "Revisión de Codex pedida en #$numero para $local_sha." >&2
fi
exit 0
