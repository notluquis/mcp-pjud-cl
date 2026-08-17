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
    COMPETENCIAS,
    INTERVALO_MINIMO,
    PAGINAS_MAXIMAS,
    RAFAGA_MAXIMA,
    PjudClient,
)
from .juris import (
    FECHA_MEDICION,
    FILAS_MAXIMAS,
    INDEXADAS_MEDIDAS,
    VISIBLES_MEDIDAS,
    JurisClient,
    ResultadoJurisprudencia,
    miles,
)
from .parser import Actuacion, CausaEncontrada

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

mcp = MCPServer("mcp-pjud", instructions=DIRECTIVA)

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


Tipo = Annotated[str, Field(description="Letra del rol. En civil: C, V, E, A, F o I.")]
Rol = Annotated[int, Field(description="Número del rol, sin la letra ni el año.", ge=1)]
Anio = Annotated[int, Field(description="Año del rol, cuatro dígitos.", ge=1900, le=2100)]
Competencia = Annotated[str, Field(description=f"Una de: {', '.join(sorted(COMPETENCIAS))}.")]
Tribunal = Annotated[
    int | None, Field(description="Código del tribunal. Omitir para buscar en todos.")
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
Corte = Annotated[
    int | None,
    Field(
        description="Código de la corte. OMITIR salvo certeza: fijarla produce falsos "
        "negativos, porque excluye causas radicadas en otra jurisdicción."
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
    Exige además indicar el tribunal: la plataforma no permite buscar por nombre en todos
    los tribunales a la vez.
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
    "Mis Causas". Exige indicar el tribunal.
    """
    with _cliente() as c:
        return c.buscar_por_rut_juridica(
            rut, digito_verificador, anio, competencia, tribunal, corte, paginas
        )


@mcp.tool(
    title="Actuaciones del receptor",
    annotations=SOLO_LECTURA,
)
def obtener_actuaciones_receptor(
    tipo: Tipo,
    rol: Rol,
    anio: Anio,
    competencia: Competencia = "civil",
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
) -> ResultadoJurisprudencia:
    """Busca sentencias de la Corte Suprema en el Buscador Unificado de Fallos.

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
        )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
