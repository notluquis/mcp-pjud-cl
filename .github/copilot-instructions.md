Las instrucciones del proyecto están en [AGENTS.md](../AGENTS.md), en la raíz del repositorio.

Resumen de lo que no se negocia: solo lectura, sin código de escritura sobre sistemas del Poder
Judicial ni siquiera desactivado; intervalo mínimo de 5 segundos entre peticiones; detención
total ante 403, 429 o captcha; el parser falla ruidosamente en vez de devolver listas vacías; y
`fecha_diligencia` nunca se confunde con `fecha_registro`, porque la primera es la que corre los
plazos procesales.
