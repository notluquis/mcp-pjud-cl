"""Servidor MCP de solo lectura para la consulta pública de causas.

Proyecto independiente, sin relación alguna con el Poder Judicial de Chile ni con la
Corporación Administrativa del Poder Judicial.
"""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .client import (
    DESCRIPCION,
    INTERVALO_MINIMO,
    MODULOS,
    PAGINAS_MAXIMAS,
    RAFAGA_MAXIMA,
    VERSION,
    PjudClient,
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
from .parser import COMPETENCIAS, Actuacion, CausaEncontrada, Liquidacion, Notificacion

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
Tribunal = Annotated[
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

#: Las competencias cuya tabla de Historia está medida. Se deriva y no se escribe a mano por
#: la misma razón que `_CON_RECEPTOR`: ofrecerle al modelo una que el cliente rechaza lo hace
#: intentarla y atribuir el error a la plataforma.
_CON_HISTORIA = sorted(n for n in MODULOS if COMPETENCIAS[n].historia is not None)
CompetenciaConHistoria = Annotated[
    str,
    Field(
        description=f"Una de: {', '.join(_CON_HISTORIA)}. Son aquellas cuyo panel de historia "
        "está medido contra una respuesta real. Las demás se rechazan antes de consultar, en "
        "vez de leerlas con el mapa de otra competencia."
    ),
]

#: Las competencias cuyo panel de notificaciones está medido. Derivado, como los otros.
_CON_NOTIFICACIONES = sorted(n for n in MODULOS if COMPETENCIAS[n].notificaciones is not None)
CompetenciaConNotificaciones = Annotated[
    str,
    Field(
        description=f"Una de: {', '.join(_CON_NOTIFICACIONES)}. Son aquellas cuyo panel de "
        "notificaciones está medido contra una respuesta real."
    ),
]

#: Las competencias que publican liquidación del crédito. Hoy sólo cobranza.
_CON_LIQUIDACIONES = sorted(n for n in MODULOS if COMPETENCIAS[n].liquidaciones is not None)
CompetenciaConLiquidaciones = Annotated[
    str,
    Field(
        description=f"Una de: {', '.join(_CON_LIQUIDACIONES)}. Es la única que liquida el crédito."
    ),
]

Corte = Annotated[
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
    title="Buscar causa por rol",
    annotations=SOLO_LECTURA,
)
def buscar_causa_por_rit(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: Competencia = "civil",
    tribunal: Tribunal = None,
    corte: Corte = None,
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
    tribunal: Tribunal = None,
    corte: Corte = None,
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
    tribunal: Tribunal = None,
    corte: Corte = None,
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
    tribunal: Tribunal = None,
    corte: Corte = None,
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
    tribunal: Tribunal = None,
    corte: Corte = None,
) -> list[Actuacion]:
    """Actuaciones del ministro de fe con su fecha real de diligencia.

    Es el dato que el ebook oficial de la Oficina Judicial Virtual omite y del que
    dependen los plazos procesales. Devolver `fecha_diligencia`, no `fecha_registro`.
    """
    with _cliente() as c:
        return c.actuaciones_receptor(tipo, rol, anio, competencia, tribunal, corte)


@mcp.tool(
    title="Historia de la causa",
    annotations=SOLO_LECTURA,
)
def obtener_historia_causa(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: CompetenciaConHistoria = "civil",
    tribunal: Tribunal = None,
    corte: Corte = None,
) -> list[Actuacion]:
    """Todas las actuaciones de la causa, no sólo las del ministro de fe.

    Recorre TODOS los cuadernos, no sólo el que la plataforma muestra por defecto.

    Cuatro de las seis competencias no tienen receptor, así que ahí ésta es la única vía
    para saber qué pasó en la causa y cuándo. Cuidado con las fechas: `fecha_diligencia`
    viene en nulo salvo en civil y cobranza, porque las demás no publican la fecha doble.
    Nulo significa que esa competencia no informa la fecha de diligencia, NO que el trámite
    no se haya practicado, y NO sirve para computar plazos.
    """
    with _cliente() as c:
        return c.historia_causa(tipo, rol, anio, competencia, tribunal, corte)


@mcp.tool(
    title="Notificaciones de la causa",
    annotations=SOLO_LECTURA,
)
def obtener_notificaciones_causa(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: CompetenciaConNotificaciones = "civil",
    tribunal: Tribunal = None,
    corte: Corte = None,
) -> list[Notificacion]:
    """Las notificaciones de la causa, practicadas y no practicadas, con sus fechas.

    Incluye los intentos que NO se practicaron, y eso es a propósito: una causa detenida en
    notificación es un dato que importa, y omitir esas filas la haría ver como si avanzara.
    Distinguirlas es obligatorio y se hace con `estado`. Una fila 'Pendiente' no hizo correr
    ningún plazo, y 'enviada' es una carta despachada, que no es lo mismo que notificada.

    Las competencias no publican lo mismo, y eso cambia qué se puede afirmar. Cobranza trae
    la fecha de notificación Y la de trámite por separado, y difieren: una carta midió tres
    días entre una y otra. Civil y laboral traen una sola, la de trámite, así que ahí
    `fecha_notificacion` viaja en NULO. Nulo significa "esta competencia no lo informa", NO
    que coincida con la fecha de trámite: no inventar esa igualdad.

    Una causa puede legítimamente no tener ninguna notificación practicada, así que acá una
    lista vacía sí es una respuesta y no un fallo.
    """
    with _cliente() as c:
        return c.notificaciones_causa(tipo, rol, anio, competencia, tribunal, corte)


@mcp.tool(
    title="Liquidación del crédito",
    annotations=SOLO_LECTURA,
)
def obtener_liquidaciones_causa(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: CompetenciaConLiquidaciones = "cobranza",
    tribunal: Tribunal = None,
    corte: Corte = None,
) -> list[Liquidacion]:
    """Cuánto se debe en un juicio de cobranza y a qué fecha.

    Una causa acumula liquidaciones sucesivas: la medida fue de $4.481.885 en 2019 a
    $24.563.365 en 2022, así que la fecha de cada una importa tanto como el monto. La más
    reciente es la vigente; las anteriores son el historial, no deudas que se sumen.

    `monto` viene en pesos sin separadores, y en NULO si el sitio publicó algo con otra forma.
    Nulo no es cero: cero sería una deuda saldada. `monto_publicado` trae siempre el texto tal
    como aparece en el expediente.
    """
    with _cliente() as c:
        return c.liquidaciones_causa(tipo, rol, anio, competencia, tribunal, corte)


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
