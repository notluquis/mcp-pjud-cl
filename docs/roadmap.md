# Hoja de ruta y estado de verificación

## Qué está verificado y qué no

Esta tabla es lo más importante de la página. Distingue tres cosas que suelen confundirse:
lo que se probó **contra el sistema real**, lo que sólo se probó **contra fixtures**, y lo que
está **mapeado en el código de la plataforma pero nunca ejecutado**.

### Verificado contra el sistema real

| Qué | Cómo se verificó |
|---|---|
| Entrada pública sin Clave Única | `sesion-consultaunificada.php` → 200 |
| Derivación de prefijo de rutas y token | Tres sesiones distintas, token distinto en cada una |
| Búsqueda por RIT en civil | E-468-2026 y C-1156-2026 |
| Detalle de causa | Ambas causas |
| Cuadernos múltiples | C-1156-2026: principal + apremio |
| Actuaciones de receptor con fecha doble | 8 actuaciones en E-468-2026, 6 en C-1156-2026 |
| Los cuatro tipos de diligencia documentados | Presentes en E-468-2026 |
| Georreferencia presente | Todas las actuaciones de ambas causas |
| El filtro de la plataforma es por User-Agent y no por huella TLS | Tres clientes, mismo handshake, distinto header |

### Verificado sólo contra fixtures

Funciona sobre HTML real guardado, pero **nunca se ejercitó contra el sistema en vivo**:

| Qué | Riesgo |
|---|---|
| Discrepancia entre las dos fuentes de fecha | Nunca se vio un caso real de discrepancia. La rama existe y está testeada con HTML sintético, pero no hay evidencia de cómo se ve en la práctica |
| Georreferencia ausente | Todas las actuaciones observadas la traen. No se sabe cómo se ve la celda cuando falta |
| Fecha imposible (31/02) | Defensa preventiva, nunca observada |
| Mensaje de "sin resultados" | Se copió de una respuesta real, pero el camino completo no se ejercitó |

### Mapeado pero nunca ejecutado

Las rutas se extrajeron del código de la plataforma. **No se probó ninguna.** El cliente las
rechaza en vez de adivinar sus parámetros:

- `consultaNombre*.php`, `consultaJuridica*.php`, `consultaFecha*.php` para todas las
  competencias
- Todo lo de `apelaciones`, `suprema`, `laboral`, `penal`, `cobranza`, `familia`
- `detalleExhortos.php`, `causaOrigenCivil.php`, `geoReferenciaCivil.php`
- `anexoCausaCivil.php` y la descarga de documentos por `docuN.php`
- `receptorCivil.php`, que devuelve la tabla de **retiro** de documentos, no la de
  actuaciones. Se ejecutó una vez y se descartó por no ser lo que se buscaba

### Sin cubrir del todo

- **Paginación.** Se procesa el primer resultado de la búsqueda. Una búsqueda con varias
  causas devuelve sólo una.
- **Causas reservadas.** No aparecen y no aparecerán.
- **Expiración de referencias.** Caducan a los 30 minutos. El flujo cabe holgado, pero no hay
  manejo explícito de expiración a mitad de cadena.

## Versionado

