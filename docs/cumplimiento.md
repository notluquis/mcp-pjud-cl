# Cumplimiento

Esta página existe porque el contexto regulatorio de esta herramienta cambió hace pocas
semanas y define varias decisiones de diseño. Todo lo que sigue está verificado contra fuente,
con la fecha de verificación indicada.

## El antecedente de julio de 2026

Entre el 25 y el 28 de julio de 2026, un abogado ingresó **38.477 escritos automatizados** a
tribunales civiles de todo el país mediante un agente externo, y la Oficina Judicial Virtual
colapsó. Los escritos correspondían mayoritariamente a desarchivos y renuncias de patrocinio y
poder.

Consecuencias, según la prensa nacional:

- La dirección **IP fue bloqueada** y se adoptaron medidas informáticas de emergencia.
- El Comité de Jueces Civiles de Santiago solicitó a la Corte Suprema **mantener restringido
  el acceso** del abogado a la plataforma.
- Se pidió un informe para evaluar **responsabilidades disciplinarias y penales**.
- Se propuso implementar **CAPTCHA** para impedir nuevos ingresos automatizados masivos.
- Se planteó **prohibir el uso de inteligencia artificial** para el ingreso de escritos.

Fuentes: [El Mostrador](https://www.elmostrador.cl/noticias/sin-editar/2026/07/28/el-dia-que-un-abogado-saturo-la-plataforma-del-poder-judicial-con-38-mil-escritos/),
[BioBioChile](https://www.biobiochile.cl/noticias/nacional/chile/2026/07/28/abogado-saturo-sistema-con-37-mil-escritos-en-horas-y-ahora-jueces-quieren-vetar-la-ia-en-tribunales.shtml),
[T13](https://www.t13.cl/amp/noticia/nacional/solicitan-prohibir-uso-ia-para-ingreso-escritos-plataforma-del-poder-judicial-28-7-2026).

### Qué se deduce de eso para este proyecto

La distinción entre **leer** e **ingresar** es la línea que separa esta herramienta de lo que
colapsó la plataforma. Por eso está declarada en el título, en la descripción del repositorio
y en la primera línea del README, no en la letra chica.

Tres decisiones bajan directamente de este antecedente:

1. **No existe código de escritura**, ni desactivado ni tras una bandera. Hay un job de CI que
   lo verifica mecánicamente en cada cambio.
2. **El intervalo mínimo no es configurable hacia abajo.** El daño de julio fue de volumen.
3. **Ante bloqueo, detención total.** No se evade, porque quien pagaría el costo de una
   escalada es el usuario que tiene plazos corriendo.

## Condiciones de uso de la plataforma

El Acta 37-2016 de la Corte Suprema, artículo 3, obliga a aceptar los términos y condiciones
de la Oficina Judicial Virtual para usarla.

Leídas en `oficinajudicialvirtual.pjud.cl/home/condicionesdeuso.php` el 16 de agosto de 2026:

**No contienen ninguna cláusula** sobre automatización, robots, scraping, extracción masiva,
minería de datos ni acceso programático.

La cláusula operativa es la **CUARTA**:

> Los usuarios no deben utilizar el servicio de formas que "dañar, inutilizar, **sobrecargar**,
> deteriorar el Portal o impedir su normal utilización".

Lo que el contrato prohíbe es la **sobrecarga**. De ahí que el intervalo de 5 segundos sea el
control jurídicamente cargante del proyecto y no una cortesía: es esa cláusula implementada en
código.

## robots.txt

Verificado el 16 de agosto de 2026:

| Host | Contenido |
|---|---|
| `oficinajudicialvirtual.pjud.cl/robots.txt` | `User-agent: *` → `Disallow: /` |
| `juris.pjud.cl/robots.txt` | `Disallow: /` para todos, **más bloqueo nominal de `Anthropic-ai` y `Claude-Web`** |
| `www.pjud.cl/robots.txt` | 404, no publica |

Esto se dice completo y sin adornos porque es información que quien evalúe usar la herramienta
merece tener.

Consecuencias asumidas:

- **La jurisprudencia (`juris.pjud.cl`) quedó fuera de alcance de forma permanente.** Ese host
  rechaza nominalmente a los agentes de esta clase. La vía correcta para jurisprudencia son
  las solicitudes por Ley 20.285 de Transparencia o una fuente licenciada.
- La consulta de causas se hace por el enlace que **la propia institución publica en la
  portada de `www.pjud.cl`** como acceso público, en un host que no publica robots.txt.

## Ley 21.719 sobre protección de datos personales

Publicada el **13 de diciembre de 2024**. Entra en vigencia el **1 de diciembre de 2026**.

Crea la Agencia de Protección de Datos Personales, con potestad para investigar de oficio,
sancionar, ordenar la suspensión de tratamientos y publicar un Registro Nacional de Sanciones.
Multas de hasta **20.000 UTM**, o **4% de los ingresos anuales** en caso de reincidencia.

### Por qué te afecta

Los datos que devuelve esta herramienta —nombres, RUT, roles, actuaciones— son **datos
personales de terceros**. Que provengan de una fuente pública no los saca del ámbito de la ley.

**El software no persiste nada**: consulta y devuelve. Esa decisión es de diseño y es la razón
por la que el uso base no genera obligaciones de tratamiento.

**Si tú decides almacenar los resultados**, el responsable del tratamiento pasas a ser tú, con
todo lo que implica:

- Base de licitud para el tratamiento
- Principio de finalidad y de minimización
- Plazos de conservación definidos
- Derechos ARCO del titular (acceso, rectificación, cancelación, oposición)
- Notificación de brechas dentro de **72 horas**

Faltan menos de cuatro meses para que rija. Si vas a guardar datos, asesórate antes.

## Alineación con el Poder Judicial

El Tribunal Pleno de la Corte Suprema aprobó el **Plan Estratégico 2026-2030** mediante
**Acta N.° 151-2026**. La definición de una **Política Institucional de Inteligencia
Artificial** es una de las iniciativas priorizadas para 2026.

**Esa política todavía no se publica.** Cuando se publique, este proyecto se revisará contra
ella, y si algo queda fuera de lo que la institución defina, se ajusta o se retira. Esa
posición está escrita acá de antemano a propósito, para que no sea una decisión que se tome
bajo presión.

Mientras tanto, los criterios que se aplican son los que se pueden verificar hoy: las
condiciones de uso, el antecedente de julio, y la lógica de no hacer nada que la institución
haya señalado que no quiere.

### Vía institucional

El camino correcto para convertir esto en algo formalmente respaldado es solicitar acceso
sancionado a la **Corporación Administrativa del Poder Judicial**. Una herramienta de solo
lectura, identificada, con límite de ritmo y sin capacidad de escritura es plausiblemente el
tipo de cosa que una política de IA institucional podría contemplar.

## Marca

Sin logos institucionales. Sin la tipografía ni los colores del Poder Judicial. Sin usar
"Poder Judicial" en el nombre del paquete. La salida de esta herramienta no debe presentarse
como información oficial.

## Divulgación responsable

Si al usar esto detectas una debilidad en la plataforma del Poder Judicial, **no la publiques
ni la reportes en este repositorio**. Va directo a la Corporación Administrativa.

Esa regla se aplicó durante el desarrollo: hay hallazgos sobre el comportamiento de la
plataforma que quedaron deliberadamente fuera de este repositorio por esta razón.

## Resumen de controles

| Control | Dónde vive | Verificado por |
|---|---|---|
| Sin código de escritura | Todo el proyecto | Job de CI que busca endpoints de ingreso |
| Intervalo mínimo 5 s | `client.py` | Test unitario + job de CI |
| Detención ante 403/429 | `client.py` | Test unitario, sin reintento |
| Fallo ruidoso | `parser.py` | Tres tests de estructura |
| User agent identificable | `client.py` | Obligatorio por variable de entorno |
| Sin persistencia | Todo el proyecto | No hay dependencia de base de datos |
| Bitácora de peticiones | `client.py` | Test unitario |
