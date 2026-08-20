"""Servidor MCP de solo lectura para la consulta pública de causas.

Proyecto independiente, sin relación alguna con el Poder Judicial de Chile ni con la
Corporación Administrativa del Poder Judicial.
"""

from __future__ import annotations

import base64
import os
from typing import Annotated
from urllib.parse import quote, urlencode

from mcp.server import MCPServer
from mcp.types import (
    BlobResourceContents,
    ContentBlock,
    EmbeddedResource,
    ResourceLink,
    TextContent,
    ToolAnnotations,
)
from pydantic import Field

from .client import (
    CON_TRIBUNAL,
    DESCRIPCION,
    DOCUMENTOS,
    INTERVALO_MINIMO,
    LIMITE_EMBEBIDO,
    MODULOS,
    PAGINAS_MAXIMAS,
    RAFAGA_MAXIMA,
    VERSION,
    Corte,
    Documento,
    PjudClient,
    Tribunal,
)
from .juris import (
    BUSCADORES,
    FECHA_MEDICION,
    FILAS_MAXIMAS,
    INDEXADAS_MEDIDAS,
    VISIBLES_MEDIDAS,
    JurisClient,
    ResultadoJurisprudencia,
    TextoSentencia,
    miles,
)
from .parser import COMPETENCIAS, Actuacion, CausaEncontrada, DetalleCausa

#: Con qué hay que acotar las búsquedas de nombre, RUT y fecha, según la competencia. Se
#: deriva de la tabla en vez de escribirse a mano, por la misma razón que `_CON_RECEPTOR`: el
#: contrato que ve el modelo es lo único que tiene para saber qué llamada es válida, y una
#: descripción que se quedó atrás lo hace intentar una consulta que este servidor rechaza y
#: atribuir el rechazo a la plataforma.
_EXIGEN_TRIBUNAL = sorted(n for n in MODULOS if COMPETENCIAS[n].acota_por == "tribunal")
_EXIGEN_CORTE = sorted(n for n in MODULOS if COMPETENCIAS[n].acota_por == "corte")
_SIN_ACOTAR = sorted(n for n in MODULOS if COMPETENCIAS[n].acota_por is None)

#: La misma regla dicha una vez, para las tres herramientas que la comparten.
ACOTACION = (
    "Las búsquedas por nombre, por RUT y por fecha hay que acotarlas, y con qué depende de "
    f"la competencia: {', '.join(_EXIGEN_TRIBUNAL)} exigen `tribunal`; "
    f"{', '.join(_EXIGEN_CORTE)} exige `corte` y NO acepta tribunal; "
    f"{', '.join(_SIN_ACOTAR)} no exige ninguna de las dos. La búsqueda por rol no exige "
    "acotar en ninguna."
)