[SemVer](https://semver.org/lang/es/). La versión mayor es `0`, y eso significa que **la API
pública puede cambiar sin aviso entre versiones menores**.

Hay una razón adicional para no apurar el `1.0.0`: este software depende del HTML de un
tercero que puede cambiar cualquier día. Prometer estabilidad de interfaz sería prometer algo
que no controlamos.

### Condiciones para llegar a 1.0.0

Las tres, no dos de tres:

1. **Más de una competencia verificada** contra el sistema real, con fixtures propias.
2. **Esquema de salida estable**, sin cambios de campos por al menos dos versiones menores.
3. **Seis meses sin que un cambio de la plataforma rompa el parser**, o con al menos un cambio
   detectado y corregido dentro de la semana.

## Hoja de ruta

### 0.2: paginación y varias causas

El caso "busco por nombre y salen doce causas" hoy no funciona. Se procesa la primera.

- Parsear los controles de paginación
- Devolver todas las causas del listado
- Decidir qué hacer cuando una búsqueda devuelve muchas: ¿traer actuaciones de todas, con lo
  que eso implica en tiempo bajo el intervalo de 5 segundos?
- Herramienta `buscar_causa_por_nombre`, que es la que un abogado realmente usa cuando no
  recuerda el rol

**Riesgo conocido:** doce causas × 5 peticiones × 5 segundos = cinco minutos. Puede que la
respuesta correcta sea devolver el listado y que el usuario elija, en vez de encadenar todo.

### 0.3: cobranza laboral y previsional

La primera competencia nueva, y la elegida a propósito: `receptorCobranza.php` existe, o sea
que también tiene actuaciones de ministro de fe, que es donde está el valor.

- Fixture de una causa real (`C-208-2019` del Juzgado de Cobranza de Concepción es candidata)
- Verificar si el formato de fecha doble es el mismo
- Parser propio si difiere
- Ampliar `MODULOS` sólo después de verificar, nunca antes

### 0.4: exhortos y documentos

- `detalleExhortos.php`: seguimiento de exhorto de origen a destino
- `causaOrigenCivil.php`
- Descarga de documentos por folio vía `docuN.php`

**Decisión pendiente y no trivial:** descargar un PDF significa traer datos de terceros a
disco. Eso cambia el perfil de retención y entra de lleno en la Ley 21.719. Probablemente
requiera consentimiento explícito por llamada, y ruta de destino elegida por el usuario.

### 0.5: laboral y apelaciones

Las dos competencias que siguen en volumen de uso real.

### Sin versión asignada

**Detección de cambios entre consultas.** Avisar cuando aparece una actuación nueva. Sigue
siendo solo lectura, pero **implica persistencia**, y eso cambia todo el perfil de datos
personales. No se toca hasta que las fases anteriores estén estables y haya una respuesta
clara sobre retención bajo la Ley 21.719.

**Búsqueda de cartera por identificador de abogado.** El campo `Institución` de los listados
permite reconstruir la cartera completa de un abogado. Técnicamente es directo.
**Deliberadamente en duda**: construir perfiles de personas está en la lista de usos que el
proyecto rechaza, aunque el dato sea público. Si se implementa, será con un caso de uso
justificado y no "porque se puede".

**Jurisprudencia.** Descartada de forma permanente por el bloqueo nominal de `juris.pjud.cl`.
Sólo reviviría por Ley 20.285 o fuente licenciada.

## Lo que se va a romper

No es pesimismo, es planificación:

- **La plataforma va a cambiar.** El prefijo de rutas y el token ya se derivan en caliente por
  esto. Cuando cambie la estructura de tablas, el parser falla ruidosamente y hay que
  arreglarlo.
- **Pueden activar la validación del captcha.** Hoy la consulta funciona sin ella. Si se
  activa, la cadena se cae entera y no se va a evadir: el proyecto se detiene y se busca la
  vía institucional.
- **Puede publicarse la Política de IA del Poder Judicial.** Si define algo incompatible, este
  proyecto se ajusta o se retira.

## Cómo influir en esto

La hoja de ruta la mueve el uso real, no la lista de deseos del autor. Lo más útil:

- Reportar un **dato incorrecto** (máxima prioridad de todas)
- Reportar que **la plataforma cambió**
- Pedir una **competencia** con una causa pública que sirva de fixture
- Contar en Discusiones **qué te falta** para poder usarlo

## Hallazgos de OpenSSF Scorecard que siguen abiertos

Se dejan anotados con su razón, para no re-discutirlos cada vez que aparecen.

| Hallazgo | Estado | Por qué |
|---|---|---|
| `Maintained` | Se resuelve solo | Mide actividad sostenida en 90 días. El repositorio es nuevo |
| `Code-Review` | Se resuelve al usar pull requests | Mide cambios revisados. Hasta ahora los commits fueron directos a `main` |
| `SAST` | Punto ciego de Scorecard | CodeQL **sí** está activo, en el modo gestionado por GitHub. Scorecard busca `codeql-action` en los workflows o la aplicación de escaneo en pull requests fusionados, y el modo gestionado no deja ninguna de las dos huellas |
| `Fuzzing` | No se va a implementar | Busca OSS-Fuzz o ClusterFuzzLite. Acá el equivalente útil son las pruebas basadas en propiedades con Hypothesis, que Scorecard no reconoce. Para un parser de 500 líneas en un lenguaje con memoria gestionada, montar infraestructura de fuzzing no compensa |
| `CII-Best-Practices` | Pendiente, requiere inscripción | La insignia se obtiene llenando un formulario en bestpractices.dev. Es gratis y manual |

Sobre `Code-Review`: en un proyecto de una persona no tiene arreglo técnico, pero para código
que decide plazos procesales vale preguntarse si conviene un segundo par de ojos antes de
tocar el parser. Queda dicho como pregunta abierta y no como casilla marcada.
