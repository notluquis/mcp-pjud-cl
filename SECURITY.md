# Política de seguridad

## Reportar una vulnerabilidad en este proyecto

No abras un issue público.

Usa [GitHub Security Advisories](https://github.com/notluquis/mcp-pjud-cl/security/advisories/new),
que permite reportar en privado. Respuesta esperada dentro de 7 días.

Interesa especialmente:

- Cualquier ruta por la que el cliente pudiera **escribir** en sistemas del Poder Judicial.
  Eso sería un defecto crítico: la garantía central del proyecto es que no puede.
- Fallas que hagan superar el intervalo mínimo entre peticiones.
- Filtración de datos personales de terceros a disco o a logs.

## Si encuentras una vulnerabilidad en los sistemas del Poder Judicial

**No la reportes acá y no la publiques.**

Este proyecto consulta una plataforma de un tercero. Si al usarlo detectas una debilidad en
la Oficina Judicial Virtual, el camino correcto es la divulgación responsable directa a la
**Corporación Administrativa del Poder Judicial**, no un issue en este repositorio ni una
publicación.

Esa regla se aplicó durante el desarrollo: hay hallazgos sobre el comportamiento de la
plataforma que quedaron deliberadamente fuera de este repositorio por esta razón.

Publicar una debilidad de la OJV expondría a todo el sistema judicial y, de paso, arriesgaría
el acceso legítimo de quienes tienen plazos corriendo.

## Qué hace este software con tus datos

- **No persiste nada.** Consulta y devuelve. No hay base de datos ni caché en disco.
- **No pide credenciales.** Sólo consulta información pública; no usa Clave Única.
- **No envía datos a terceros.** La única conexión saliente es a
  `oficinajudicialvirtual.pjud.cl`.
- **Bitácora en memoria**: registra timestamp, URL y código de estado de cada petición, para
  poder acreditar uso razonable. Se pierde al terminar el proceso.

El `User-Agent` incluye el correo de contacto que configures en `MCP_PJUD_CONTACTO`. Es
deliberado: el Poder Judicial debe poder identificar y contactar a quien consulta. Si eso te
incomoda, esta herramienta no es para ti.

## Dependencias

Cuatro en producción: `mcp`, `httpx`, `lxml`, `pydantic`. Dependabot vigila actualizaciones
de seguridad semanalmente.