# La directiva viaja en el propio protocolo, no sólo en el README: quien conecte este
# servidor la recibe antes de llamar cualquier herramienta.
DIRECTIVA = f"""\
Consulta pública de causas del Poder Judicial de Chile. Solo lectura: este servidor no
puede ingresar escritos ni modificar nada, y no existe código para hacerlo.

Al informar fechas de actuaciones de receptor, distinguir siempre:

  - `fecha_diligencia`: cuándo el ministro de fe practicó la diligencia. ES LA QUE
    CORRE LOS PLAZOS PROCESALES.
  - `fecha_registro`: cuándo se registró en el sistema. NO corre plazos.

Suelen diferir en varios días. El ebook que entrega la Oficina Judicial Virtual no trae
ninguna de las dos, y ésa es la razón de existir de esta herramienta. Si
`discrepancia_fechas` es verdadero, las dos fuentes del sitio no coinciden: informarlo
en vez de elegir una.

`georreferenciado: false` significa que la actuación NO tiene registro georreferenciado
(art. 9 inc. 3 Ley 20.886), lo que puede ser jurídicamente relevante. No omitir el dato.

Las causas reservadas no aparecen en la consulta pública: un resultado vacío no prueba
que la causa no exista.

{ACOTACION}

Si una búsqueda excede el tope de páginas, la herramienta falla en vez de devolver una
lista recortada. Ese error significa "hay más resultados de los que caben", no "no hay
resultados": acotar la búsqueda o subir `paginas`, nunca informar que no se encontró nada.

Sobre jurisprudencia: `buscar_jurisprudencia` consulta el Buscador Unificado de Fallos.
Su resultado trae `ocultas`, que es cuántas coincidencias existen y NO se entregan a una
consulta anónima. Si `ocultas` es mayor que cero, la lista es un subconjunto y hay que
decirlo: NO se puede afirmar que algo no existe porque no aparezca.
Medido el {FECHA_MEDICION} sin filtros: {miles(VISIBLES_MEDIDAS)} visibles
de {miles(INDEXADAS_MEDIDAS)} indexadas.

Una sentencia que la herramienta no encuentra puede ser inexistente, reservada o estar
fuera del buscador. Son cosas distintas y se informan distinto. Nunca presentar una cita
como verificada si la búsqueda no la devolvió.

Sobre documentos: `documento_referencia` CADUCA con la sesión en que se leyó, así que se
usa en el momento y no se guarda para después. Si `obtener_documento` avisa que lo que
llegó no es un PDF, casi siempre es eso: se vuelve a pedir el detalle de la causa.
Un documento que llega declarado como escaneo NO se transcribe, ni con OCR propio: una
transcripción automática de una resolución se ve idéntica a la resolución y no lo es. Se
informa que es un escaneo y se entrega el archivo.

Las consultas van a ritmo controlado: hasta {RAFAGA_MAXIMA} peticiones seguidas y después
una cada {INTERVALO_MINIMO:.0f} segundos, que implementa la prohibición de sobrecargar la
plataforma. Una consulta de actuaciones son
varias peticiones encadenadas, así que tarda. No es un error ni algo que convenga paralelizar.

Esto acerca la fuente oficial, no reemplaza la revisión de un abogado ni la lectura del
expediente.
"""

SOLO_LECTURA = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    # Consulta un sistema externo: lo que devuelve es contenido no confiable.
    open_world_hint=True,
)

#: La identidad que el servidor publica en `server/discover`, que la especificación de MCP
#: exige implementar desde la revisión 2026-07-28. Ahí viaja `serverInfo` con nombre y versión.
#:
#: La versión estaba en su valor por defecto, o sea vacía: el servidor se presentaba ante los
#: clientes MCP sin decir qué versión era. Es el mismo descuido que el User-Agent tenía con el
#: Poder Judicial, y sale de la misma fuente única para que no vuelva a separarse.
#:
#: La propia especificación advierte que estos datos son para mostrar, registrar y depurar, y
#: que un cliente no debe usarlos para decidir nada de seguridad. Acá sirven para que quien
#: reporte un problema pueda decir contra qué versión lo vio.
mcp = MCPServer(
    "mcp-pjud",
    title="Consulta de causas del Poder Judicial de Chile",
    description=DESCRIPCION,
    version=VERSION,
    website_url="https://mcp-pjud-cl.readthedocs.io",
    instructions=DIRECTIVA,
)

_CONTACTO = os.environ.get("MCP_PJUD_CONTACTO", "")


def _contacto() -> str:
    if not _CONTACTO:
        raise ValueError(
            "Falta la variable de entorno MCP_PJUD_CONTACTO. El Poder Judicial debe "
            "poder identificar y contactar a quien consulta; sin eso el servidor no opera."
        )
    return _CONTACTO


def _cliente() -> PjudClient:
    return PjudClient(_contacto())


