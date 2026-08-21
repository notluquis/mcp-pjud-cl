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

# El detector de push es lo más frágil de todo esto y ya falló una vez, por subcadena. Vive
# en una función para poder probarlo, y los casos de `--probar` corren contra ESTA función y
# no contra una copia del patrón pegada en otro archivo: una copia sólo prueba que la copia
# funciona.
es_un_push() {
  printf '%s' "$1" | grep -qE '(^|[;&|]|&&|\|\|)[[:space:]]*(sudo[[:space:]]+)?git([[:space:]]+-[^[:space:]]+([[:space:]]+[^[:space:]-][^[:space:]]*)?)*[[:space:]]+push([[:space:]]|$)'
}

if [[ "${1:-}" == "--probar" ]]; then
  fallos=0
  probar() {  # $1: 0 si debe detectarse, 1 si no
    if es_un_push "$2"; then real=0; else real=1; fi
    if [[ "$real" != "$1" ]]; then
      fallos=$((fallos + 1))
      printf '  FALLA  %s: %s\n' \
        "$([[ $1 == 0 ]] && echo 'debía detectarse' || echo 'no debía detectarse')" "$2" >&2
    fi
  }
  probar 0 'git push'
  probar 0 'git push -q -u origin rama'
  probar 0 'git push -f'
  probar 0 'git push --force-with-lease'
  probar 0 'git add -A && git commit -q -m x && git push'
  probar 0 'cd /x; git push'
  probar 0 'git -C /otro/repo push'
  probar 0 'git -c user.name=x push'
  probar 1 'echo git push'
  probar 1 'grep -n "git push" hook.sh'
  probar 1 'rg "git push" .'
  probar 1 '# git push va despues'
  probar 1 'git log --oneline'
  probar 1 'gh pr view 81'
  probar 1 'git status'
  if [[ $fallos -gt 0 ]]; then
    echo "$fallos de 15 casos del detector de push fallaron." >&2
    exit 1
  fi
  echo "15 casos del detector de push, todos como se espera."
  exit 0
fi

entrada=$(cat)
comando=$(printf '%s' "$entrada" | /usr/bin/python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null) || exit 0
# Que se haya EJECUTADO un push, no que el texto lo mencione. `echo git push`,
# `grep "git push" .` y un comentario de shell traen esas dos palabras y no empujan nada, y
# con la marca ausente cualquiera de ellos publicaba un pedido. Se exige que `git` esté en
# posición de comando (principio de línea o después de un separador) y que `push` sea su
# subcomando, con las opciones globales que git acepta en medio.
es_un_push "$comando" || exit 0

cd "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || exit 0

# ¿Llegó? Si el remoto no tiene lo mismo que HEAD, no hay nada nuevo que revisar.
local_sha=$(git rev-parse HEAD 2>/dev/null) || exit 0
remoto_sha=$(git rev-parse '@{u}' 2>/dev/null) || exit 0
[[ "$local_sha" == "$remoto_sha" ]] || exit 0

# `--git-common-dir` y no `.git/` a secas. Dos motivos. En un checkout hecho con `git worktree`,
# `.git` es un ARCHIVO, así que escribir dentro falla. Y como el script no usa `set -e`,
# fallaba en silencio: el pedido salía igual y cada push siguiente del mismo SHA volvía a
# publicarlo. Acá se trabaja con worktrees a diario, así que era el caso normal y no el raro.
#
# Y COMÚN, no privada del worktree: un commit es el mismo commit se empuje desde donde se
# empuje. Con la ruta privada cada worktree llevaba su propia cuenta y el mismo SHA pedía
# una revisión por cada uno.
comun=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
marca="$comun/codex-pedido-$local_sha"
[[ -f "$marca" ]] && exit 0

rama=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
datos=$(gh pr view "$rama" --json number,isDraft,state 2>/dev/null) || exit 0
numero=$(printf '%s' "$datos" | /usr/bin/python3 -c \
  'import json,sys; d=json.load(sys.stdin); print(d["number"] if d.get("state")=="OPEN" and not d.get("isDraft") else "")' 2>/dev/null)
[[ -n "$numero" ]] || exit 0

# Si el pedido anterior quedó sin contestar, decirlo. Es el único modo de falla silencioso
# que le queda al diseño: cuando se agota la cuota de revisiones, el comentario `@codex
# review` se ve EXACTAMENTE igual esté contestado o no, así que uno cree que revisó y no
# revisó. Se avisa y se pide igual, porque puede haberse repuesto la ventana.
sin_contestar=$(gh pr view "$numero" --json comments,reviews --jq '
  [.comments[], .reviews[]]
  | (map(select(.author.login != "chatgpt-codex-connector" and (.body // "") == "@codex review")) | last) as $pedido
  | if $pedido == null then "no"
    else (map(select(.author.login == "chatgpt-codex-connector"
                     and ((.createdAt // .submittedAt) > ($pedido.createdAt // $pedido.submittedAt))))
          | if length == 0 then "si" else "no" end)
    end' 2>/dev/null)
aviso=""
[[ "$sin_contestar" == "si" ]] && aviso="El pedido anterior en #$numero sigue sin respuesta de Codex: puede ser la cuota agotada. "

if gh pr comment "$numero" --body "@codex review" >/dev/null 2>&1; then
  if : > "$marca" 2>/dev/null; then
    aviso+="Revisión de Codex pedida en #$numero para ${local_sha:0:7}."
  else
    # Sin marca no hay protección contra el duplicado, y decirlo es mejor que fingir que sí.
    aviso+="Revisión pedida en #$numero, pero no se pudo dejar la marca en $marca: el próximo push del mismo commit la va a repetir."
  fi
fi

# Por `systemMessage` y no por `stderr`. En `PostToolUse` con código 0 la documentación dice
# que «Claude Code shows nothing in the conversation», y stdout y stderr sólo salen con
# `--debug`: el aviso del pedido colgado, que es el único que hay que ver, era invisible justo
# para quien tiene que actuar. Y no con código 2, cuya semántica acá es ambigua porque la
# herramienta ya corrió: `systemMessage` es el campo documentado para decir algo sin bloquear.
if [[ -n "$aviso" ]]; then
  printf '%s' "$aviso" | /usr/bin/python3 -c \
    'import json,sys; print(json.dumps({"systemMessage": sys.stdin.read(), "continue": True}))'
fi
exit 0
