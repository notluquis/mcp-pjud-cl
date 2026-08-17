"""Buscador Unificado de Fallos: consulta de jurisprudencia.

Solo lectura, igual que el resto del proyecto.

Sobre por qué esto vive acá y no en otro paquete: el ritmo de las consultas se le debe a
la institución, no al host. Dos servidores MCP en paralelo serían dos procesos con dos
semáforos, es decir el doble de peticiones contra el mismo Poder Judicial. Por eso
`JurisClient` comparte el transporte de `client.py`, y sólo su sesión es propia.

Sobre lo que el buscador no muestra: una consulta anónima recibe bastante menos de lo que
hay indexado, y el propio sitio dejó de decirlo. Los dos mensajes que lo avisaban siguen
en su JavaScript, comentados::

    // append("(" + diferencia + " sentencias ocultas por limitaciones de visualización
    //         del perfil de usuario)")
    // html("Se ha(n) encontrado " + cantidad_global + " resultado(s), pero sus permisos
    //       de usuario no permiten la visualización de esta(s) sentencia(s).")

Medido el 16-08-2026 sobre el buscador de Corte Suprema, sin filtros: 300.005 visibles de
1.223.925 coincidencias declaradas. Un resultado que no diga eso se lee como el universo
completo, que es el mismo defecto que motivó el resto del proyecto. Por eso la búsqueda no
devuelve una lista pelada sino `ResultadoJurisprudencia`, donde el número de ocultas es un
campo y no una nota al pie.

Cuidado con qué significa esa segunda cifra. Es lo que el buscador declara antes de aplicar
su filtro de condición de publicación, no el tamaño del índice: el Poder Judicial habla
públicamente de más de un millón y medio de sentencias, y esa diferencia no está explicada.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from typing import NamedTuple

import httpx
from pydantic import BaseModel, Field

from .client import INTERVALO_MINIMO, Transporte
from .parser import EstructuraInesperada

BASE = "https://juris.pjud.cl"

#: Sólo Corte Suprema está verificada contra el sistema real. No es prudencia de más: cada
#: buscador declara sus propios campos Solr (`rol_era_sup_s` en Suprema, `rol_era_ape_s` en
#: Apelaciones), así que exponer los otros sin medirlos devolvería campos vacíos en vez de
#: un error, que es la falla que este proyecto existe para no cometer.


class Buscador(NamedTuple):
    """Cómo leer las sentencias de un buscador.

    Mismo criterio que `parser.COMPETENCIAS`: los diez buscadores comparten el endpoint, el
    contrato de la petición y la forma de la respuesta Solr. Lo único que difiere son los
    nombres de los campos, así que esto es una tabla y no diez parsers.

    `campos` mapea nombre del modelo a campo Solr. Los que no aparecen quedan vacíos, salvo
    los indispensables para identificar una cita, que se exigen.
    """

    ruta: str
    campos: Mapping[str, str]


#: Campos que toda sentencia tiene que traer: son los que identifican la cita. Sin ellos se
#: entregaría una sentencia que no dice a qué sentencia corresponde.
INDISPENSABLES = ("rol", "fecha_sentencia")

#: Los campos salen de `parametros_buscador`, que cada página del buscador declara. Confirman
#: la premisa del diseño: Apelaciones identifica sus sentencias con `rol_era_ape_s` y Laborales
#: con `rol_era_sup_s`, así que un cliente que asumiera los campos de Suprema devolvería el rol
#: vacío en Apelaciones sin que nada reviente.
BUSCADORES: Mapping[str, Buscador] = {
    "suprema": Buscador(
        "Corte_Suprema",
        {
            "rol": "rol_era_sup_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            "sala": "gls_sala_sup_s",
            "tipo_recurso": "gls_tip_recurso_sup_s",
            "resultado_recurso": "resultado_recurso_sup_s",
            "corte_origen": "gls_corte_s",
            "rol_corte_apelaciones": "rol_era_ape_s",
            "redactor": "gls_redactor_s",
            "ministros": "sent__gls_int_firma_sup_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
        },
    ),
    "apelaciones": Buscador(
        "Corte_de_Apelaciones",
        {
            # Es el campo que cambia respecto de Suprema, y el que justifica esta tabla.
            "rol": "rol_era_ape_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            "sala": "gls_sala_sup_s",
            "tipo_recurso": "gls_tip_recurso_sup_s",
            "resultado_recurso": "resultado_recurso_sup_s",
            "corte_origen": "gls_corte_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
        },
    ),
    "laborales": Buscador(
        "Laborales",
        {
            "rol": "rol_era_sup_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            # Acá el origen es un juzgado y no una corte, así que la etiqueta cambia de
            # significado aunque el campo del modelo sea el mismo.
            "corte_origen": "gls_juz_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
        },
    ),
}

#: Identificadores que el sitio asigna a cada buscador. Se derivan de la página al abrir
#: sesión y no se hardcodean; esto queda como referencia de lo medido el 17 de agosto de 2026.
IDENTIFICADORES_MEDIDOS = {"suprema": 528, "apelaciones": 168, "laborales": 271}

_TOKEN = re.compile(r'name="_token"\s+value="([^"]+)"')
_ID_BUSCADOR = re.compile(r"id_buscador_activo\s*=\s*(\d+)")

#: Filas por página. Medido contra el sistema real: pedir 250 devuelve 250.
#:
#: Hay una contradicción en el propio sitio que conviene dejar anotada, porque invita a
#: "corregir" esto a la baja: `parametros_buscador` del buscador de Corte Suprema declara
#: `numero_resultados_pagina: "10-20-50"`, pero su desplegable ofrece hasta 250 y el servidor
#: los entrega. Lo declarado es la configuración de la interfaz, no un límite del servidor.
FILAS_MAXIMAS = 250

ORDENES = ("recientes", "antiguos", "rol", "rel")

#: Medido sobre el buscador de Corte Suprema, sin filtros. Estas cifras se citan en la
#: directiva del servidor y en tres páginas de documentación. Viven acá para que haya una sola
#: fuente: `tests/test_documentacion.py` verifica que nadie quede con la cifra vieja, porque
#: una documentación desactualizada se lee con la misma confianza que una al día.
FECHA_MEDICION = "16 de agosto de 2026"
VISIBLES_MEDIDAS = 300_005
INDEXADAS_MEDIDAS = 1_223_925


def miles(n: int) -> str:
    """Formatea con el separador de miles chileno."""
    return f"{n:,}".replace(",", ".")


class Sentencia(BaseModel):
    """Una sentencia del buscador de fallos.

    Metadatos de cita, no el texto completo: una búsqueda de diez sentencias devolvería
    megabytes de texto con nombres y cédulas de personas naturales. El texto se lee
    entrando por `url`.
    """

    rol: str = Field(description="Rol y año ante la Corte Suprema. Ej: 34546-2025.")
    caratulado: str
    fecha_sentencia: date | None = Field(description="Fecha de la sentencia, ISO 8601.")
    sala: str = Field(description="Sala que la dictó.")
    tipo_recurso: str
    resultado_recurso: str
    corte_origen: str = Field(description="Corte de Apelaciones de origen.")
    rol_corte_apelaciones: str = Field(description="Rol ante la corte de origen, si consta.")
    redactor: str
    ministros: list[str] = Field(description="Quienes firmaron.")
    condicion_publicacion: str = Field(
        description="Cómo está publicada. Determina si el texto se ve completo, "
        "anonimizado o no se ve."
    )
    anonimizada: bool = Field(description="Si el texto publicado viene anonimizado.")
    url: str = Field(description="Enlace permanente a la sentencia en el buscador.")


class ResultadoJurisprudencia(BaseModel):
    """Resultado de una búsqueda, con lo que quedó fuera declarado.

    `ocultas` no es una advertencia: es la diferencia entre lo que el buscador dice que
    coincide y lo que una consulta anónima puede ver.
    """

    sentencias: list[Sentencia]
    visibles: int = Field(description="Cuántas coincidencias son visibles para esta consulta.")
    coincidencias: int = Field(
        description="Cuántas coincidencias declara el buscador ANTES de aplicar el filtro de "
        "condición de publicación. No es el tamaño del índice: es el universo del que sale "
        "esta búsqueda."
    )
    ocultas: int = Field(
        description="Coincidencias que existen y NO se entregan. Si es mayor que cero, la "
        "lista es un subconjunto: no se puede afirmar que no exista lo que no aparece."
    )
    condiciones_de_publicacion: dict[str, int] = Field(
        description="Desglose de TODAS las coincidencias por condición de publicación, "
        "visibles incluidas. Suma `coincidencias`, no `ocultas`: la categoría 'Publicable' "
        "son justamente las que sí se entregan. Sirve para ver de qué está hecho el universo "
        "(anonimizadas, reservadas, excluidas de salud), no para saber cuáles faltan: el "
        "buscador no publica la regla de visibilidad, así que no se puede decir qué "
        "categorías componen `ocultas`."
    )


def _fecha(valor: str | None) -> date | None:
    """La respuesta trae ISO 8601. El sitio la reescribe a DD-MM-AAAA para mostrarla; acá
    no, porque quien consume esto es un programa."""
    if not valor:
        return None
    try:
        return date.fromisoformat(valor[:10])
    except ValueError:
        return None


def _lista(valor: str | None) -> list[str]:
    return [p.strip() for p in (valor or "").split(",") if p.strip()]


def parse_sentencias(cuerpo: str, buscador: str = "suprema") -> ResultadoJurisprudencia:
    """Convierte la respuesta del buscador en el modelo. Sin red: se prueba offline.

    Levanta `EstructuraInesperada` en vez de devolver una lista vacía, por la misma razón
    que el resto del proyecto: "no encontré" y "no supe leer" se parecen demasiado, y
    confundirlos hace que una cita inexistente y una cita reservada se informen igual.
    """
    try:
        datos = json.loads(cuerpo)
    except json.JSONDecodeError as e:
        raise EstructuraInesperada(
            f"El buscador de fallos no devolvió JSON: {cuerpo[:200]!r}"
        ) from e

    if "response" not in datos or "docs" not in datos.get("response", {}):
        raise EstructuraInesperada(
            "La respuesta del buscador de fallos no trae 'response.docs'. Cambió el "
            f"formato. Claves recibidas: {sorted(datos)}"
        )

    respuesta = datos["response"]
    condicion = datos.get("condition_pub_sf") or {}
    # Con un valor por defecto, que el campo desaparezca produce `visibles = 0` junto a una
    # lista de sentencias que sí llegó, y `ocultas` pasa a ser una resta contra cero: una
    # cifra inventada con apariencia de medida. Preferible enterarse.
    if "numFound" not in respuesta:
        raise EstructuraInesperada(
            "La respuesta no trae 'response.numFound'. Sin él no se sabe cuántas "
            "coincidencias son visibles, y la cuenta de ocultas saldría del aire."
        )
    visibles = int(respuesta["numFound"])
    # Su propio JS llama a esto `cantidad_global` y calcula la diferencia contra numFound
    # para avisar de las ocultas. Si el campo desaparece no se puede saber cuánto falta, y
    # devolver la lista igual sería afirmar completitud sin fundamento.
    if "numFound_sf" not in condicion:
        raise EstructuraInesperada(
            "La respuesta no trae 'condition_pub_sf.numFound_sf', que es lo único que "
            "permite saber cuántas coincidencias quedaron fuera. Sin ese dato la lista no "
            "se puede presentar como completa."
        )
    coincidencias = int(condicion["numFound_sf"])

    # `counts` viene como lista plana [etiqueta, cantidad, etiqueta, cantidad, ...] y es la
    # partición COMPLETA: sus valores suman `numFound_sf`, no la diferencia con lo visible.
    # Verificado sobre la respuesta real. Presentarlo como "por qué están ocultas" haría leer
    # las 232.021 'Publicable' como retenidas, que es exactamente lo contrario.
    crudo = condicion.get("counts") or []
    condiciones = {
        str(crudo[i]): int(crudo[i + 1])
        for i in range(0, len(crudo) - 1, 2)
        if int(crudo[i + 1]) > 0
    }

    campos = BUSCADORES[buscador.lower()].campos

    # El rol y la fecha son lo que identifica una cita. Si el buscador los renombra, una
    # `Sentencia` con `rol=""` llegaría al usuario como una cita verificada que no dice a qué
    # sentencia corresponde, en una herramienta cuyo propósito es verificar citas.
    for i, d in enumerate(respuesta["docs"], 1):
        faltantes = [campos[c] for c in INDISPENSABLES if not d.get(campos[c])]
        if faltantes:
            raise EstructuraInesperada(
                f"La sentencia {i} de la respuesta no trae {faltantes}, que es lo que la "
                "identifica. El buscador cambió sus campos: devolverla igual sería entregar "
                "una cita que no se puede verificar."
            )

    def leer(d: dict, nombre: str) -> str:
        return str(d.get(campos.get(nombre, ""), "") or "")

    sentencias = [
        Sentencia(
            rol=leer(d, "rol"),
            caratulado=leer(d, "caratulado"),
            fecha_sentencia=_fecha(leer(d, "fecha_sentencia")),
            sala=leer(d, "sala"),
            tipo_recurso=leer(d, "tipo_recurso"),
            resultado_recurso=leer(d, "resultado_recurso"),
            corte_origen=leer(d, "corte_origen"),
            rol_corte_apelaciones=leer(d, "rol_corte_apelaciones"),
            redactor=leer(d, "redactor"),
            ministros=_lista(leer(d, "ministros")),
            condicion_publicacion=leer(d, "condicion_publicacion"),
            anonimizada=bool(d.get(campos.get("anonimizada", ""), 0)),
            url=leer(d, "url"),
        )
        for d in respuesta["docs"]
    ]

    return ResultadoJurisprudencia(
        sentencias=sentencias,
        visibles=visibles,
        coincidencias=coincidencias,
        ocultas=max(0, coincidencias - visibles),
        condiciones_de_publicacion=condiciones,
    )


class JurisClient(Transporte):
    """Buscador Unificado de Fallos.

    Sesión propia: un token CSRF de Laravel y el identificador del buscador, los dos
    derivados de la página al abrir sesión. No se hardcodean, por lo mismo que el prefijo
    de rutas de la Oficina Judicial Virtual: si cambian del lado del servidor, hay que
    enterarse en vez de consultar rutas muertas.
    """

    def __init__(self, contacto: str, intervalo: float = INTERVALO_MINIMO) -> None:
        super().__init__(contacto, intervalo)
        self._token: str | None = None
        self._id_buscador: str | None = None
        #: Qué buscador abrió la sesión. Sin esto, reutilizar el cliente para otro buscador
        #: se saltaba `abrir_sesion` porque el token ya existía, y el POST viajaba con el
        #: `id_buscador` del primero mientras el referer y el parser usaban el segundo: o
        #: resultados de la fuente equivocada, o un error de estructura. Cuando había un solo
        #: buscador expuesto era inofensivo; deja de serlo con el segundo.
        self._buscador_de_la_sesion: str | None = None

    def __enter__(self) -> JurisClient:
        return self

    def abrir_sesion(self, buscador: str = "suprema") -> None:
        buscador = buscador.lower()
        if buscador not in BUSCADORES:
            raise ValueError(
                f"Buscador '{buscador}' no verificado. Disponible: "
                f"{', '.join(sorted(BUSCADORES))}. Los demás declaran otros campos y "
                "devolverían datos vacíos en vez de un error."
            )
        html = self._req("GET", f"{BASE}/busqueda?{BUSCADORES[buscador].ruta}").text

        token = _TOKEN.search(html)
        ident = _ID_BUSCADOR.search(html)
        if not token or not ident:
            raise EstructuraInesperada(
                "No se pudo derivar el token de sesión ni el identificador del buscador "
                f"desde {BASE}/busqueda. El sitio cambió: consultar igual produciría "
                "resultados vacíos indistinguibles de 'no hay jurisprudencia'."
            )
        self._token, self._id_buscador = token.group(1), ident.group(1)
        self._buscador_de_la_sesion = buscador

    def buscar(
        self,
        *,
        rol: int | None = None,
        anio: int | None = None,
        todas: str = "",
        literal: str = "",
        excluir: str = "",
        desde: str = "",
        hasta: str = "",
        filas: int = 10,
        orden: str = "recientes",
        buscador: str = "suprema",
    ) -> ResultadoJurisprudencia:
        """Busca sentencias. Sin ningún criterio devolvería el índice entero, y eso no es
        una búsqueda: es un volcado."""
        if orden not in ORDENES:
            raise ValueError(f"Orden '{orden}' desconocido. Usar una de: {', '.join(ORDENES)}.")
        if not 1 <= filas <= FILAS_MAXIMAS:
            raise ValueError(f"Las filas por página van de 1 a {FILAS_MAXIMAS}.")

        # Sólo se envían las claves con valor. Medido: mandar el juego completo de claves
        # vacías que arma su formulario hace que el servidor responda 500.
        filtros = {
            k: v
            for k, v in {
                "rol": str(rol) if rol else "",
                "era": str(anio) if anio else "",
                "todas": todas,
                "literal": literal,
                "excluir": excluir,
                "fec_desde": desde,
                "fec_hasta": hasta,
            }.items()
            if v
        }
        if not filtros:
            raise ValueError(
                "Hay que dar al menos un criterio: rol y año, texto, o un rango de fechas."
            )

        if buscador.lower() not in BUSCADORES:
            raise ValueError(
                f"Buscador {buscador!r} no verificado. Disponible: {', '.join(sorted(BUSCADORES))}."
            )
        if not self._token or self._buscador_de_la_sesion != buscador.lower():
            self.abrir_sesion(buscador)

        r = self._req(
            "POST",
            f"{BASE}/busqueda/buscar_sentencias",
            files={
                "_token": (None, self._token),
                "id_buscador": (None, self._id_buscador),
                "filtros": (None, json.dumps(filtros, ensure_ascii=False)),
                "numero_filas_paginacion": (None, str(filas)),
                "offset_paginacion": (None, "0"),
                "orden": (None, orden),
                "personalizacion": (None, "false"),
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/busqueda?{BUSCADORES[buscador.lower()].ruta}",
            },
        )
        return parse_sentencias(r.text, buscador)

    def _bloqueo_encubierto(self, r: httpx.Response) -> str | None:
        """El buscador responde JSON. Un cuerpo con verificación en vez de resultados es un
        bloqueo aunque venga con HTTP 200."""
        if "json" in r.headers.get("content-type", ""):
            return None
        cuerpo = r.text[:2000].lower()
        if "recaptcha" in cuerpo and "buscar_sentencias" in str(r.url):
            return "el buscador respondió con una verificación en vez de resultados"
        return None