#: Competencias donde el rol publicado lleva el libro adelante. Sale de la tabla: la referencia
#: lo explicaba y el esquema seguía diciendo "Letra del rol", y lo que el modelo lee es esto.
_CON_LIBRO = sorted(n for n in MODULOS if COMPETENCIAS[n].rol_con_libro)
Tipo = Annotated[
    str,
    Field(
        description="Letra del rol. En civil: C, V, E, A, F o I. En "
        f"{', '.join(_CON_LIBRO)} va el LIBRO en vez de una letra (por ejemplo 'Protección' "
        "o 'Exhorto'): ahí el número de rol se repite entre libros, así que sin él la "
        "consulta es ambigua y la herramienta falla en vez de abrir la causa equivocada."
    ),
]
Rol = Annotated[int, Field(description="Número del rol, sin la letra ni el año.", ge=1)]
Anio = Annotated[int, Field(description="Año del rol, cuatro dígitos.", ge=1900, le=2100)]
#: Lo que el modelo ve. Son las verificadas y no las que existen: anunciar una que el
#: cliente rechaza hace que el modelo la intente, reciba un error y se lo atribuya a la
#: plataforma.
Competencia = Annotated[
    str,
    Field(description=f"Una de: {', '.join(sorted(MODULOS))}."),
]
CodigoTribunal = Annotated[
    int | None,
    Field(
        description="Código del tribunal. Obligatorio en las búsquedas de nombre, RUT y "
        f"fecha cuando la competencia es una de: {', '.join(_EXIGEN_TRIBUNAL)}. En "
        f"{', '.join(_EXIGEN_CORTE + _SIN_ACOTAR)} la plataforma no lo usa. En la búsqueda "
        "por rol es opcional siempre, y omitirlo AMPLÍA los resultados."
    ),
]
Paginas = Annotated[
    int,
    Field(
        description="Cuántas páginas de resultados recorrer como máximo. La plataforma "
        "devuelve 100 por página. Si la búsqueda excede este tope, la herramienta falla en "
        "vez de devolver una lista recortada, porque un listado truncado en silencio se "
        "leería como si no hubiera más resultados.",
        ge=1,
        le=50,
    ),
]
#: Las competencias que de verdad entregan actuaciones de ministro de fe por esta vía. Se
#: deriva de la tabla y no se escribe a mano: el alias general ofrecía las cuatro buscables, y
#: tres de ellas terminan siempre en error acá. Ofrecerle al modelo una opción que siempre
#: falla lo hace intentarla y atribuir el error a la plataforma.
_CON_RECEPTOR = sorted(
    n for n in MODULOS if COMPETENCIAS[n].receptor and COMPETENCIAS[n].receptor_en_historia
)
CompetenciaConReceptor = Annotated[
    str,
    Field(
        description=f"Una de: {', '.join(_CON_RECEPTOR)}. Sólo esas publican las actuaciones "
        "del ministro de fe en la tabla de Historia. En cobranza existen pero viven en otro "
        "panel que este servidor todavía no lee, y en las demás no existen."
    ),
]

#: Las competencias que se acotan POR TRIBUNAL, o sea aquellas donde su listado sirve para
#: buscar. Medido el 20 de agosto de 2026 sobre la corte 46 con las seis: suprema devuelve
#: `null` porque ES la corte, y apelaciones devuelve 118 juzgados de primera instancia que no
#: son con qué se busca ahí. Ofrecerlas invitaría a usar esa lista como si fuera `tribunal`.
_CON_TRIBUNAL = sorted(CON_TRIBUNAL)
CompetenciaConTribunal = Annotated[
    str,
    Field(
        description=f"Una de: {', '.join(_CON_TRIBUNAL)}. Son las que se acotan por tribunal, "
        "o sea aquellas donde este listado sirve para buscar. Suprema no tiene tribunales "
        "debajo y apelaciones se acota por corte."
    ),
]

#: Las competencias con al menos un panel del detalle medido. `penal` no está: ninguno de los
#: suyos lo está, así que la lectura combinada la rechaza siempre. Ofrecerla en el esquema hace
#: que el modelo la intente, reciba un error y se lo atribuya a la plataforma.
_CON_DETALLE = sorted(
    n
    for n in MODULOS
    if any(
        (
            COMPETENCIAS[n].historia,
            COMPETENCIAS[n].litigantes,
            COMPETENCIAS[n].notificaciones,
            COMPETENCIAS[n].liquidaciones,
            COMPETENCIAS[n].materias,
            COMPETENCIAS[n].exhortos,
        )
    )
)
CompetenciaConDetalle = Annotated[
    str,
    Field(
        description=f"Una de: {', '.join(_CON_DETALLE)}. Son aquellas con al menos un panel del "
        "detalle medido contra una respuesta real."
    ),
]

