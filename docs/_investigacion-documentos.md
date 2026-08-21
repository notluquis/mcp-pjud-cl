---
orphan: true
myst:
  html_meta:
    description: "Investigación: cómo entregar el documento de una actuación sin gastar el contexto de quien consulta, qué cuesta una página escaneada como imagen y por qué el OCR sigue afuera."
---

# Investigación: entregar un documento sin gastar el contexto

:::{note}
Documento de trabajo, no publicado. Recoge lo que se midió y lo que se leyó antes de tocar
`obtener_documento`, que **no se tocó**. Se borra cuando lo que propone se ejecute o se
descarte.

No se publica porque `docs/conf.py` excluye `_*.md` del build. El `orphan: true` de la cabecera
quedó de antes, cuando la exclusión no existía y sin él el build con `-W` fallaba por esta
misma página; hoy es inerte y se deja como red por si alguien toca `exclude_patterns`.
:::

## La recomendación, en una frase

Dejar de tratar el documento como una sola cosa que viaja entera o no viaja: entregar primero
un **índice por página** (cuáles traen texto, cuáles son imagen, y los marcadores del archivo),
después el **texto por rango de páginas** a pedido, y no producir imágenes acá, porque hacerlo
mueve al servidor una transformación que hoy no hace y que es el vecino incómodo del OCR.

## La cifra que decide

Lo único que este proyecto midió sobre un documento real está en {doc}`verificacion`: el folio
9 de C-1156-2026, **975.006 bytes, una página, sin capa de texto**. O sea el peor caso posible
en el tamaño más chico posible: una hoja.

De ahí sale la aritmética, con las constantes que ya viven en `client.py`:

| Dato | Valor | De dónde sale |
|---|---|---|
| El documento | 975.006 bytes | medido, una página escaneada |
| En base64 | 1.300.008 caracteres | cuatro caracteres por cada tres bytes |
| Presupuesto de una respuesta | 25.000 caracteres | `CARACTERES_DE_UNA_RESPUESTA` |
| Cuántas veces lo pasa | **52** | división de las dos anteriores |

Esa misma página, mirada como imagen, cuesta **como mucho 1.568 tokens visuales** en el escalón
estándar de Claude, porque una hoja carta escaneada supera el techo de ese escalón y se reduce
antes de procesarse. Cincuenta y dos presupuestos de respuesta contra mil quinientos tokens.

Y conviene decir qué demuestra y qué no. Es **una** página, o sea el caso donde todo lo que
esta página propone rinde menos: un índice de una hoja es la hoja, un rango de páginas es todo
el documento, y los marcadores de un archivo de una página no existen. Lo que prueba es lo
otro: si **una** hoja escaneada, tal como la entrega la plataforma, ya son cincuenta y dos
presupuestos, mover el expediente completo en su formato original no cabe en ninguna respuesta.

Hasta ahí llega lo medido sobre el folio real, y conviene no estirarlo. Más abajo, sobre una
hoja **sintética** y no sobre éste, rasterizar baja el costo a cuatro presupuestos, y bajando la
resolución baja más: la afirmación fuerte, que el expediente no cabe a ninguna resolución, esta
página **no la comprueba**, y del folio 9 rasterizado no hay ninguna cifra. Lo que sí se sostiene es que ninguna resolución la
hace gratis, y que elegirla es una decisión sobre pérdida que el servidor tomaría por el
abogado. Por eso la salida propuesta no es comprimir mejor, es dejar de mover bytes y empezar a
apuntar a páginas. Lo que hace falta medir es el ebook, y de ése no hay ni una cifra.

## Qué cuesta una imagen, y qué cuesta el mismo contenido en texto

### En Claude

