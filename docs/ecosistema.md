---
myst:
  html_meta:
    description: "Qué cubren las otras herramientas que consultan el Poder Judicial de Chile, qué se tomó de cada una y qué se dejó fuera a propósito."
---

# Qué más existe

Revisado el 17 de agosto de 2026. Se anota para no re-descubrirlo, y porque si algo de esto
cubre tu caso mejor, conviene que lo uses en vez de esto.

Este proyecto no es el primero que consulta al Poder Judicial de Chile por programa, y decirlo
importa: parte de lo que hay cubre bastante más superficie. Lo que sigue es lo medido, no una
comparación de folleto.

## Servidores MCP jurídicos

| Proyecto | Jurisdicción |
|---|---|
| [`mcp-legal-ar`](https://github.com/Probanza-ar/mcp-legal-ar) | Argentina. 14 conectores, 203 herramientas, jurisprudencia de la Corte Suprema desde 1863 |
| [`brlaw_mcp_server`](https://glama.ai/mcp/servers/pdmtt/brlaw_mcp_server) | Brasil |
| Entscheidsuche | Suiza |
| Varios | España (CENDOJ) y Colombia |
| [`mcp-dev-latam`](https://github.com/codespar/mcp-dev-latam) | Incluye Chile, pero para comercio y no para tribunales |

**Para Chile no hay ninguno.** Argentina es el ecosistema más maduro de la región y sirve de
referencia de hacia dónde puede ir esto.

## Herramientas chilenas que tocan lo mismo

Revisadas a fondo el 17 de agosto de 2026, más Magnar el 21: las de código abierto leyendo su
código, las comerciales leyendo lo que documentan. Se anota con detalle porque marcan el piso:
lo que ellas ya hacen no es una idea para el roadmap, es lo mínimo.

De las comerciales sólo se puede afirmar lo que publican. Ninguna se contrató ni se probó, así
que cuando acá diga "no cubre X" hay que leerlo como **no lo publica**, que no es lo mismo.

### CausAlerta

Es el competidor real, y cubre mucho más superficie que esto. SaaS de gestión completa, con
seguimiento diario y resumen por correo.

| | |
|---|---|
| Precio | Gratis hasta 3 causas; 6.500, 10.400 y 31.200 pesos más IVA al mes |
| Competencias | Civil, cobranza, laboral, familia, libre competencia, constitucional, apelaciones y suprema |
| Qué sigue | "Historia, escritos por resolver, **movimientos de receptor** y estado procesal" |
| Además | Banco de jurisprudencia, programación semanal de salas en Cortes de Apelaciones, calendario de plazos y audiencias, importación masiva desde la Oficina Judicial Virtual o Excel, documentos y plantillas, cobros por cliente, registro de horas, equipos |

Conviene subrayar la tercera fila: **sí dice cubrir los movimientos de receptor**. Lo que no
dice, y no se puede saber desde afuera, es si separa la fecha de diligencia de la de registro
o si presenta una sola. Afirmar que no lo hace sería inventar.

### Magnar

Revisado el 21 de agosto de 2026 sobre lo que publica, sin contratarlo. Es chileno, de 2025, y
ya opera en Perú, Ecuador, Costa Rica, Colombia y Uruguay.

**La jurisprudencia se solapa; el resto no.** Este proyecto también busca fallos y entrega su
texto, con `buscar_jurisprudencia` y `obtener_texto_sentencia`, así que decir que Magnar cubre
"la otra mitad" sería falso y le serviría mal a quien esté comparando. La diferencia real:

| | Magnar | Acá |
|---|---|---|
| Jurisprudencia | **sí**, con banco propio | **sí**, contra el buscador oficial |
| Normativa | sí | no |
| Análisis de expedientes y redacción | sí | no, y por decisión de alcance, no por la regla 1 |
| Estado de una causa y fecha que corre el plazo | no lo publica | **sí**, y es la razón de existir |

| | |
|---|---|
| Qué declara buscar | "normativa y jurisprudencia oficial de tu país, con citas verificables y acceso directo a cada fuente" |
| Base propia | Un banco de fallos en `app.magnar.ai/cl/juris` |
| Qué genera | Resúmenes de sentencias, tablas comparativas, ediciones con control de cambios en Word |
| Escala que declara | Expedientes de hasta 10.000 páginas |
| Certificaciones que declara | ISO 27001 obtenida, SOC 2 Type 2 obtenida, RGPD cumple; ISO 42001 en curso |
| Qué NO publica | Ninguna mención de la Oficina Judicial Virtual, de consulta de causas ni de cómputo de plazos |

Sobre el solapamiento en jurisprudencia hay una diferencia que sí se puede sostener sin
contratar nada: acá la fuente es el buscador oficial y la respuesta declara qué NO trae, con
`ocultas` y `no_entregadas`. Un banco propio puede estar más completo o menos, y desde afuera
no hay cómo saberlo.

Dos cosas que sí sirven acá:

**La cifra de las 10.000 páginas.** Es publicidad y no una medición, pero pone un orden de
magnitud a lo que un producto de este rubro dice manejar, y el problema de entregar un
expediente sin gastar el contexto está abierto en esta hoja. No se toma como dato: se anota
como el número que alguien más se atreve a decir en público.

**Que el énfasis esté en la cita verificable.** Es la misma decisión que acá lleva a que cada
sentencia traiga su `url` y a que el texto declare `anonimizada` y `fuente`. Que un producto
comercial lo ponga primero en su portada confirma que no es una manía del proyecto.

Y lo que no se toma: la redacción de escritos. **No porque la regla 1 lo prohíba**, y la
distinción importa porque esa regla no se negocia y estirarla la desgasta: lo que prohíbe es
que este servidor escriba en los sistemas del Poder Judicial o invoque endpoints de ingreso.
Un borrador que se queda en la máquina de quien lo pidió no hace ninguna de las dos cosas.

Queda fuera por alcance, que es una decisión y no un límite: esto es un servidor de consulta,
redactar exige entender el caso y no sólo leerlo, y quien redacte con ayuda de un modelo puede
hacerlo con el resultado de estas herramientas al lado. Lo que la regla 1 sí cierra es el paso
siguiente, presentar el escrito, y ése no se va a abrir.

### API de Boostr

Otro producto, no un competidor directo: resuelve "¿esta persona tiene causas en alguna parte
del país?", no "¿qué pasó en esta causa?".

| | |
|---|---|
| Precio | 2.000 pesos **por consulta**, mínimo 10.000 (cinco consultas) |
| Modelo | Asincrónico con `operation_id` y notificación por URL, porque barre todos los tribunales |
| Busca por | RUT en civil, nombre completo en penal |
| Cubre | Penal, civil y apelaciones. Excluye familia y causas reservadas |
| Advertencia propia | "No nos hacemos responsable de la información entregada, todo proviene directamente desde el Poder Judicial" |

Su documentación no describe los campos de cada causa, así que no hay evidencia de que llegue
al detalle ni a las actuaciones.

### `automatizador-legal`

Ataca un dato que este proyecto no cubre: la **Programación de Sala**, o sea cuándo se ve una
causa. Sin licencia, o sea sin derecho de uso.

Su arquitectura es el contraejemplo de la nuestra, y su README lo dice sin rodeos: Playwright
corre dentro de Docker pero controla un Brave real en el Mac por CDP, "para evitar bloqueos"
y para que una persona pueda resolver el captcha a mano. Entrada por Excel en Google Drive,
salida por correo, orquestado con n8n.

Los campos del formulario quedan mapeados de paso: `progComp`, `progCorte`, `progRolCausa`,
`progEraCausa`, `progTipoCausa`, botón `btnProgConsulta`, tabla `dtaTableDetalleProgSala`.

### `webscrapthings`

Los bots de ParalegApp. Selenium con la API de la versión 3 (ya retirada), persistencia en
Django, sin licencia y sin mantención desde 2025. Un directorio `botsClave` indica que opera
con Clave Única, o sea del lado autenticado.

Es el que más pestañas cubre, y ahí está lo aprovechable:

| Pestaña, con el selector que usa **su** código | Equivalente acá |
|---|---|
| `#Historia` | `historiaCiv`, cubierto |
| Selector de cuadernos | cubierto |
| `#Litigantes` | `litigantesCiv`, cubierto |
| `#Notificaciones` | `notificacionesCiv`, cubierto |
| `#Escritos` | `escritosCiv`, **no** |
| `#Exhorto` | `exhortosCiv`, **no** |
| `#Diligencias` en laboral, con descarga de PDF | sin equivalente, **no** |

Los identificadores de la izquierda son los suyos y no calzan con los nuestros: operan sobre la
vista autenticada con Clave Única, que tiene otro marcado. Los de la derecha son los que trae
la consulta pública, verificados contra la respuesta real.

Y un dato que acota la comparación: la palabra "receptor" no aparece ni una vez en sus 400 KB
de scrapers. Cubre más pestañas, pero no la que a este proyecto le da sentido.

Una comprobación que se intentó y **no** sirvió: buscar en el código de GitHub los nombres de
los endpoints de la plataforma. La consulta de control (`oficinajudicialvirtual.pjud.cl`)
devolvió cero, o sea el buscador no indexa bien cadenas con puntos, y los ceros de las demás
consultas no significaban nada. Queda anotado para que nadie lo repita creyendo que mide algo.

## Qué se toma de cada una

Lo honesto primero: **en superficie estamos muy atrás.** Una competencia contra ocho, sin
seguimiento, sin alertas, sin documentos, sin calendario. Eso no se disimula, se anota.

Lo que sí se puede sostener, y hay que sostenerlo con evidencia y no con adjetivos:

| Dónde ser mejores | Por qué es sostenible |
|---|---|
| Las dos fechas como campos distintos y tipados | Nadie documenta esa separación. La salida es un esquema, no una pantalla: quien la consume no puede confundirlas |
| Declarar lo que falta | `ocultas` en jurisprudencia y `ResultadosTruncados` en listados. Ninguna otra declara completitud, y la plataforma dejó de hacerlo |
| Fallar ruidoso | Un servicio de alertas diarias que deja de parsear manda un resumen vacío que se lee como "no pasó nada". Acá eso levanta excepción |
| Ser auditable | Código a la vista, bitácora de cada petición, y el intervalo verificado por CI. Un SaaS cerrado no permite comprobar ninguna de las tres |
| No guardar nada de terceros | Sin cuenta, sin base de datos, sin retención bajo la Ley 21.719 |
| Hablar MCP | Ninguna de las cinco lo hace. La herramienta llega adentro del asistente que el abogado ya usa, no a otra pestaña más |

Y lo que hay que copiar sin orgullo, en este orden, porque marca el piso de lo que un abogado
espera:

1. **Litigantes, escritos y exhortos** del detalle de causa. `webscrapthings` los cubre desde
   2025 y son una pestaña más de la misma respuesta que ya se pide.
2. **Programación de Sala**, el "¿cuándo me ven?". Ojo: los campos que se listaban acá se
   midieron y no existen, así que esto no es copiar, es investigar de nuevo.
3. **Más competencias.** Ocho contra una es la brecha más grande, y cobranza sigue siendo la
   primera por tener actuaciones de ministro de fe.
4. **Detección de cambios**, que ya está más abajo sin versión asignada. Es lo que vende
   CausAlerta y lo que exige resolver antes la pregunta de retención de datos.

## Lo que falta, medido

No es una lista de deseos: cada línea sale de leer la respuesta real, la fixture o el código
del que ya lo hace. Se anota con los nombres exactos para que implementarlo no cueste
re-descubrirlos.

### Los paneles del detalle que ya llegan y se tiran

El detalle de causa devuelve **una sola respuesta** que trae todos estos paneles. Cubrirlos no
cuesta ni una petición más, y por eso fueron lo primero. Quedan los escritos.

Conviene no confundirlos con los modales de la sección siguiente: aquéllos **sí** cuestan una
petición cada uno, con su intervalo. Lo gratis es sólo lo de esta tabla.

| Panel | Columnas exactas |
|---|---|
| `litigantesCiv` | `Participante`, `Rut`, `Persona`, `Nombre o Razón Social`. **Cubierto** |
| `escritosCiv` | `Doc.`, `Anexo`, `Fecha de Ingreso`, `Tipo Escrito`, `Solicitante` |
| `notificacionesCiv` | `ROL`, `Est. Notif.`, `Tipo Notif.`, `Fecha Trámite`, `Tipo Part.`, `Nombre`, `Trámite`, `Obs. Fallida`. **Cubierto** |
| `exhortosCiv` | `Rol Origen`, `Tipo Exhorto`, `Rol Destino`, `Fecha Ordena Exhorto`, `Fecha Ingreso Exhorto`, `Tribunal Destino`, `Estado Exhorto`. **Cubierto** |
| `piezasExhortoCiv` | `Folio`, `Doc.`, `Cuaderno`, `Anexo`, `Etapa`, `Támite`, `Desc. Támite`, `Fec. Támite`, `Foja`. **Cubierto** |

Tres advertencias que sólo se ven mirando la respuesta:

- **`piezasExhortoCiv` trae los encabezados con errata**: dice `Támite` y `Fec. Támite`, sin la
  erre. Un parser que busque `Trámite` no encuentra nada y devuelve vacío. El mapeo calza con
  el texto que la plataforma emite, no con el correcto, y si algún día la corrigen levanta.
- **`notificacionesCiv` tiene su propia `Fecha Trámite`, y no se comporta como la de la
  historia.** La inferencia por el nombre de las columnas (`Est. Notif.`, `Obs. Fallida`) era
  que respondía "¿la notificación resultó?", la pregunta anterior a "¿cuándo corre el plazo?",
  y midiéndola resultó ser eso: tres filas reales, ninguna con el formato de fecha doble. La
  advertencia que queda es otra: **incluye las NO practicadas**, que se distinguen por
  `estado`, y una fila pendiente no hizo correr ningún plazo.
- **`litigantesCiv` trae RUT de personas naturales.** Es el panel con más carga de datos
  personales de todo el detalle, y su fixture tendrá que anonimizarse como el resto.

Estado de la evidencia: los dos del exhorto están verificados con datos reales. C-1156-2026
despacha E-875-2026 al 1º Juzgado Civil de Chillán, estado `Generado`, y E-468-2026 trae las
seis piezas que su tribunal de origen despachó. De `escritosCiv` se conoce la estructura, pero
**las causas de la muestra lo traen vacío**: no hay fila real que sirva de fixture todavía.

### Modales de la Oficina Judicial Virtual sin usar

Extraídos de `consultaUnificada.php`, ninguno ejecutado:

| Ruta | Qué daría |
|---|---|
| `modal/detalleExhortos.php` | El exhorto visto desde el tribunal exhortado |
| `modal/causaOrigenCivil.php` | La causa de origen cuando ésta viene de otra |
| `modal/geoReferenciaCivil.php` | Las coordenadas de la actuación, no sólo si existen |
| `modal/anexoCausaCivil.php` | Documentos adjuntos de la causa |
| `modal/anexoCausaSolicitudCivil.php` y `anexoCausaSolEscritoCivil.php` | Adjuntos de solicitudes y escritos |
| `modal/anexoCausaSolicitudCivilSII.php` | Adjuntos de solicitudes del Servicio de Impuestos Internos |

### Programación de Sala

**Este mapeo se midió y no existe.** Salía de leer `automatizador-legal`, y el 20 de agosto de
2026 se comprobó que ninguno de sus siete campos aparece: ni en `consultaUnificada.php` ni en
la página real. Se conserva acá porque describe lo que ese proyecto hace, que es de lo que
trata esta página, y no lo que la plataforma ofrece hoy.

Lo que sí existe, medido, está en la {doc}`hoja de ruta <roadmap>`: otro host, sin el
cortafuegos compartido, y un monitor por sala que no recibe rol.

### Jurisprudencia: lo que queda del buscador

| Ruta | Parámetros medidos | Qué daría |
|---|---|---|
| `/busqueda/buscar_sentencias` con `id_sentencia` | `_token`, `id_sentencia` | El detalle completo de una sentencia, con su texto |
| `/busqueda/webservices` con `cod_ws=6` | `datos` (la sentencia), `numero_pestanna` 2 o 3 | Las instancias anteriores. Una sentencia de Suprema arrastra la de Apelaciones y la del tribunal de origen |
| `/busqueda/webservices` con `cod_ws=1` | `url_webservice` a `leychile.cl/Consulta/obtxml` | Las normas citadas, resueltas contra LeyChile |
| `/busqueda/listar_ids_relacionados` | `rol_era` | Sentencias relacionadas |
| `/busqueda/arbol_json` | `filtros`, `id_buscador` | Índice temático de materias y submaterias |
| `/busqueda/documentos` e `/busqueda/imprimir` | por medir | El documento y su versión imprimible |
| `/detalle_sentencia/terminos_juridicos` | por medir | Glosario, que el sitio usa para marcar términos en el texto |

Lo de `numero_pestanna` es lo más valioso y no se ve desde la interfaz: **la cadena procesal
completa de una causa cabe en una consulta**. `parametros_buscador` lo confirma con
`ws_2_visible` y `ws_3_visible`, etiquetados "Corte Apelaciones" y "Tribunales".

### Detección de cambios: el diseño que ya existe

`webscrapthings` resuelve esto con un resumen diario, y su plantilla vale como punto de
partida porque marca **qué dimensión cambió**, no sólo que algo cambió:

| Causa | Caratulado | Inicio | Actualización | Estado | Etapa | Cuaderno | Historia | Litigante | Notificación | Escrito | Exhorto |
|---|---|---|---|---|---|---|---|---|---|---|---|

Las últimas ocho columnas son una X. Dos cosas se pueden hacer mejor, y las dos se ven en su
código: marca la dimensión pero no **qué** cambió dentro, y decide esas X buscando la palabra
dentro de un comentario en texto libre (`'Estado' in caso.caso.last_chenge_coment`), que falla
en silencio si el texto cambia. Acá lo que corresponde informar no es "cambió la Historia":
es qué folio apareció, y si trae una fecha de diligencia que echó a correr un plazo.

Sigue vigente lo que bloquea esto: implica persistir datos de terceros, o sea entra de lleno
en la Ley 21.719.

### Las diligencias de cobranza no publican fecha

Medido sobre filas reales, y cierra la pregunta que la sección de abajo dejaba abierta.
`diligenciaCob` sí trae diligencias, y son las que importan:

```
cumplida | Embargo en cuenta corriente | 31/12/1969 | No Asignado | MONICA ...
cumplida | Alzamiento embargo en cta cte | 31/12/1969 | No Asignado | MONICA ...
```

**`31/12/1969` es el epoch de Unix** visto desde una zona al oeste de Greenwich: el valor cero
impreso como fecha. O sea la columna está vacía. Tres diligencias de una causa real, las tres
con el mismo cero.

Consecuencia para el proyecto: en cobranza hay diligencias de embargo, con su estado y con un
responsable identificado, **y sin fecha de diligencia publicada**. Que es justamente el dato por
el que existe este proyecto. Cobranza queda buscable y con detalle, y no puede entregar lo que
civil sí entrega, por una razón de la plataforma y no del cliente.

Y de paso apareció una trampa que ahora tiene guardia: devolver `1969-12-31` como fecha real
sería peor que devolver nulo, porque alguien computaría un plazo desde ahí. `_FECHAS_CENTINELA`
las descarta. Es el error del proyecto con el signo invertido: no falta un dato, sobra uno que
tiene forma de dato.

### Las diligencias de cobranza viven en su propio panel

Medido sobre una respuesta real, y corrige lo que esta misma hoja afirmó antes: en cobranza las
diligencias del ministro de fe viven en un panel propio.

Su tabla de Historia **sí nombra algunas**, y ésa es la trampa: tres filas dicen
`Actuacion - Receptor`, sin tilde y con guion, y **ninguna trae fecha de diligencia**. Leerlas
de ahí daría una lista de completitud **desconocida**: para saber si esas tres son todas
habría que compararlas contra `diligenciaCob`. Y ninguna trae el
dato que se busca. Además `TRAMITE_RECEPTOR` busca `actuación receptor`,
así que ni siquiera las reconocería: hoy eso no importa porque la competencia se rechaza antes,
y no se toca el marcador para no dejar una rama que no puede ejecutarse.

Están en `diligenciaCob`, que tiene estructura propia:

```
Doc. Ida | Doc. Vta. | Estado Diligencia | RIT | RUC | Tipo Diligencia | Fecha Trámite | Destinatario | Responsable
```

De las dos preguntas que quedaban abiertas se contestó **una**. `Fecha Trámite` **no** trae el
formato de fecha doble de civil: es una sola columna, y en la fila medida imprime el epoch, así
que se entrega en nulo.

Qué significa `Responsable` **sigue sin medirse**. Se entrega tal como lo imprime el sitio, y
no se afirma que identifique al receptor: eso era una conjetura y sigue siéndolo.

Y una advertencia que la estructura no dice sola: `RIT` y `RUC` son de la causa **a la que la
diligencia se dirige**, que no es necesariamente la consultada. Leerlos como los de esta causa
haría informar acá un trámite ajeno.

El panel ya se lee, y viaja en `diligencias` dentro del detalle de causa. Lo que
sigue rechazándose es pedir esas filas como **actuaciones**: sin fecha de diligencia no son lo
que `obtener_actuaciones_receptor` promete, y la Historia sólo produciría esas tres filas sin
fecha y sin saber si son todas. Es el mismo falso negativo que motivó el proyecto, y estuvo
brevemente dentro de él.

### El calendario de días hábiles: la pieza que falta para cerrar el círculo

Revisando el catálogo completo de Boostr apareció lo que este proyecto no tiene y necesita más
que ninguna otra cosa. Su API de feriados responde por fecha y distingue el tipo:

```json
{"status":"success","date":"2025-01-01","is_holiday":true,
 "data":{"title":"Año Nuevo","type":"Civil","inalienable":true,"extra":"Civil e Irrenunciable"}}
```

Por qué importa acá: hoy la herramienta entrega la **fecha de diligencia**, que es el punto de
partida del plazo. Lo que el abogado quiere saber es la fecha de término, y para eso hace falta
el calendario de días inhábiles. Sin él, el dato que este proyecto rescata queda a mitad de
camino.

Y por qué **no** basta con enchufar un calendario:

- El cómputo depende de la regla procesal aplicable, no sólo del almanaque, y esa regla varía
  según la materia y según el tipo de plazo. Decir cuál rige en cada caso es calificación
  jurídica, no aritmética.
- Equivocarse acá es peor que no responder. Entregar "el plazo vence el 12" con un día de
  error produce exactamente la pérdida que el proyecto existe para evitar, y con la confianza
  añadida de venir con forma de respuesta.

Esto último no es prudencia retórica: este documento describe software, y una afirmación sobre
cómo se cuenta un plazo la va a leer un abogado como la posición del proyecto. Acá no se
sostiene ninguna, a propósito.

De modo que la dirección probable no es "calcular el plazo" sino **entregar los insumos con la
misma honestidad que el resto**: la fecha de diligencia, los días inhábiles del período, y la
cuenta en días corridos y en hábiles, dejando la calificación jurídica a quien firma. La
decisión queda abierta y es de las que conviene discutir antes de escribir código.

Fuente del calendario: está por decidir. Boostr lo ofrece pero es un tercero de pago. Los
feriados chilenos están fijados por ley, o sea el dato es público y cabe en el paquete sin
depender de nadie. La norma base es la
[Ley 2.977](https://www.bcn.cl/leychile/navegar?idNorma=23530) de 1915, más las posteriores
que la modifican; verificado el 17 de agosto de 2026.

Ese "verificado" es lo único que se puede ofrecer acá, y conviene decir por qué: la suite no
consulta la red por diseño, así que **ninguna cita legal de esta documentación puede
comprobarse en CI**. Lo que sí se comprueba es que venga con enlace y con la fecha en que
alguien la miró, que es lo que permite a quien lea juzgar si sigue vigente. Vale para todas las
leyes que este proyecto cita, que están en una tabla única en la página de cumplimiento.

### Del mismo catálogo: qué más sirve y qué se rechaza

| Servicio de Boostr | Decisión |
|---|---|
| Feriados | **Sirve**, ver arriba |
| UTM y UF del día y por año | **Sirve.** Las cuantías y multas judiciales se expresan en esas unidades; hoy la salida las deja como texto |
| Generador de dígito verificador | **Sirve, y se hace acá.** La búsqueda por RUT de empresa lo exige, y calcularlo son cinco líneas: no amerita una dependencia ni una llamada |
| Propiedades y vehículos por RUT | **Se rechaza.** Es búsqueda de bienes embargables, y aunque calce con el cuaderno de apremio, convierte la herramienta en un buscador de patrimonio de personas |
| PEP, Interpol, defunción, AFP, AFC | **Se rechaza.** Es perfilamiento de personas, que ya está en la lista de usos que el proyecto no acepta |

Vale anotar por qué se escriben también los rechazos: son las funciones que alguien va a pedir
tarde o temprano, y tener la respuesta escrita evita discutirla de nuevo cada vez.

### Competencias

Ocho contra una es la brecha más grande. Cobranza sigue primera por tener actuaciones de
ministro de fe; de ella ya se sondeó que el panel es `historiaCob`, que agrega una columna
`Estado Firma`, que no trae `Foja`, y que existe un panel `diligenciaCob`.

## El diseño de su documentación, y qué se copió

La documentación de Boostr está hecha con [readme.com](https://readme.com/), que es una
plataforma de pago especializada en referencias de API. Sus piezas, leídas del propio HTML:

| Pieza | Qué hace |
|---|---|
| `rm-Sidebar` con 98 enlaces en 18 grupos plegables | Navegación por secciones, con el método HTTP como insignia |
| `Playground` | Panel para probar la llamada desde la página |
| `LanguagePicker` y `CodeTabs` | El mismo ejemplo en Shell, Node, Python, Ruby y PHP |
| `APIResponseSchemaPicker` | Elegir el esquema de respuesta por código de estado |
| `Param` con nombre, tipo y descripción | Los parámetros como bloques, no como tabla |
| `ThemeToggle` | Modo claro y oscuro |

Lo que se adoptó, traducido a lo que este proyecto es:

- **Pestañas por cliente en vez de por lenguaje.** Acá no hay cinco lenguajes: hay Claude Code,
  Claude Desktop, Cursor, VS Code y Codex, y cada uno quiere un formato distinto. Es el mismo
  problema que resuelve su `LanguagePicker`. De paso quedó documentada una trampa real: VS Code
  usa la clave `servers` y el resto usa `mcpServers`, así que copiar el bloque equivocado no
  funciona.
- **El esquema de cada herramienta, generado.** Es el equivalente de su
  `APIResponseSchemaPicker`, con una ventaja: no se escribe a mano. Se genera desde el servidor
  al construir la página, así que lo publicado es literalmente lo que un cliente MCP recibe por
  el protocolo, y no puede quedar viejo.
- **Botón de copiar** en cada bloque de código.

Lo que **no** se copia, y conviene decir por qué:

- **El panel para probar en vivo.** En su caso una prueba consulta su API; acá consultaría al
  Poder Judicial desde el navegador de quien lee la documentación, sin intervalo, sin
  identificación y sin bitácora. Es exactamente lo que el proyecto no hace.
- **Migrar a readme.com.** Es de pago y cerrado. Sphinx con Furo ya da buscador, modo oscuro y
  navegación; lo que faltaba eran las tres piezas de arriba.

  Acá se decía además que la documentación se publica en Markdown y `llms.txt` "para que un
  agente la lea sin atravesar HTML", como si eso fuera un argumento de peso. Es una capacidad,
  no una evidencia: Ahrefs midió 137.210 dominios en mayo de 2026 y **el 97% de los `llms.txt`
  publicados no recibió ninguna petición**. Se sigue generando porque no cuesta nada y no
  repite ningún dato, que es el único criterio que tiene que pasar, y no porque conste que
  alguien lo lea.

## El contexto gremial

Tras el colapso de julio de 2026, la Asociación Gremial Legaltech Chile (Altech A.G.,
21 empresas) respondió al Comité de Jueces rechazando prohibir la IA y pidiendo regular:
sostuvo que "la automatización no implica necesariamente el uso de inteligencia artificial" y
que hay que distinguir "entre inteligencia artificial, automatización de procesos,
robotización y otras herramientas tecnológicas", examinando los antecedentes específicos en
vez de juzgar por volumen.

Esa distinción es la misma que estructura este proyecto, con una diferencia que conviene no
perder: el debate público es sobre **ingresar** escritos. Acá no se ingresa nada.