CodigoCorte = Annotated[
    int | None,
    Field(
        description="Código de la corte. Obligatorio en las búsquedas de nombre, RUT y "
        f"fecha cuando la competencia es una de: {', '.join(_EXIGEN_CORTE)}, donde la "
        "plataforma responde 'Por favor seleccione una Corte para la búsqueda'. En el resto, "
        "OMITIR salvo certeza: fijarla produce falsos negativos, porque excluye causas "
        "radicadas en otra jurisdicción."
    ),
]


@mcp.tool(
    title="Listar las Cortes de Apelaciones y su código",
    annotations=SOLO_LECTURA,
)
def listar_cortes() -> list[Corte]:
    """Las Cortes de Apelaciones con el código que las búsquedas exigen.

    Llamar esto ANTES de buscar por nombre, RUT o fecha en apelaciones: el parámetro `corte`
    es obligatorio ahí y su valor no aparece en ninguna otra respuesta.
    """
    with _cliente() as c:
        return c.listar_cortes()


@mcp.tool(
    title="Listar los tribunales de una corte y su código",
    annotations=SOLO_LECTURA,
)
def listar_tribunales(
    corte: Annotated[
        int,
        Field(
            description="Código de la corte, el que entrega `listar_cortes`. Obligatorio: sin "
            "él habría que elegir una, y devolver los tribunales de otra jurisdicción es una "
            "lista plausible y equivocada.",
            ge=1,
        ),
    ],
    competencia: CompetenciaConTribunal = "civil",
) -> list[Tribunal]:
    """Los tribunales de una corte, con el código que las búsquedas exigen.

    Llamar esto ANTES de buscar en primera instancia: `tribunal` es obligatorio ahí y su valor
    no aparece en ninguna otra respuesta, así que sin esto hay que sabérselo de memoria.

    También es la forma de seguir un exhorto. El detalle entrega el tribunal de destino por su
    NOMBRE, y la búsqueda pide el código: se ubica la corte con `listar_cortes`, se piden sus
    tribunales acá, y con ese código se busca la causa de destino por su rol.
    """
    with _cliente() as c:
        return c.listar_tribunales(competencia, corte)


@mcp.tool(
    title="Buscar causa por rol",
    annotations=SOLO_LECTURA,
)
def buscar_causa_por_rit(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: Competencia = "civil",
    tribunal: CodigoTribunal = None,
    corte: CodigoCorte = None,
    paginas: Paginas = PAGINAS_MAXIMAS,
) -> list[CausaEncontrada]:
    """Busca causas por rol en la consulta pública. Ej: tipo='E', rol=468, anio=2026."""
    with _cliente() as c:
        return c.buscar_por_rit(tipo, rol, anio, competencia, tribunal, corte, paginas)


@mcp.tool(
    title="Buscar causa por nombre",
    annotations=SOLO_LECTURA,
)
def buscar_causa_por_nombre(
    apellido_paterno: Annotated[str, Field(description="Apellido paterno del litigante.")] = "",
    apellido_materno: Annotated[str, Field(description="Apellido materno del litigante.")] = "",
    nombre: Annotated[str, Field(description="Nombres del litigante.")] = "",
    anio: Annotated[int | None, Field(description="Año de ingreso, opcional.")] = None,
    competencia: Competencia = "civil",
    tribunal: CodigoTribunal = None,
    corte: CodigoCorte = None,
    paginas: Paginas = PAGINAS_MAXIMAS,
) -> list[CausaEncontrada]:
    """Busca causas por nombre de litigante.

    Exige al menos DOS de los tres campos de nombre. El año no cuenta para ese mínimo.

    Hay que acotar la búsqueda: con qué depende de la competencia, y lo dicen las
    descripciones de `tribunal` y de `corte`.
    """
    with _cliente() as c:
        return c.buscar_por_nombre(
            nombre, apellido_paterno, apellido_materno, anio, competencia, tribunal, corte, paginas
        )


