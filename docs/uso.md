---
myst:
  html_meta:
    description: "Qué significa cada campo de la respuesta y cuándo desconfiar de ella. Para quien va a computar un plazo con esto."
---

# Cómo se usa e interpreta

Esta página no tiene código. Si quieres instalarlo, pásale la {doc}`guía de instalación <instalacion>` a quien administre tus sistemas.

## Qué problema resuelve

Cuando descargas el ebook de una causa desde la Oficina Judicial Virtual, **no vienen las
actuaciones del receptor**. En un caso real, el folio 12 de un cuaderno de apremio aparecía
en el ebook como una sola línea que decía "validación", sin fecha de diligencia.

La fecha real de esa diligencia, la que determina si un plazo de cuatro u ocho días se cumple
o se pierde, sólo está visible en la interfaz web, y sólo si sabes dónde mirar.

Esta herramienta va a buscar esa información y te la entrega con las fechas separadas y
etiquetadas.

## Las dos fechas, y por qué se confunden

En la web, la columna `Fec. Trámite` de una actuación de receptor se ve así:

```
31/03/2026 (27/03/2026)
```

Son **dos fechas distintas**:

| Fecha | Qué es | ¿Corre plazos? |
|---|---|---|
| `31/03/2026`, la primera | Cuándo el tribunal registró el trámite en el sistema | **No** |
| `27/03/2026`, la del paréntesis | Cuándo el receptor practicó realmente la diligencia | **Sí** |

Y la descripción del trámite trae la misma fecha, con hora:

```
NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:27/03/2026 17:40
```

La herramienta te devuelve `fecha_diligencia: 2026-03-27` y `fecha_registro: 2026-03-31` como
campos aparte. No hay que interpretar ningún paréntesis.

:::{note}
Las fechas se entregan en formato **ISO 8601** (`2026-03-27`, año-mes-día) y no en formato
chileno. Es deliberado: `06/09/2026` es ambiguo (¿6 de septiembre o 9 de junio?) y acá
confundirse cuesta un plazo.
:::

## Los cuadernos: lo que casi se nos pasa

La interfaz web muestra la historia de **un cuaderno a la vez**. Si tu causa tiene cuaderno de
apremio, hay un desplegable que la mayoría no nota.

Durante el desarrollo, la herramienta leía sólo el cuaderno que venía por defecto. En
C-1156-2026 eso significaba devolver 3 actuaciones de 6, y **las 3 que faltaban eran el
requerimiento de pago, el embargo y la inscripción**: justo las que corren plazos en un juicio
ejecutivo.

Ya está corregido: **se recorren todos los cuadernos**, y cada actuación te dice a cuál
pertenece. Se menciona acá porque es el tipo de omisión que se ve completa y no lo está.

## Qué te devuelve

Por cada actuación del ministro de fe:

`fecha_diligencia`
: Cuándo se practicó realmente. **Es la que corre los plazos.**

`hora_diligencia`
: La hora, cuando la descripción la trae.

`fecha_registro`
: Cuándo se registró en el sistema. No corre plazos.

`discrepancia_fechas`
: Si sale `true`, las dos fuentes de fecha de la propia plataforma **no coinciden**. La
herramienta no elige por ti: te avisa para que lo revises a mano.

`cuaderno`
: A qué cuaderno pertenece. Ej: `2 - Apremio Ejecutivo Obligación de Dar`.

`desc_tramite`
: El texto literal, sin normalizar. Ej: `NOTIFICACIÓN DE DEMANDA (Búsqueda negativa)`.

`georreferenciado`
: Si la actuación tiene registro georreferenciado. **Cuando dice `false` en civil, cobranza,
laboral o apelaciones, significa que ese registro no está**, y su ausencia puede ser
jurídicamente relevante (art. 9 inc. 3 de la Ley 20.886). Por eso el campo se muestra siempre,
incluso vacío: omitirlo sería esconder un dato que quizá quieras alegar.

  En suprema el sitio no publica esa columna, así que ahí el `false` significa que no hay dónde
  mirar. Y el `true` significa que el sitio ofrece la georreferencia, no que exista: de seis
  actuaciones medidas, una abría un panel que dice que no hay ninguna.