La fórmula ya no es la del megapíxel. La
[guía de visión](https://platform.claude.com/docs/en/build-with-claude/vision) dice, textual:

> Claude views images in patches instead of pixels. Each patch is a 28×28-pixel block of the
> image, referred to as a visual token. An image, therefore, costs `⌈width / 28⌉ × ⌈height / 28⌉`
> visual tokens.

Y trae dos escalones, no uno:

| Escalón | Modelos | Borde largo máximo | Tokens visuales máximos |
|---|---|---|---|
| Alta resolución | Claude 4.7 en adelante | 2576 px | 4784 |
| Estándar | los demás | 1568 px | 1568 |

Toda imagen mayor que el techo de su escalón se reduce antes de procesarse, así que una hoja
carta escaneada **no puede costar más que el techo**. La misma página cita el resto de los
límites: dimensiones máximas de 8000 por 8000 píxeles, 10 MB por imagen en la API directa,
32 MB la petición completa, y JPEG, PNG, GIF o WebP como únicos formatos aceptados. TIFF no
está en esa lista, y más abajo se verá por qué importa.

La otra pieza está en el
[soporte de PDF](https://platform.claude.com/docs/en/build-with-claude/pdf-support):

> The system converts each page of the document into an image. The text from each page is
> extracted and provided alongside each page's image.

Y lo cobra dos veces:

> Text token costs: Each page typically uses 1,500–3,000 tokens per page depending on content
> density. […] Image token costs: Because each page is converted into an image, the same
> image-based cost calculations are applied.

Ése es el orden de magnitud de entregar un PDF entero: cada página cuesta los tokens de su
texto **más** los de su imagen. La misma página trae la advertencia que describe justo el caso
del expediente completo:

> Dense PDFs (many small-font pages, complex tables, or heavy graphics) can fill the context
> window before reaching the page limit.

### En ChatGPT

La guía se movió: `platform.openai.com/docs/guides/images-vision` responde 301 hacia
[developers.openai.com](https://developers.openai.com/api/docs/guides/images-vision). Ahí
conviven dos esquemas de cobro según el modelo, mosaicos de 512 px y parches de 32 por 32, y el
reparto no es el intuitivo: `gpt-5` cobra por mosaicos y `gpt-5.4` por parches.

En el esquema de mosaicos, `detail: low` cuesta un plano de 85 tokens en `gpt-4o` y `gpt-4.1`,
70 en `gpt-5`, y `detail: high` cuesta esa base más los mosaicos de 512 px que ocupe la imagen
después de reescalarla. En el de parches, el ejemplo resuelto de la propia documentación es el
que más se parece a una hoja: **1800 por 2400 píxeles dan 4.275 parches**, sobre el presupuesto
de 1.536, así que se reduce a 1056 por 1408 y quedan **1.452 parches**.

Para PDF, [File inputs](https://developers.openai.com/api/docs/guides/file-inputs) confirma lo
mismo que Anthropic:

> On models with vision capabilities, such as `gpt-4o` and later models, the API extracts both
> text and page images and sends both to the model.

No publica fórmula de costo, sólo el aviso de que sube el consumo y un límite de 50 MB por
archivo. Para contarlo hay un endpoint dedicado, `POST /v1/responses/input_tokens`, cuya
[documentación](https://developers.openai.com/api/docs/guides/token-counting) advierte algo que
conviene tener a mano antes de estimar nada: *"Images and files are not supported—estimates like
`characters / 4` are inaccurate"*.

### El mismo contenido en texto

Este proyecto ya tiene su propia medición, citada en `client.py`: una sentencia de trece páginas
son unos veinticinco mil caracteres, o sea **del orden de dos mil caracteres por página**. Ése
es el contraste que importa:

| Cómo viaja una página | Qué cuesta |
|---|---|
| Su texto extraído | del orden de dos mil caracteres |
| Como imagen, escalón estándar | hasta 1.568 tokens visuales |
| Como página de un PDF entregado a la API | los tokens de su texto **más** los de su imagen |
| En base64 dentro de la respuesta | cuatro caracteres por cada tres bytes del archivo |

La única cifra oficial que compara las dos primeras vías de punta a punta está en la sección de
Amazon Bedrock de la página de PDF de Anthropic, y hay que citarla con su alcance, porque
compara dos modos de la Converse API y no dos diseños de servidor: el modo de sólo extracción de
texto *"uses approximately 1,000 tokens for a 3-page PDF"* y el de comprensión visual completa
*"uses approximately 7,000 tokens for a 3-page PDF"*. Siete veces, medido por el proveedor en su
propia plataforma.

### Y el presupuesto que impone el cliente, que es otro

`CARACTERES_DE_UNA_RESPUESTA` es una decisión de este proyecto. El cliente tiene la suya, y está
documentada en [Claude Code](https://code.claude.com/docs/en/mcp):

> Claude Code displays a warning when any MCP tool output exceeds 10,000 tokens […] the default
> maximum is 25,000 tokens

Dos consecuencias que cambian el diseño y no son obvias.

La primera es que **el cliente escribe en disco lo que este servidor decidió no escribir**:

> Without the annotation, results that exceed the default threshold are persisted to disk and
> replaced with a file reference in the conversation.

La regla 5 dice que acá no se persiste nada de terceros. Devolver un expediente entero en la
respuesta no viola esa regla en el servidor y la deja sin efecto igual, porque el documento
judicial termina en el disco de quien consulta sin que nadie lo haya pedido. Es un argumento más
para que el caso normal sea el enlace.

La segunda es que la vía de escape para respuestas grandes **no existe para imágenes**:

> Tools that return image data are still subject to `MAX_MCP_OUTPUT_TOKENS`

> The annotation has no effect on tools that return image content; for those, raising
> `MAX_MCP_OUTPUT_TOKENS` is the only option.

O sea `_meta["anthropic/maxResultSizeChars"]`, que sube el techo hasta 500.000 caracteres, sirve
para texto y no para una página escaneada. Quien quiera devolver imágenes le pide al usuario que
cambie una variable de entorno, que es lo contrario de una herramienta que se puede usar sin
configurar nada.

## Qué hacen los servidores MCP que trabajan con documentos largos

Verificado contra el código de cada proyecto, no contra su descripción.

### Lectura por rango con pista de continuación

El servidor oficial [`fetch`](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch)
expone `max_length` (5000 por omisión) y `start_index`, y cuando corta **le dicta al modelo la
llamada siguiente**: `"Content truncated. Call the fetch tool with a start_index of {next_start}
to get more content."` Dos detalles que sólo se ven en el código y que acá interesan: la pista
es condicional, así que no dice "hay más" cuando el corte cayó justo, y pedir un índice fuera de
rango responde `"No more content available."` en vez de una cadena vacía. Es la regla 4 de este
proyecto escrita por otra gente.

### Índice primero, contenido después

[`jztan/pdf-mcp`](https://github.com/jztan/pdf-mcp) (MIT) es el más completo: trece
herramientas, y la primera, `pdf_info`, devuelve páginas, metadatos, índice, tamaño y cobertura
de texto, con la instrucción explícita de llamarla antes de leer nada. El índice mismo está
acotado: se incluye en línea sólo si trae hasta cincuenta entradas, y sobre eso marca
`toc_truncated` y remite a `pdf_get_toc`.

Su justificación de por qué el detalle va detrás de una bandera es la mejor evidencia de
economía de contexto que apareció, y es del propio autor: con el detalle apagado *"only the
constant-size `summary` is returned, which keeps the payload bounded on large documents (a
3000-page PDF otherwise ships ~6000 ints just for coverage)"*.

El flujo que documenta son cuatro pasos: `pdf_info` para planificar, `pdf_search` para ubicar,
responder con los extractos si alcanzan, y sólo si no alcanzan, `pdf_read_pages("report.pdf",
"89-95")`.

### Buscar dentro en vez de volcar

`pdf_search` del mismo proyecto devuelve `{page, excerpt, position, score}` en vez del
documento, con el extracto delimitado por el párrafo que contiene el acierto y no por una
ventana de ancho fijo. La versión mínima del mismo patrón está en
[`I-CAN-hack/pdf-mcp`](https://github.com/I-CAN-hack/pdf-mcp) (MIT, 284 líneas, cinco
herramientas): recorre páginas y devuelve `[{page, context}]` con cien caracteres alrededor.

### Rasterizar la página, y qué hacen cuando no cabe

`pdf_render_pages` de `jztan/pdf-mcp` es el único que enfrenta en serio el choque entre visión y
tope de transporte, y lo resuelve con **tres desenlaces por página, todos declarados en la
respuesta**: en línea al DPI pedido; en línea pero submuestreada, marcada con una bandera
`likely_illegible_for_fine_detail` que instruye a no responder sobre letra chica desde esa
imagen; o fuera de línea, con la ruta en disco y sin imagen. Además acepta un recorte en
fracciones de página, para el ciclo de mirar barato y después acercarse caro.

`I-CAN-hack/pdf-mcp` expone la misma decisión como un parámetro de una línea:
`output: Literal["base64", "file"]`, con `base64` por omisión, o sea gastando contexto por
defecto.

### Delegar el troceado al sistema de archivos

[`pymupdf4llm-mcp`](https://github.com/pymupdf/pymupdf4llm-mcp), el oficial del equipo de
PyMuPDF y bajo AGPL-3.0, es el más pobre: una sola herramienta. Su única estrategia de contexto
es escribir el markdown a disco y devolver la ruta, y si no se le da ruta corta en diez mil
caracteres y agrega un consejo que empuja al modelo hacia la otra vía.

### Dos hallazgos laterales que valen

**Ninguno de los cuatro usa `ResourceLink`.** Todos reinventan lo mismo con una ruta de texto
plano metida dentro de un diccionario: `file_path_on_disk`, `markdown_path`, `"Image saved to
{path}"`, `"path"`. Este proyecto ya usa la primitiva del protocolo que ellos improvisan, y esa
decisión se sostiene.

**Dos servidores MIT dependen en duro de PyMuPDF, que es AGPL-3.0, y ninguno de los dos lo
menciona en su README.** Es exactamente el conflicto que acá se evitó a propósito, encontrado
en el mundo real y sin declarar.

## Imágenes: quién produce la imagen, y qué llega de verdad al modelo

Ésta es la pregunta que más pesa, y la respuesta honesta es más incómoda que la obvia.

### Lo que la especificación garantiza, y lo que no

En el esquema de la revisión `2026-07-28`, `ImageContent` es *"An image provided to or from an
LLM"*, con `data` en base64 y `mimeType`, ambos obligatorios. Es el **único** camino donde la
especificación es inequívoca sobre que esos bytes son una imagen para el modelo.

Para el otro camino, el propio comentario del tipo `EmbeddedResource` dice lo contrario de una
garantía:

> It is up to the client how best to render embedded resources for the benefit of the LLM
> and/or the user.

Y la página de recursos lo enmarca igual: *"Resources in MCP are designed to be
application-driven, with host applications determining how to incorporate context based on
their needs"*. La especificación **no declara ningún límite de tamaño** en ninguno de los dos
caminos. Lo único que reconoce el problema es el campo `size` de `Resource`, que existe para
que el anfitrión *"estimate context window usage"*, y que este servidor ya llena en su
`ResourceLink`.

### Lo que hacen los clientes reales

En VS Code está en el fuente y es favorable. En
[`mcpLanguageModelToolContribution.ts`](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/contrib/mcp/common/mcpLanguageModelToolContribution.ts),
un `EmbeddedResource` con blob de imagen pasa por la misma rama `addAsInlineData` que un
`ImageContent`, con el comentario *"Rewrite image resources to images so they are inlined
nicely"*, y un `resource_link` de imagen se lee y se incrusta igual. Pero con tres condiciones
que se pisan fácil:

1. **La lista de tipos aceptados no incluye PDF.** `CHAT_ATTACHABLE_IMAGE_MIME_TYPES`, en
   [`chatModel.ts`](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/contrib/chat/common/model/chatModel.ts),
   sólo declara PNG, JPEG, GIF y WebP, y gobierna las ramas de recurso. Un `EmbeddedResource`
   con blob de PDF no da error: **degrada en silencio** a una referencia opaca, y el modelo
   nunca ve la página.
2. **`annotations.audience` puede borrar la imagen.** Si el servidor declara
   `audience: ["user"]`, el contenido no se manda al modelo. Y el ejemplo canónico de
   `ImageContent` de la propia especificación trae justo eso, así que copiarlo tal cual produce
   una imagen invisible.
3. **El cliente reescala antes de mostrarla.** Los bytes que el modelo mira no son los que el
   servidor mandó.

En Claude Code, lo documentado es asimétrico y hay que decirlo con precisión: las herramientas
que devuelven imagen están reconocidas (existe una regla de contabilidad para ellas), y de los
recursos sólo dice que *"Resources are automatically fetched and included as attachments when
referenced"*. **Que un PDF entregado por este servidor termine convertido en imágenes de página
por la API no está documentado en ninguna parte.**

Ése es el hallazgo que ordena todo lo demás: la conversión de página a imagen existe y está
documentada **en la API**, no en el trayecto que va desde una herramienta MCP hasta el modelo.
Suponer que basta con entregar el PDF para que el modelo pueda ver un escaneo es un supuesto sin
medición, y esta página no lo va a dar por bueno.

### Extraer la imagen de dentro del PDF: medido, y no conviene

La idea era tentadora, porque en un escaneo el contenido de la página **es** una imagen
incrustada: extraerla parecía devolver los mismos bytes sin transformar nada. Medido sobre PDF
sintéticos, con la versión de `pypdf` que este proyecto instala, no se cumple ninguna de las
tres cosas que la hacían atractiva.

**Uno: no devuelve los bytes originales.** `_xobj_to_image` termina siempre en
`img.save(img_byte_arr, format=image_format)`, o sea el stream sale reserializado por Pillow y
no copiado del archivo. Comprobado con una hoja carta a 200 ppp guardada como JPEG dentro de un
PDF: **los dos SHA-256 no coinciden**, y el tamaño tampoco (el suelto pesaba unos 194.8 KB y lo
devuelto unos setenta bytes menos). Lo que sostiene el argumento es la primera mitad: el hash
distinto prueba que hubo reserialización, y el tamaño exacto depende de la versión de Pillow. Para JPEG el código conserva los coeficientes con
`quality="keep"`, así que la imagen no se degrada, pero el archivo que sale no es el que entró.

**Dos: el formato que sale puede no servir.** El filtro decide la extensión: `DCTDecode` sale
`.jpg`, `JPXDecode` sale `.jp2`, y `CCITTFaxDecode`, que es el filtro habitual de un escaneo
bitonal, **sale `.tiff`**, que no es un formato que las plataformas acepten. Haría falta una
segunda conversión, y ésa sí decide cosas: qué formato, con cuántos píxeles y con cuánta
pérdida. Cuánto pesa el resultado depende por completo de esas decisiones, y sobre una hoja
sintética la horquilla entre elegir bien y elegir mal fue de dos órdenes de magnitud, así que
no hay una cifra que citar acá hasta medirlo sobre un escaneo real. Lo que sí se sostiene sin
medir nada es que la conversión existe y la decide el servidor.

**Tres: suma dependencias, y una no es de Python.** `page.images` exige el extra `pypdf[image]`,
que arrastra `Pillow`, hoy no instalado acá. Y `JBIG2Decode` se resuelve con
`shutil.which("jbig2dec")`, o sea un **binario del sistema** que hay que instalar aparte y que
si falta convierte el escaneo en un error. JBIG2 es un filtro común en escaneos de documentos,
así que es un caso a soportar y no una rareza.

:::{note}
Las cifras de esta sección y de la siguiente salen de un experimento **sintético y de una sola
corrida**, hecho el 20 de agosto de 2026 con la versión de `pypdf` que el proyecto instala y
`Pillow` traído sólo para eso. No se reproducen en un test a propósito: hacerlo obligaría a
declarar `pypdf[image]`, `Pillow` y un motor de rasterizado como dependencias, que es justo lo
que esta página concluye que no conviene hacer. Lo que sí queda anclado es la aritmética, que
es la mitad que puede quedar vieja por un cambio del código.
:::

### Rasterizar la página: la licencia decide, otra vez

`pypdf` no rasteriza. Es Python puro, no trae motor de dibujo, y renderizar obliga a traer uno.
Ahí vuelve el criterio que ya dejó fuera a PyMuPDF: la licencia manda sobre la velocidad, porque
este proyecto se distribuye bajo PolyForm Strict y enlazar código AGPL pone las dos en
conflicto. Los dos servidores MCP que mejor resuelven el problema, `jztan/pdf-mcp` e
`I-CAN-hack/pdf-mcp`, rasterizan los dos con PyMuPDF: la solución existe y no es adoptable acá.

Sí hay una alternativa permisiva, y conviene dejarla anotada aunque no se use:
[`pypdfium2`](https://pypi.org/project/pypdfium2/) se publica bajo
`BSD-3-Clause, Apache-2.0, dependency licenses`, y el motor que envuelve, PDFium, va bajo una
licencia de estilo BSD. Lo que cuesta no es la licencia sino la forma: a diferencia de `pypdf`,
que es Python puro, trae un binario precompilado por plataforma, así que la rueda de este
proyecto pasaría a depender de uno.

Y aunque se traiga ese motor, rasterizar no resuelve el problema de contexto. Medido sobre la
hoja sintética de 200 ppp reducida al borde largo de 1568 píxeles, guardada como JPEG al
cincuenta por ciento de calidad: **81.566 bytes**, o sea **108.756 caracteres** en base64,
todavía **más de 4 veces** el presupuesto de una respuesta. La imagen sale barata en tokens y cara en
caracteres, y son dos presupuestos distintos que tiran para lados opuestos.

## El límite del OCR, argumentado

La regla que este proyecto ya escribió dice que un escaneo se declara y no se transcribe.
Conviene decir **qué** protege, porque de eso depende dónde cae la línea.

### Lo que protege no es la lectura, es la procedencia

`extract_text()` devuelve caracteres que el documento **trae**. El OCR devuelve la apuesta de
una máquina sobre caracteres que el documento **no trae**. Los dos entrarían por el mismo campo,
con la misma forma, y nada río abajo podría distinguirlos: quien reciba la salida ve texto y no
tiene cómo saber cuál de los dos es. Una transcripción automática de una resolución se ve
idéntica a la resolución y no lo es, y a diferencia de una lista vacía, no se nota. Eso es lo
que la regla evita.

### Por qué mirar no es transcribir

Que el modelo mire la imagen y saque sus conclusiones no colapsa esa procedencia, por tres
razones que se sostienen por separado:

1. **Quién afirma.** El servidor no dice qué dice el documento: entrega el documento. La lectura
   ocurre en la conversación y queda atribuida al modelo, que es un lector como cualquier otro y
   se lo trata como tal.
2. **Quién puede contradecir.** El abogado tiene la misma imagen a la vista. Una lectura
   equivocada es discutible contra la fuente; una transcripción incrustada en la salida del
   servidor viene con el sello de la herramienta y nadie va a ir a contrastarla.
3. **Dónde queda registrada.** Una lectura del modelo vive en el turno de una conversación, con
   su contexto y sus reservas. Una transcripción del servidor vive en un campo que se puede
   copiar, citar y reenviar sin nada de eso alrededor.

Vale la pena decirlo al revés para ver que la distinción no es una excusa: si este servidor
hiciera OCR y devolviera el resultado **etiquetado como transcripción automática**, seguiría
estando mal, porque la etiqueta se pierde en el primer copiado y el texto no. Y si el modelo
mirara la imagen y afirmara sin reservas lo que leyó, también estaría mal, pero ése es un
problema del turno y no del contrato de la herramienta.

### Y la parte incómoda: producir la imagen sí se acerca al límite

El argumento tiene un contra que hay que decir, porque es el que decide el diseño. Si el
**servidor** produce la imagen, la transformó: la decodificó, la reescaló y la volvió a
comprimir. Un dígito que se pierde en ese camino hace exactamente el daño que haría el OCR,
sólo que en un canal donde nadie lo está vigilando. La distancia entre "el servidor no
transcribe" y "el servidor decide con cuántos píxeles se ve la resolución" es más corta de lo
que parece, y la medición de arriba muestra que esa decisión no se puede evitar: la página no
cabe sin reducirla.

De ahí sale la línea, y es de diseño y no una prohibición nueva: **la transformación tiene que
vivir donde vive la lectura.** Si el archivo original llega entero a quien lo va a mirar, la
conversión y la lectura son de la misma parte y se juzgan juntas. Si este servidor entrega una
imagen, se lleva la mitad del riesgo a un lugar donde no está el lector.

Y si algún día hay que cruzarla, la condición mínima ya está inventada por otros: el
`likely_illegible_for_fine_detail` de `jztan/pdf-mcp` es exactamente eso, una imagen que viene
con su propia advertencia de que no sirve para leer letra chica. El equivalente acá sería que el
sobre en palabras diga con qué números se transformó, del mismo modo en que hoy dice cuántas
páginas son imágenes. Un dato transformado en silencio es el modo de falla que este proyecto
entero existe para evitar.

### Lo que esta posición cuesta, dicho de frente

Sumando las dos partes: acá no se hace OCR, no se produce la imagen, y **que el archivo llegue
a los ojos del modelo no está medido en ningún cliente**. La consecuencia neta es que hoy este
servidor puede no tener ninguna vía por la que el modelo lea una resolución escaneada, y la
única que la especificación deja sin ambigüedad, `ImageContent`, es justamente la que se
descarta.

Es un costo elegido y no un descuido. La alternativa era que el servidor decidiera con cuántos
píxeles se ve una resolución, en silencio, para que el modelo pudiera leerla igual: eso es
comprar una capacidad con la garantía que hace utilizable todo lo demás. Quien necesite leer un
escaneo abre el archivo, que es lo que un abogado hace con un expediente de todos modos, y esta
página deja anotado en primer lugar qué habría que medir para cambiar de opinión.

## Qué emite la plataforma: sólo PDF, y hasta dónde está medido

Buscado en las fixtures antes de suponer nada. Las páginas guardadas **no contienen ninguna
referencia a `.doc`, `.docx`, `.xls` ni `.rtf`**. Los
únicos archivos que nombran son dos iconos del propio sitio: `icono_PDF.png`, que aparece en el
detalle de apelaciones, y `downloadPdf.png`, que no está en ningún detalle sino en la página de
la consulta unificada. Y en el cuaderno principal de
C-1156-2026 los enlaces de descarga van marcados **12** veces con el icono `fa-file-pdf-o`.

De las **cabeceras** de respuesta no se sabe nada, y conviene decirlo en vez de darlo por
comprobado: las fixtures son cuerpos HTML, así que ningún `Content-Disposition` aparece ahí ni
podría aparecer. Lo medido es lo que el detalle **dibuja**, no lo que las seis rutas responden.

El código ya se apoya en eso: `_MAGIA_PDF` exige que la respuesta empiece en `%PDF-` y
`EstructuraInesperada` corta si no. Pero está **medido en una de las seis rutas**, `docuN.php`,
y supuesto en las otras cinco. La forma honesta de decirlo es que la plataforma marca sus seis
enlaces como PDF y que una de las seis se ejecutó. No hace falta investigar otros formatos:
hace falta ejecutar las otras cinco rutas cuando haya dónde probarlas.

## Qué se está tirando hoy y sale gratis

`_describir_pdf` ya llama a `extract_text()` en **todas** las páginas y se queda sólo con la
cuenta. El trabajo está pagado y el resultado se descarta. Sin sumar una dependencia, y **en la
misma petición que ya se hizo**, ahí hay:

| Dato | Qué habilita | De dónde sale |
|---|---|---|
| **Cuáles** páginas traen texto, no cuántas | "de la 1 a la 40 se leen, de la 41 a la 200 son imágenes" en vez de "40 de 200" | ya se recorre página por página |
| El texto mismo, por rango | leer dos páginas en vez de mover el archivo entero | `extract_text()`, que ya corre |
| Los marcadores | un índice del expediente antes de pedir contenido | `PdfReader.outline` |
| El tamaño de la página | anticipar cuántos tokens visuales costaría mirarla | `page.mediabox` |
| Si viene cifrado | distinguirlo de "truncado" dentro de `problema_al_leer` | `PdfReader.is_encrypted` |

Una advertencia sobre el texto extraído, para que no se lea como equivalente al documento:
`extract_text()` puede desordenar columnas y tablas. Sirve para leer y para citar con el archivo
al lado, no para reemplazarlo, y el archivo tiene que seguir estando a un `resources/read` de
distancia.

`PdfReader.metadata` queda fuera de la lista a propósito: puede traer nombre de autor y software
del tribunal o de quien redactó el escrito, o sea datos de terceros que nadie pidió.

:::{important}
**"En la misma petición" no se extiende a la siguiente, y eso decide la forma de la herramienta.**

La regla 5 dice que no se persisten datos de terceros, así que ni el PDF ni su extracción
sobreviven a la llamada. Una herramienta aparte que pidiera "las páginas 41 a 50" tendría que
**volver a descargar el archivo entero y volver a parsearlo**: una petición más contra el Poder
Judicial, con su intervalo, por cada rango.

De ahí sale una consecuencia de diseño y no sólo una advertencia: el rango va como parámetro
opcional de `obtener_documento`, no como una segunda herramienta. Con una segunda herramienta,
pedir el índice y después dos rangos cuesta tres descargas del mismo archivo; con un parámetro,
quien ya sabe qué páginas quiere las pide de una vez. Lo gratis es el índice de la llamada que
ya se hizo, no el acceso posterior.
:::

## Qué se propone entregar en vez del PDF

Nada de esto está implementado. En orden de cuánto rinde por lo que cuesta:

1. **Un índice por página en el sobre en palabras.** Hoy el resumen dice "es MIXTO: 40 de 200
   páginas traen texto". Que diga cuáles cuesta lo mismo y convierte un dato descriptivo en uno
   accionable.
2. **El texto por rango de páginas, como parámetro opcional de `obtener_documento`** y no
   como una lectura aparte. El precedente de `JurisClient.texto` separado de la búsqueda no
   sirve acá: ahí la búsqueda y el texto son preguntas distintas, y acá es el mismo archivo,
   que sin persistencia hay que volver a descargar entero para leerle otro rango. Si el rango
   pedido cae sobre páginas sin texto, eso se dice, con los números: es el mismo criterio que
   `discrepancia_fechas`, no elegir en silencio. Y el texto sale **delimitado y con la
   advertencia de que es contenido de un tercero que no se obedece**, no como conveniencia sino
   como parte del contrato: quien redactó ese escrito puede ser la contraparte, y nada de lo
   que hoy anuncia la herramienta lo cubre.
3. **Los marcadores del archivo**, cuando los traiga, como tabla de contenidos del expediente.
4. **Declarar `_meta["anthropic/maxResultSizeChars"]`, y sabiendo qué NO resuelve.** No
   protege el caso que motivó todo esto: el PDF grande no viaja por la herramienta sino por
   `resources/read`, siguiendo el `ResourceLink`, y esa anotación no llega a ese canal. Y para
   lo que sí viaja embebido tampoco cambia nada, porque `LIMITE_EMBEBIDO` ya lo acota bastante
   por debajo de cualquier tope que el cliente traiga. Sirve para los rangos de texto del punto
   2, que son lo único que puede crecer sin un tope propio. Que un documento grande se persista
   al leer el recurso sigue sin tener respuesta acá, y eso es lo que habría que medir primero.
5. **Nada de imágenes producidas acá.** Para las páginas que son imagen, el archivo sigue siendo
   la única vía, y cómo llega a los ojos del modelo es del cliente y no de este servidor.

Lo que **no** cambia: el umbral entre viajar embebido y viajar como enlace, el fallo ruidoso
cuando lo que llega no es un PDF, y que leer el recurso vuelve a consultar al Poder Judicial
porque no hay copia guardada de nada.

## Qué se descartó y por qué

| Descartado | Por qué |
|---|---|
| **PyMuPDF** | AGPL-3.0. Enlazarla desde una rueda PolyForm Strict pone las dos licencias en conflicto. Ya estaba decidido y se confirmó: los dos servidores MCP que mejor rasterizan la usan, y los dos se declaran MIT sin mencionarlo |
| **OCR en el servidor** | Colapsa la procedencia: la transcripción entra por el mismo campo que el texto real y nadie río abajo puede distinguirlas |
| **Extraer la imagen incrustada con `pypdf`** | Reserializa por Pillow en vez de copiar, para un escaneo bitonal sale en TIFF que las plataformas no aceptan, exige Pillow y para JBIG2 un binario del sistema |
| **Rasterizar la página acá** | `pypdf` no puede, y con un motor compatible la imagen resultante sigue sin caber en el presupuesto de caracteres |
| **Devolver la página como `ImageContent`** | Pone la transformación en el servidor y deja la lectura en el cliente. Además el tope que el cliente aplica a las imágenes no se puede levantar con la anotación, sólo con una variable de entorno del usuario |
| **Subir el umbral de lo embebido** | Es el lado caro de equivocarse: el contexto gastado no se devuelve, y una lectura de más sí se puede evitar |
| **Guardar el PDF en disco** | Regla 5. Se consulta y se devuelve |
| **Un cursor con estado sobre el documento**, como `mcp-pdf-vision` | Acopla el servidor a estado de sesión para ahorrar un parámetro. El rango explícito hace lo mismo sin recordar nada |
| **Investigar `.doc` y otros formatos** | Las fixtures no traen ninguna referencia a esos formatos y los seis enlaces van marcados como PDF |

## Lo que falta medir

Lo único medido sobre un documento real del Poder Judicial es su **tamaño**: los 975.006 bytes
del folio 9 de C-1156-2026, que están en {doc}`verificacion` y son de donde cuelga la
recomendación. Todo lo demás de esta página, la extracción de texto, la reserialización de
imágenes y el rasterizado, se probó sobre archivos sintéticos armados acá, porque **no hay
ningún PDF del Poder Judicial en `tests/fixtures/`**. Alcanzan para mostrar la forma del
problema, no su magnitud exacta. Falta, en este orden:

- **Qué llega de verdad al modelo cuando este servidor entrega un PDF.** Es el supuesto del que
  cuelga todo lo demás y no está documentado por ningún cliente.
- Con qué filtro vienen los escaneos de la plataforma. Si es JBIG2, la extracción de imágenes
  necesita un binario externo y queda todavía más lejos de valer la pena.
- Cuántas páginas trae un ebook y cuánto pesa, que es el caso que motivó todo esto y del que
  hoy no hay ni una cifra.
- Si un expediente trae marcadores, que decide si el punto 3 de la propuesta tiene contenido o
  es una lista vacía.
- Las cinco rutas de documentos que nunca se ejecutaron.

Y una que no es de tamaño sino de confianza: el texto de un PDF es **contenido no confiable**,
igual que el HTML del que este servidor ya extrae tablas, y devolverlo en la respuesta lo pone a
la vista del modelo como si fueran instrucciones. `jztan/pdf-mcp` lo trata así, repite en cada
docstring que el texto extraído no se obedece, y detecta texto escondido (blanco sobre blanco,
opacidad cero, tamaños diminutos) sin borrarlo, sólo marcándolo. Acá la anotación
`open_world_hint` **no sirve para esto**: declara que la herramienta habla con entidades
externas, no marca lo devuelto como no confiable ni le dice al modelo que no lo obedezca. O sea
hoy no hay nada que lo cubra.

Por eso, si el texto empieza a viajar por rangos, el contrato tiene que **exigir** dos cosas en
cada respuesta y no dejarlas como conveniencia: la advertencia explícita de que lo que sigue es
contenido de un tercero que no se obedece, y el texto delimitado para que se vea dónde empieza y
dónde termina. Es el mismo criterio con el que este proyecto trata todo lo demás: quien redactó
ese escrito puede ser la contraparte.