@mcp.tool(
    title="Buscar causa por RUT de empresa",
    annotations=SOLO_LECTURA,
)
def buscar_causa_por_rut_juridica(
    rut: Annotated[int, Field(description="RUT sin dígito verificador ni puntos.", ge=1)],
    digito_verificador: Annotated[str, Field(description="Dígito verificador: 0-9 o K.")],
    anio: Annotated[int | None, Field(description="Año de ingreso, opcional.")] = None,
    competencia: Competencia = "civil",
    tribunal: CodigoTribunal = None,
    corte: CodigoCorte = None,
    paginas: Paginas = PAGINAS_MAXIMAS,
) -> list[CausaEncontrada]:
    """Busca causas de una persona jurídica por su RUT.

    Es la única vía para empresas: no tienen Clave Única, así que no aparecen en
    "Mis Causas".
    """
    with _cliente() as c:
        return c.buscar_por_rut_juridica(
            rut, digito_verificador, anio, competencia, tribunal, corte, paginas
        )


@mcp.tool(
    title="Buscar causas por fecha de ingreso",
    annotations=SOLO_LECTURA,
)
def buscar_causa_por_fecha(
    desde: Annotated[str, Field(description="Fecha inicial del rango, DD/MM/AAAA.")],
    hasta: Annotated[str, Field(description="Fecha final del rango, DD/MM/AAAA.")],
    competencia: Competencia = "civil",
    tribunal: CodigoTribunal = None,
    corte: CodigoCorte = None,
    paginas: Paginas = PAGINAS_MAXIMAS,
) -> list[CausaEncontrada]:
    """Causas ingresadas en un rango de fechas.

    Existía en el cliente y no estaba expuesta: es la cuarta búsqueda que la plataforma
    ofrece, y sin ella no hay forma de responder "qué ingresó contra esta empresa esta
    semana" sabiendo el tribunal pero no el rol.

    Un solo día en un solo tribunal puede devolver decenas de causas, así que conviene
    acotar el rango antes de subir el tope de páginas.
    """
    with _cliente() as c:
        return c.buscar_por_fecha(desde, hasta, competencia, tribunal, corte, paginas)


@mcp.tool(
    title="Actuaciones del receptor",
    annotations=SOLO_LECTURA,
)
def obtener_actuaciones_receptor(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: CompetenciaConReceptor = "civil",
    tribunal: CodigoTribunal = None,
    corte: CodigoCorte = None,
) -> list[Actuacion]:
    """Actuaciones del ministro de fe con su fecha real de diligencia.

    Es el dato que el ebook oficial de la Oficina Judicial Virtual omite y del que
    dependen los plazos procesales. Devolver `fecha_diligencia`, no `fecha_registro`.
    """
    with _cliente() as c:
        return c.actuaciones_receptor(tipo, rol, anio, competencia, tribunal, corte)


@mcp.tool(
    title="Detalle de la causa: historia, partes y notificaciones",
    annotations=SOLO_LECTURA,
)
def obtener_detalle_causa(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: CompetenciaConDetalle = "civil",
    tribunal: CodigoTribunal = None,
    corte: CodigoCorte = None,
) -> DetalleCausa:
    """Historia, litigantes, notificaciones, liquidaciones, materias y exhortos de la causa.

    Recorre TODOS los cuadernos, no sólo el que la plataforma muestra por defecto, y lo hace
    con una sola cadena de peticiones. Preferir esta herramienta antes que preguntar por
    partes: los paneles vienen juntos en la misma respuesta, así que pedirlos por separado
    multiplica las consultas contra la plataforma sin traer nada nuevo.

    NO es el expediente completo. El detalle publica más paneles de los que este servidor sabe
    leer: los escritos todavía no están medidos, así que su ausencia acá NO significa que la
    causa no los tenga.

    Cada campo distingue tres estados y hay que respetarlos al informar:

    - NULO: esta competencia no publica ese panel. La pregunta no tiene respuesta acá.
    - Lista vacía: el panel existe y no trae filas. Es una respuesta. `litigantes` y `materias`
      nunca vienen así: una causa sin partes, o laboral sin materia, no existe, y ahí se
      levanta un error en vez de publicar una lista vacía.
    - Con elementos: lo que hay.

    `piezas_exhorto` es el único que no se rige por eso: su panel sólo existe en las causas que
    SON un exhorto, así que cuando viene en nulo hay que mirar `causa_es_exhorto` para saber si
    es porque la causa no lo es o porque la competencia no tiene medida la pregunta.

    Cuidado con dos cosas al computar plazos. `fecha_diligencia` de la historia viene en nulo
    salvo en civil y cobranza, y las notificaciones incluyen las NO practicadas, que se
    distinguen por su `estado`.

    Las liquidaciones NO se suman: la más reciente es la deuda vigente y las anteriores son el
    historial. Sumarlas informa una deuda inflada varias veces.

    Los litigantes traen RUT de personas naturales: son datos personales de terceros.

    Y si `exhortos` trae algo, parte de la tramitación ocurre en OTRO expediente: el exhorto
    abre una causa nueva en el tribunal destino, y las actuaciones de esa parte NO están acá.
    """
    with _cliente() as c:
        return c.detalle_causa(tipo, rol, anio, competencia, tribunal, corte)


