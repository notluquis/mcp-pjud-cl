# Dónde pedir ayuda

Este proyecto lo mantiene una persona en su tiempo libre. No hay soporte comercial, ni SLA,
ni garantía de respuesta. Dicho eso, hay un orden que funciona mejor:

## Según lo que necesites

| Tu situación | Dónde |
|---|---|
| No entiendo qué significa un campo del resultado | [Discusión → Dudas de uso](https://github.com/notluquis/mcp-pjud/discussions) |
| Quiero usarlo en mi estudio y la licencia no me lo permite | [Issue → Solicitud de permiso](https://github.com/notluquis/mcp-pjud/issues/new/choose) |
| Devolvió algo que no calza con el expediente | [Issue → Dato incorrecto](https://github.com/notluquis/mcp-pjud/issues/new/choose) — es lo más urgente que se puede reportar |
| Dejó de funcionar de un día para otro | [Issue → La OJV cambió](https://github.com/notluquis/mcp-pjud/issues/new/choose) |
| No logro instalarlo | [Discusión → Instalación](https://github.com/notluquis/mcp-pjud/discussions) |
| Encontré una vulnerabilidad | [SECURITY.md](SECURITY.md), nunca un issue público |

## Antes de escribir

Lee la [documentación](https://mcp-pjud.readthedocs.io). Hay dos entradas separadas: una para
abogados y otra para quien administra los sistemas del estudio.

## Lo que este proyecto no hace

Decirlo ahorra tiempo a todos:

- **No ingresa escritos.** Ni ahora ni nunca. Es solo lectura por diseño.
- **No accede a "Mis Causas".** Eso requiere Clave Única; acá sólo se consulta lo público.
- **No ve causas reservadas.**
- **No cubre familia, penal, laboral, cobranza ni cortes.** Sólo civil está verificada.
- **No da asesoría legal.** Acerca la fuente oficial; el criterio profesional es tuyo.

## Si el Poder Judicial cambia su plataforma

Va a pasar. Cuando pase, el software **falla ruidosamente**: levanta una excepción en vez de
devolver una lista vacía. Eso es intencional, porque un resultado vacío se lee como "no hubo
actuaciones" y así se pierden plazos.

Si ves un error de estructura inesperada, abre un issue con la plantilla "La OJV cambió" y
adjunta el mensaje completo. Es el reporte más útil que existe para este proyecto.