`tiene_documento`
: Si el folio tiene documento descargable en la plataforma.

## Diligencias que vas a ver

Las observadas en causas civiles:

- `NOTIFICACIÓN DE DEMANDA (Búsqueda negativa)`
- `NOTIFICACIÓN DE DEMANDA (Exitosa)`
- `CERTIFICACIÓN BÚSQUEDAS (Búsqueda positiva)`
- `Requerimiento de Pago (Ficto)`
- `EMBARGO (Exitosa)`
- `Inscripción / Alzamiento registro (Certificación)`

## Por qué la directiva es corta

El servidor entrega una directiva por el protocolo, y el cliente la **corta en 2.048 bytes sin
avisar**. Pesaba 3.770, así que 1.722 bytes no llegaban, y lo que caía del otro lado eran tres
reglas de las que evitan afirmar de más: que `ocultas` en nulo no es cero, que una cita no está
verificada si la búsqueda no la devolvió, y el régimen de consultas.

Un corte silencioso se ve igual que un texto que termina. Por eso no se descubrió leyendo: se
descubrió midiendo lo que viaja por el cable, con el servidor en otro proceso.

Ahora cabe entera, y lo que salió no se borró: se mudó a la herramienta que lo necesita, donde
el modelo lo lee justo antes de usarla. Cada frase mudada tiene guardia de dos caras, presente
donde manda y **ausente de la directiva**, porque reponerla ahí la llena otra vez en silencio y
el corte se lleva otra regla.

Es el mismo problema que el catálogo de herramientas, una capa más arriba: pesaba 104.475
caracteres y el cliente difiere las definiciones sobre el 10% de su ventana, así que una sesión
cargó diez de las catorce sin señal de que le faltaban cuatro. La herramienta que el modelo no
ve no la puede pedir, y eso no falla: calla.

## Un error no es una ausencia

Es la misma regla que gobierna el parser, dicha una capa más abajo. Cuando la plataforma no
contesta, contesta 503, o devuelve una página donde prometía JSON, la respuesta correcta no es
una lista vacía: es un error que diga qué pasó.

Costó descubrirlo. La primera sesión que usó esto de verdad reportó dos consultas colgadas y lo
dijo así: *"Los tres cuelgues devolvieron 'no result received'. Nada distingue 'no respondió'
de 'no existe'. Un lector apurado reporta que la causa no existe."*

Y era exacto: `httpx.TimeoutException` es **hermana** de `NetworkError`, no subclase, así que la
clasificación que atrapa los rechazos no la tomaba y salía cruda. Ahora las tres dicen
textualmente que no significa que la causa no exista, y ninguna detiene el proceso: la
detención total es para cuando la plataforma nos rechaza a propósito, y un portal lento no
rechaza a nadie.

## Por qué te avisa que está trabajando

Una consulta no es una petición: son varias encadenadas, y entre cada una el servidor espera
a propósito, porque el ritmo se lo debe a la plataforma. Abrir sesión, buscar la causa, abrir
su detalle y recorrer sus cuadernos toma minutos, no segundos.

Desde afuera eso se ve exactamente igual que un cuelgue. La misma sesión que reportó los
cuelgues de arriba los describió así: nada distinguía "no respondió" de "no existe". Y hay una
consecuencia más: muchos clientes cortan la llamada por su cuenta al cabo de unos segundos sin
noticias, así que la consulta moría por el reloj del cliente mientras el servidor seguía
esperando la respuesta del Poder Judicial.

Por eso ahora el servidor avisa cada petición antes de que salga, con una frase de qué está
haciendo ("abriendo sesión", "buscando la causa", "cuaderno 2 de 2") y, cuando se sabe de
antemano, cuántas faltan. El protocolo permite que el cliente reinicie su reloj al recibir uno.