#: Las competencias cuyo detalle emite formularios de descarga, y qué rutas emite cada una.
#: Se deriva de la tabla del cliente por la misma razón que `_CON_RECEPTOR` y `_CON_DETALLE`:
#: ofrecerle al modelo una competencia que el cliente rechaza lo hace intentarla y atribuirle
#: el fallo a la plataforma. `penal` no publica ninguna.
_CON_DOCUMENTOS = sorted(DOCUMENTOS)
_RUTAS_POR_COMPETENCIA = "; ".join(
    f"{n} ({', '.join(sorted(DOCUMENTOS[n]))})" for n in _CON_DOCUMENTOS
)

CompetenciaConDocumentos = Annotated[
    str,
    Field(
        description=f"Una de: {', '.join(_CON_DOCUMENTOS)}. Son aquellas cuyo detalle publica "
        "documentos descargables. La competencia elige bajo qué módulo del sitio cuelga la "
        "ruta, así que tiene que ser la MISMA con que se leyó la actuación."
    ),
]
RutaDeDocumento = Annotated[
    str,
    Field(
        description="El campo `documento_ruta` de la actuación, tal cual. Sólo se aceptan las "
        f"rutas que el detalle de cada competencia emite: {_RUTAS_POR_COMPETENCIA}. Una ruta "
        "libre convertiría esto en un proxy contra cualquier página del sitio y por eso se "
        "rechaza.\n\nCuando la actuación trae `documento_ruta` en nulo, el sitio abre ese "
        "documento con un modal de JavaScript y a qué endpoint llama no está medido: ese "
        "documento todavía no se puede pedir, y no hay ruta que inventarle."
    ),
]
ReferenciaDeDocumento = Annotated[
    str,
    Field(
        description="El campo `documento_referencia` de la actuación, tal cual. CADUCA: la "
        "plataforma la emite al dibujar el detalle y no sobrevive a la sesión en que se leyó, "
        "así que una guardada de antes no devuelve 'no existe', devuelve otra cosa. Si la "
        "herramienta responde que lo recibido no es un PDF, volver a pedir el detalle de la "
        "causa y usar la referencia nueva."
    ),
]


def _uri_del_documento(competencia: str, ruta: str, referencia: str) -> str:
    """La dirección con que el cliente puede volver a pedir este mismo documento.

    Lleva los tres datos porque el servidor no guarda nada: leerla vuelve a consultar al Poder
    Judicial, que es lo único compatible con no persistir documentos de terceros.
    """
    return "pjud://documento?" + urlencode(
        {"competencia": competencia, "ruta": ruta, "referencia": referencia}, quote_via=quote
    )


