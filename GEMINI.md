# Instrucciones del proyecto

Están en [AGENTS.md](AGENTS.md), en la raíz del repositorio.

Este archivo existe sólo porque Gemini CLI todavía no lee `AGENTS.md`. No duplica su
contenido a propósito: dos archivos con las mismas reglas se desincronizan a la primera
edición.

Lo que no se negocia, en resumen: solo lectura, sin código de escritura sobre sistemas del
Poder Judicial ni siquiera desactivado; régimen sostenido de una petición cada 5 segundos con ráfaga máxima de 4;
detención total ante 403, 429 o captcha; el parser falla ruidosamente en vez de devolver
listas vacías; y `fecha_diligencia` nunca se confunde con `fecha_registro`, porque la primera
es la que corre los plazos procesales.