Qué esperar de eso:

- **Depende del cliente.** Si el tuyo no muestra progreso, la consulta funciona igual: los
  avisos se descartan y no cambian ni lo que se consulta ni lo que se responde.
- **La cuenta no siempre existe.** Una búsqueda que puede recorrer varias páginas no sabe
  cuántas va a necesitar hasta llegar a la última, así que ahí se avisa el paso sin prometer
  un total. Anunciar el tope sería una barra que se queda pegada cerca del principio.
- **Un aviso no es un resultado.** Que la barra avance dice que la plataforma sigue
  contestando, no que la causa exista ni que se haya podido leer.

## Por qué la bitácora separa los dos tiempos

Cada petición que sale queda anotada con lo que tardó la plataforma y, aparte, con lo que se
esperó por el ritmo. Juntos no distinguen "el portal va lento" de "nos estamos frenando solos",
y ésa es justo la pregunta cuando una consulta parece colgada.

No es teórico: las dos consultas que obligaron a subir el techo de espera no se pudieron
diagnosticar porque nada registraba duraciones por petición. De ellas se conoce una cota
inferior, no una duración, porque el timeout las mató.

## Qué NO hace

Decirlo con todas sus letras evita malentendidos caros:

**No ingresa escritos.** Ni ahora ni nunca. Es solo lectura por diseño, y no existe el código
para escribir. Esto importa por el antecedente de julio de 2026, cuando un ingreso
automatizado masivo hizo colapsar la Oficina Judicial Virtual: la distinción entre **leer** e
**ingresar** es toda la diferencia entre esta herramienta y aquello.

**No entra a "Mis Causas".** Eso requiere Clave Única. Acá sólo se consulta lo público. Como
efecto lateral útil, sirve para personas jurídicas, que no tienen Clave Única.

**No ve causas reservadas.** Y ojo: un resultado vacío **no prueba** que la causa no exista.
Puede estar reservada.

**No cubre familia.** La plataforma reserva esas causas a Clave Única, así que quedan fuera de
lo público. Las otras seis se buscan (civil, laboral, cobranza, penal, apelaciones y suprema) y
el detalle se lee en cinco: en penal se busca y no se abre el detalle, por decisión, porque su
carátula trae el nombre del imputado.

**No reemplaza tu criterio.** Acerca la fuente oficial. Antes de computar un plazo a partir de
esto, verifica el expediente.

## Cuándo desconfiar del resultado

- **`discrepancia_fechas: true`** → las dos fuentes del sitio se contradicen. Revisa a mano.
- **Un error en vez de un resultado** → si la plataforma cambia su estructura, la herramienta
  **falla ruidosamente** en lugar de devolver una lista vacía. Es a propósito: una lista vacía
  se lee como "no hubo actuaciones", y así se pierden plazos. Si ves un error, repórtalo.
- **La causa aparece sin actuaciones** → puede ser correcto, o puede ser que la causa esté en
  una competencia no cubierta.

## Lo que necesitas saber de la licencia

El software se entrega bajo [PolyForm Strict 1.0.0](https://polyformproject.org/licenses/strict/1.0.0),
que permite **ejecutarlo con fines no comerciales**.

**El ejercicio profesional remunerado no está cubierto.** Si facturas a tus clientes,
necesitas permiso escrito, aunque uses la herramienta sólo para tus propias causas.

Se pide [abriendo un issue](https://github.com/notluquis/mcp-pjud-cl/issues/new/choose) con la
plantilla "Solicitud de permiso de uso". Se otorga caso a caso y **sin costo**: la licencia
restrictiva existe para saber quién usa esto y para qué, no para cobrar.

Si vas a **guardar** los resultados, lee la parte de {doc}`cumplimiento` sobre la Ley 21.719,
que entra en vigencia el 1 de diciembre de 2026. Al almacenar datos de terceros pasas a ser
responsable del tratamiento.