def _resumen(doc: Documento, embebido: bool) -> str:
    """Lo que se dice del documento en palabras, que es lo único que el modelo lee sin gastar
    el contexto entero."""
    if doc.capa_de_texto is None:
        veredicto = (
            f"NO se pudo abrir para saber si trae texto ({doc.problema_al_leer}). Eso NO "
            "significa que sea un escaneo: significa que no se sabe."
        )
    elif doc.capa_de_texto:
        veredicto = "Trae capa de texto, así que es un PDF digital y no una imagen."
    else:
        veredicto = (
            "NO trae capa de texto: es un ESCANEO, o sea una imagen de un documento. Este "
            "servidor no le pasa OCR y no va a hacerlo: una transcripción automática de una "
            "resolución se ve idéntica a la resolución y no lo es. Para leerlo hay que abrirlo."
        )
    paginas = f"{doc.paginas} página(s)" if doc.paginas is not None else "páginas desconocidas"
    entrega = (
        "Viaja completo en esta respuesta."
        if embebido
        else "Viaja como enlace y NO como contenido, porque pasa de "
        f"{LIMITE_EMBEBIDO} bytes. Leerlo con `resources/read` cuesta otra consulta al Poder "
        "Judicial, así que conviene sólo si hace falta el archivo entero."
    )
    return (
        f"Documento de una causa de {doc.competencia}, entregado por {doc.ruta}. "
        f"{doc.tamano_bytes} bytes, {doc.tipo_mime}, {paginas}. {veredicto} {entrega}\n\n"
        "Es un documento de la plataforma, no información oficial validada por este servidor."
    )


@mcp.resource(
    "pjud://documento{?competencia,ruta,referencia}",
    name="documento-de-causa",
    title="Documento de una causa",
    description="Vuelve a pedirle el documento al Poder Judicial y lo entrega. No hay copia "
    "guardada: este servidor no persiste documentos de terceros, así que cada lectura es una "
    "consulta nueva, con su ritmo. La referencia caduca con la sesión en que se leyó.",
    mime_type="application/pdf",
)
def documento_de_causa(competencia: str = "civil", ruta: str = "", referencia: str = "") -> bytes:
    """El otro extremo del `ResourceLink` que devuelve `obtener_documento`.

    Los tres van con valor por defecto porque son variables de consulta de la plantilla, y el
    SDK exige que se puedan omitir: un cliente puede pedir la dirección sin alguna. Cuando eso
    pasa, el cliente rechaza la llamada diciendo qué falta, que es mejor que un valor supuesto.
    """
    with _cliente() as c:
        return c.documento(ruta, referencia, competencia).contenido


@mcp.tool(
    title="Documento de una actuación",
    annotations=SOLO_LECTURA,
    # Devuelve bloques de contenido del protocolo y no un modelo de datos: un esquema de
    # salida armado sobre la unión `ContentBlock` describiría la forma del sobre y no la del
    # documento, que es lo que a nadie le sirve validar.
    structured_output=False,
)
def obtener_documento(
    documento_ruta: RutaDeDocumento,
    documento_referencia: ReferenciaDeDocumento,
    competencia: CompetenciaConDocumentos = "civil",
) -> list[ContentBlock]:
    """El archivo de una actuación: la resolución, el escrito, el certificado o el expediente.

    Los dos primeros parámetros los entrega cada actuación de `obtener_detalle_causa` y de
    `obtener_actuaciones_receptor`, en `documento_ruta` y `documento_referencia`. No hace falta
    el rol: la referencia ya identifica el documento.

    Un documento chico viaja completo en la respuesta. Uno grande viaja como ENLACE, con su
    tamaño, y se lee con `resources/read` sólo si de verdad hace falta: el ebook es el
    expediente entero, y meterlo en la respuesta gasta el contexto de la conversación en algo
    que casi nunca se necesita leer completo.

    Si el PDF resulta ser un ESCANEO se dice y se entrega igual. No se le pasa OCR: una
    transcripción automática de una resolución se ve idéntica a la resolución y no lo es, y
    eso es peor que no entregar nada, porque no se nota.

    Y si lo que llegó no es un PDF, la herramienta falla en vez de entregarlo. Casi siempre
    significa que `documento_referencia` caducó: se vuelve a pedir el detalle de la causa y se
    usa la referencia nueva.
    """
    with _cliente() as c:
        doc = c.documento(documento_ruta, documento_referencia, competencia)

    uri = _uri_del_documento(doc.competencia, doc.ruta, documento_referencia)
    embebido = doc.tamano_bytes <= LIMITE_EMBEBIDO
    if embebido:
        entrega: ContentBlock = EmbeddedResource(
            resource=BlobResourceContents(
                uri=uri,
                mime_type=doc.tipo_mime,
                blob=base64.b64encode(doc.contenido).decode("ascii"),
            )
        )
    else:
        entrega = ResourceLink(
            uri=uri,
            name="documento-de-causa",
            title=f"Documento de {doc.competencia} ({doc.ruta})",
            description=_resumen(doc, embebido=False),
            mime_type=doc.tipo_mime,
            size=doc.tamano_bytes,
        )
    return [TextContent(type="text", text=_resumen(doc, embebido)), entrega]


@mcp.tool(
    title="Buscar jurisprudencia",
    annotations=SOLO_LECTURA,
)
def buscar_jurisprudencia(
    rol: Annotated[
        int | None, Field(description="Rol ante la Corte Suprema, sin el año.", ge=1)
    ] = None,
    anio: Annotated[int | None, Field(description="Año del rol.", ge=1900, le=2100)] = None,
    todas: Annotated[
        str, Field(description="Texto libre: deben aparecer todas estas palabras.")
    ] = "",
    literal: Annotated[str, Field(description="Frase exacta.")] = "",
    excluir: Annotated[str, Field(description="Palabras que NO deben aparecer.")] = "",
    desde: Annotated[str, Field(description="Fecha inicial, DD/MM/AAAA.")] = "",
    hasta: Annotated[str, Field(description="Fecha final, DD/MM/AAAA.")] = "",
    filas: Annotated[
        int, Field(description="Cuántas sentencias traer.", ge=1, le=FILAS_MAXIMAS)
    ] = 10,
    buscador: Annotated[
        str,
        Field(
            description=f"Cuál de los buscadores de fallos consultar. Verificados: "
            f"{', '.join(sorted(BUSCADORES))}. En `laborales` el origen es un juzgado y no "
            "una corte."
        ),
    ] = "suprema",
) -> ResultadoJurisprudencia:
    """Busca sentencias en el Buscador Unificado de Fallos.

    Sirve para verificar que una cita existe antes de usarla: dar `rol` y `anio` devuelve
    la sentencia con su caratulado, sala, fecha y enlace permanente.

    El resultado trae `ocultas`. Si es mayor que cero, la lista es un subconjunto de lo
    que hay indexado y no se puede afirmar que falte lo que no aparece.
    """
    with JurisClient(_contacto()) as c:
        return c.buscar(
            rol=rol,
            anio=anio,
            todas=todas,
            literal=literal,
            excluir=excluir,
            desde=desde,
            hasta=hasta,
            filas=filas,
            buscador=buscador,
        )


@mcp.tool(
    title="Texto completo de una sentencia",
    annotations=SOLO_LECTURA,
)
def obtener_texto_sentencia(
    rol: Annotated[int, Field(description="Rol de la sentencia, sin el año.", ge=1)],
    anio: Annotated[int, Field(description="Año del rol.", ge=1900, le=2100)],
    buscador: Annotated[
        str,
        Field(description=f"Uno de: {', '.join(sorted(BUSCADORES))}."),
    ] = "suprema",
) -> TextoSentencia:
    """El texto completo de una sentencia, de una en una.

    Se pide aparte de la búsqueda y de a una a propósito: una sentencia de trece páginas son
    unos veinticinco mil caracteres. La búsqueda entrega `texto_preview` y la extensión en
    palabras y páginas, que suele bastar para decidir si vale pedir el resto.

    El texto trae los nombres de quienes fueron parte, y cuando el fallo no está anonimizado
    también sus cédulas. `anonimizada` y `fuente` dicen qué versión se entregó. No reproducir
    datos de personas naturales más allá de lo que la respuesta al usuario necesite.
    """
    with JurisClient(_contacto()) as c:
        return c.texto(rol=rol, anio=anio, buscador=buscador)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
