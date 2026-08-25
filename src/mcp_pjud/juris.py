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

from .client import INTERVALO_MINIMO, PASO_SESION, Transporte
from .parser import EstructuraInesperada, PlataformaRechaza

BASE = "https://juris.pjud.cl"

#: Diez de los diez buscadores se midieron contra el sistema real y siete se exponen. Los tres
#: que quedan fuera es por decisión y no por falta de medición: penales y el compendio de
#: extranjería publican un dato de una persona en cada fila (el nombre del imputado, la
#: nacionalidad del recurrente), y líneas jurisprudenciales no entrega fallos sino temas, con
#: los mismos campos Solr significando otra cosa. No es prudencia de más:
#: cada buscador declara sus propios campos Solr (`rol_era_sup_s` en Suprema, `rol_era_ape_s` en
#: Apelaciones, `gls_juz_s` donde las otras dos ponen la corte), así que exponer los otros sin
#: medirlos devolvería campos vacíos en vez de un error, que es la falla que este proyecto
#: existe para no cometer.


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
    #: Si `condition_pub_sf.numFound_sf` cuenta la consulta o el corpus entero.
    #:
    #: Medido, y difiere entre buscadores. En Suprema es por consulta: un rol que existe da
    #: 2 y 2, uno imposible da 0 y 0. En Laborales es el corpus: 269.264 en los dos casos,
    #: incluida una consulta sin resultados. Ahí la diferencia contra lo visible no es
    #: "coincidencias reservadas" sino el tamaño del índice, y presentarla como ocultas haría
    #: ver cada resultado como una fracción de un universo oculto que no existe.
    #:
    #: Cuando es falso, `ocultas` viene en nulo en vez de traer un número sin significado. Un
    #: campo que miente es peor que un campo ausente.
    coincidencias_por_consulta: bool


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
            "texto_preview": "texto_sentencia_preview",
            "texto": "texto_sentencia",
            "texto_anonimizado": "texto_sentencia_anon",
        },
        coincidencias_por_consulta=True,
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
            "texto_preview": "texto_sentencia_preview",
            "texto": "texto_sentencia",
            "texto_anonimizado": "texto_sentencia_anon",
        },
        # El buscador quedó verificado el 17 de agosto de 2026: el rol 1504-2019 devolvió tres
        # sentencias en 115,6 s. Los cuatro intentos anteriores se habían dado por muertos por
        # timeout, y el timeout era nuestro.
        #
        # Y la bandera quedó medida el mismo día, comparando un rol que existe contra uno
        # imposible: `numFound_sf` dio 5.290.009 en los dos casos. Es el corpus, así que el
        # falso que ya estaba puesto por prudencia resultó ser el correcto.
        #
        # El campo que decide esto es `condition_pub_sf.numFound_sf` y NO `response.numFound`.
        # El segundo son las visibles, y ésas siguen a la consulta en todos los buscadores
        # medidos, `laborales` incluido: medirlo daría 18 contra 0 y haría concluir "es por
        # consulta" justo donde no lo es.
        coincidencias_por_consulta=False,
    ),
    "laborales": Buscador(
        "Laborales",
        {
            # Medido: el rol que este buscador publica NO lleva la letra del tipo de causa.
            # Pedir el rol 364 del año 2020 devolvió `O-364-2020` cuando lo buscado era
            # `T-364-2020`: son causas distintas y el filtro no las separa. Quien verifique una
            # cita laboral por rol y año tiene que comparar el caratulado, porque una respuesta
            # con el mismo número no prueba que sea la misma causa.
            "rol": "rol_era_sup_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            # Acá el origen es un juzgado y no una corte, así que la etiqueta cambia de
            # significado aunque el campo del modelo sea el mismo.
            "corte_origen": "gls_juz_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
            "texto_preview": "texto_sentencia_preview",
            "texto": "texto_sentencia",
            "texto_anonimizado": "texto_sentencia_anon",
        },
        # Medido: 269.264 tanto para un rol que existe como para uno imposible, o sea es el
        # corpus y no la consulta.
        coincidencias_por_consulta=False,
    ),
    "civiles": Buscador(
        "Civiles",
        {
            # Acá el rol SÍ lleva la letra del tipo de causa: `C-528-2025`. Es al revés que en
            # laborales, y por eso las dos filas no se pueden compartir aunque el campo Solr se
            # llame igual: lo que cambia es qué trae adentro.
            "rol": "rol_era_sup_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            # Como en laborales, el origen es un juzgado y no una corte.
            "corte_origen": "gls_juz_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
            "texto_preview": "texto_sentencia_preview",
            "texto": "texto_sentencia",
            "texto_anonimizado": "texto_sentencia_anon",
        },
        # Medido el 23 de agosto de 2026: 954.129 tanto para una búsqueda de texto con 38.757
        # coincidencias como para un rol imposible con cero. Es el corpus, no la consulta.
        coincidencias_por_consulta=False,
    ),
    "cobranza": Buscador(
        "Cobranza",
        {
            # Como en civiles, el rol trae la letra del libro: `P-34224-2018`.
            "rol": "rol_era_sup_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            "corte_origen": "gls_juz_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
            "texto_preview": "texto_sentencia_preview",
            "texto": "texto_sentencia",
            "texto_anonimizado": "texto_sentencia_anon",
        },
        # Medido el 23 de agosto de 2026: 28.368 para una búsqueda con 1.865 coincidencias y el
        # mismo número para un rol imposible.
        coincidencias_por_consulta=False,
    ),
    "familia": Buscador(
        "Familia",
        {
            # La plataforma anonimiza esta materia por su cuenta: en las tres sentencias
            # medidas el caratulado llega literalmente como `ANONIMIZADO` y la condición de
            # publicación dice "anonimizada". O sea lo que se entrega acá no identifica a las
            # partes, que en familia suelen ser niños.
            "rol": "rol_era_sup_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            "corte_origen": "gls_juz_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
            "texto_preview": "texto_sentencia_preview",
            "texto": "texto_sentencia",
            "texto_anonimizado": "texto_sentencia_anon",
        },
        # Medido el 23 de agosto de 2026: 3.722.878 para una búsqueda con 8.524 coincidencias y
        # el mismo número para un rol imposible.
        coincidencias_por_consulta=False,
    ),
    "salud": Buscador(
        "Salud_CS",
        {
            # El único de los cinco medidos que tiene la forma de suprema y no la de los
            # juzgados: trae corte, sala, tipo de recurso y resultado, más el rol de la causa de
            # apelaciones de la que subió. Es un compendio de la Corte Suprema sobre isapres.
            "rol": "rol_era_sup_s",
            "caratulado": "caratulado_s",
            "fecha_sentencia": "fec_sentencia_sup_dt",
            "sala": "gls_sala_sup_s",
            "tipo_recurso": "gls_tip_recurso_sup_s",
            "resultado_recurso": "resultado_recurso_sup_s",
            "corte_origen": "gls_corte_s",
            "rol_corte_apelaciones": "rol_era_ape_s",
            "condicion_publicacion": "gls_condicion_publicacion_s",
            "anonimizada": "sit_fallo_anonimizado_i",
            "url": "url_acceso_sentencia",
            "texto_preview": "texto_sentencia_preview",
            "texto": "texto_sentencia",
            "texto_anonimizado": "texto_sentencia_anon",
        },
        # Medido el 23 de agosto de 2026: 303 para una búsqueda con 262 coincidencias, el mismo
        # número para un rol imposible. Es el corpus, y acá el corpus entero son 303 sentencias.
        coincidencias_por_consulta=False,
    ),
}

#: Identificadores que el sitio asigna a cada buscador. Se derivan de la página al abrir sesión
#: y NO se hardcodean: esto es la constancia de lo medido, no la fuente de la petición.
#:
#: Existe porque los tres números están escritos en `verificacion`, y un dato repetido a mano es
#: un dato que va a quedar viejo. Un guardia compara la tabla contra esto; sin él la constante
#: era código muerto, que es como estuvo hasta el 22 de agosto de 2026.
IDENTIFICADORES_MEDIDOS = {
    "suprema": 528,
    "apelaciones": 168,
    "laborales": 271,
    "civiles": 328,
    "cobranza": 269,
    "familia": 270,
    "salud": 127,
    # Medido y NO expuesto, por decisión. Va acá igual: esta tabla es la constancia de lo que se
    # midió, y dejarlo fuera obligaría a medirlo de nuevo el día que se decida distinto.
    "penales": 268,
    # Los dos que no son buscadores de fallos ofrecibles, medidos el 23 de agosto de 2026. Van
    # acá por lo mismo que penales: para que nadie tenga que volver a medirlos, y para que la
    # ruta con tilde de extranjería no se pierda. Ver `docs/estado-de-verificacion.yml`.
    "lineas_jurisprudenciales": 628,
    "compendio_extranjeria": 648,
}

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

    rol: str = Field(description="Rol y año en el buscador consultado. Ej: 34546-2025.")
    caratulado: str
    fecha_sentencia: date | None = Field(description="Fecha de la sentencia, ISO 8601.")
    sala: str | None = Field(
        description="Sala que la dictó. NULO: este buscador no publica el campo."
    )
    tipo_recurso: str | None = Field(
        description="Tipo de recurso. NULO: este buscador no publica el campo."
    )
    resultado_recurso: str | None = Field(
        description="Cómo se resolvió. NULO: este buscador no publica el campo."
    )
    corte_origen: str = Field(description="Corte de Apelaciones de origen.")
    rol_corte_apelaciones: str | None = Field(
        description="Rol ante la corte de origen. NULO: este buscador no publica el campo; "
        "vacío: lo publica y esta sentencia no lo trae."
    )
    redactor: str | None = Field(
        description="Quien redactó. NULO: este buscador no publica el campo."
    )
    ministros: list[str] | None = Field(
        description="Quienes firmaron. NULO: este buscador no publica el campo. Una lista "
        "VACÍA diría que no firmó nadie, y eso no lo dice ningún buscador."
    )
    condicion_publicacion: str = Field(
        description="Cómo está publicada. Determina si el texto se ve completo, "
        "anonimizado o no se ve."
    )
    anonimizada: bool = Field(description="Si el texto publicado viene anonimizado.")
    url: str = Field(description="Enlace permanente a la sentencia en el buscador.")
    palabras: int | None = Field(
        default=None, description="Extensión del fallo en palabras, según el buscador."
    )
    paginas: int | None = Field(default=None, description="Extensión en páginas.")
    texto_preview: str = Field(
        default="",
        description="Primeras líneas del fallo, tal como el buscador las entrega para la "
        "lista de resultados. Sirve para decidir si vale pedir el texto completo, que es dos "
        "órdenes de magnitud más grande.",
    )


class TextoSentencia(BaseModel):
    """El texto completo de una sentencia.

    Va en un modelo aparte y se pide de una en una a propósito: una sentencia de trece
    páginas son unos veinticinco mil caracteres, así que devolver diez con la búsqueda serían
    doscientos cincuenta mil. El costo no es sólo de tamaño: el texto trae nombres y cédulas
    de las personas que fueron parte, y pedirlo tiene que ser una decisión explícita y no el
    efecto colateral de una búsqueda.
    """

    rol: str
    anonimizada: bool = Field(
        description="Si lo que se entrega es la versión anonimizada. Cuando es verdadero, los "
        "datos de las personas naturales vienen suprimidos por el propio tribunal."
    )
    fuente: str = Field(
        description="Cuál de los dos campos del buscador se entregó: `texto_sentencia` o "
        "`texto_sentencia_anon`. Se dice para que quien lo lea sepa qué está leyendo."
    )
    palabras: int | None = None
    paginas: int | None = None
    texto: str


class ResultadoJurisprudencia(BaseModel):
    """Resultado de una búsqueda, con lo que quedó fuera declarado.

    `ocultas` no es una advertencia: es la diferencia entre lo que el buscador dice que
    coincide y lo que una consulta anónima puede ver.
    """

    sentencias: list[Sentencia]
    visibles: int = Field(description="Cuántas coincidencias son visibles para esta consulta.")
    coincidencias: int | None = Field(
        description="Cuántas coincidencias declara el buscador ANTES de aplicar el filtro de "
        "condición de publicación. Nulo cuando ese número, en este buscador, cuenta el corpus "
        "entero y no la consulta: informarlo entonces sería dar por medido algo que no lo es."
    )
    ocultas: int | None = Field(
        description="Coincidencias que existen y NO se entregan. Si es mayor que cero, la "
        "lista es un subconjunto: no se puede afirmar que no exista lo que no aparece.\n\n"
        "NULO significa que en este buscador no se puede saber, porque el número que la "
        "plataforma entrega cuenta el índice completo. Nulo NO significa cero: significa que "
        "la pregunta no tiene respuesta acá, y un resultado sin coincidencias puede igual "
        "corresponder a algo reservado."
    )
    desplazamiento: int = Field(
        default=0,
        description="Desde qué coincidencia empieza esta página. Cero es la primera.\n\n"
        "Sirve para pedir la siguiente: `desplazamiento + filas`. Medido el 22 de agosto de "
        "2026: pedir más allá de `visibles` devuelve una página VACÍA con 200, no un error.",
    )
    no_entregadas: int = Field(
        description="Coincidencias visibles que esta llamada NO trajo: las que quedan DESPUÉS "
        "de esta página, contando desde `desplazamiento`. Si es mayor que cero, la lista es un "
        "subconjunto de lo visible y se puede pedir el resto.\n\n"
        "Es distinto de `ocultas`, y hay que mirar los dos: `ocultas` son las que la "
        "plataforma reserva, `no_entregadas` son las que sí se podrían ver y no se pidieron. "
        "Un resultado con `ocultas` en cero puede igual estar recortado."
    )
    condiciones_de_publicacion: dict[str, int] | None = Field(
        description="Desglose de TODAS las coincidencias por condición de publicación, "
        "visibles incluidas. Suma `coincidencias`, no `ocultas`: la categoría 'Publicable' "
        "son justamente las que sí se entregan. Sirve para ver de qué está hecho el universo "
        "(anonimizadas, reservadas, excluidas de salud), no para saber cuáles faltan: el "
        "buscador no publica la regla de visibilidad, así que no se puede decir qué "
        "categorías componen `ocultas`.\n\nNULO donde ese desglose cuenta el índice completo y "
        "no la consulta, que son los mismos buscadores en que `coincidencias` viene en nulo: "
        "ahí sumaría millones para una búsqueda de decenas."
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


def buscadores_que_publican(campo: str) -> list[str]:
    """Quiénes declaran ese campo Solr, leído del mapa de cada buscador.

    Única fuente de qué publica cada uno: la prosa que lo repita se compara contra esto en vez
    de escribirse a mano, porque un buscador nuevo la dejaría vieja sin que nada avise.
    """
    return sorted(n for n, b in BUSCADORES.items() if campo in b.campos)


def _lista(valor: str | None) -> list[str]:
    return [p.strip() for p in (valor or "").split(",") if p.strip()]


def parse_sentencias(
    cuerpo: str, buscador: str = "suprema", desplazamiento: int = 0
) -> ResultadoJurisprudencia:
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
    # Sólo se informa cuando está medido que cuenta la consulta. Ver `Buscador`.
    por_consulta = BUSCADORES[buscador.lower()].coincidencias_por_consulta
    coincidencias = int(condicion["numFound_sf"]) if por_consulta else None

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

    def leer_si_lo_declara(d: dict, nombre: str) -> str | None:
        """Nulo cuando ESTE buscador no publica el campo, cadena cuando lo publica.

        `leer` colapsaba las dos cosas: sin entrada en `campos` hacía `d.get("", "")` y
        devolvía la cadena vacía, que se lee como "consta que está vacío". Medido: seis de los
        siete buscadores no declaran `ministros` y llegaba como lista vacía mientras el texto
        del fallo nombraba a los cinco de la sala. El mapa del buscador es la única fuente de
        qué publica cada uno, y es la que decide.
        """
        return leer(d, nombre) if nombre in campos else None

    sentencias = [
        Sentencia(
            rol=leer(d, "rol"),
            caratulado=leer(d, "caratulado"),
            fecha_sentencia=_fecha(leer(d, "fecha_sentencia")),
            sala=leer_si_lo_declara(d, "sala"),
            tipo_recurso=leer_si_lo_declara(d, "tipo_recurso"),
            resultado_recurso=leer_si_lo_declara(d, "resultado_recurso"),
            corte_origen=leer(d, "corte_origen"),
            rol_corte_apelaciones=leer_si_lo_declara(d, "rol_corte_apelaciones"),
            redactor=leer_si_lo_declara(d, "redactor"),
            ministros=_lista(leer(d, "ministros")) if "ministros" in campos else None,
            condicion_publicacion=leer(d, "condicion_publicacion"),
            anonimizada=bool(d.get(campos.get("anonimizada", ""), 0)),
            url=leer(d, "url"),
            palabras=d.get("sent__word_count_i"),
            paginas=d.get("sent__npages_i"),
            texto_preview=leer(d, "texto_preview"),
        )
        for d in respuesta["docs"]
    ]

    # El total no puede ser menor que la página que lo acompaña. Si lo es, el `max(0, ...)`
    # de abajo publicaría `no_entregadas` en cero, o sea leería una respuesta contradictoria
    # como una lista completa: exactamente el falso negativo que el campo vino a cerrar.
    if visibles < len(sentencias):
        raise EstructuraInesperada(
            f"La respuesta declara {visibles} coincidencias visibles y trae "
            f"{len(sentencias)} sentencias. Un total menor que su propia página significa "
            "que la respuesta dejó de cumplir el contrato, no que no falte nada."
        )

    return ResultadoJurisprudencia(
        sentencias=sentencias,
        visibles=visibles,
        coincidencias=coincidencias,
        ocultas=max(0, coincidencias - visibles) if coincidencias is not None else None,
        desplazamiento=desplazamiento,
        # Se resta acá y no se deja al lector: `ocultas` ya sienta esa convención, y sólo
        # `suprema` la trae con número, así que ésta es la única señal de recorte que funciona
        # en todos los buscadores.
        #
        # El desplazamiento entra en la resta desde que la paginación existe. Sin él, la
        # segunda página de una búsqueda de 59.819 declararía casi todas las visibles como no
        # entregadas, o sea diría que falta lo que ya se entregó en la página anterior.
        no_entregadas=max(0, visibles - desplazamiento - len(sentencias)),
        # NULO donde el desglose cuenta el índice entero y no la consulta, por lo mismo que
        # `ocultas` y `coincidencias`: medido el 25 de agosto de 2026, en suprema suma 2 para
        # una consulta de 2, y en apelaciones suma 5.295.308 con 28 visibles. Entregarlo ahí
        # con la descripción que tiene diría que la consulta coincidió con cinco millones.
        condiciones_de_publicacion=condiciones if por_consulta else None,
    )


#: Cuántas sentencias se enumeran como mucho al pedir que se elija una. Es un tope de
#: mensaje, no de la plataforma: cada documento que se trae para enumerar arrastra su texto
#: completo, y lo que falta se dice en vez de callarse.
TOPE_AL_ENUMERAR = 10

#: El caso medido de un rol con más de una sentencia, que es lo que justifica que esta
#: herramienta se detenga en vez de elegir. Vive acá y no sólo en la prosa porque la
#: referencia lo cita y `tests/test_documentacion.py` compara las dos.
ROL_CON_DOS_SENTENCIAS = "1933-2025"

#: Y el que trae TRES, medido el 17 de agosto de 2026 en el buscador de apelaciones. Que no
#: siempre sean dos es lo que obliga a enumerar de verdad en vez de listar un par.
ROL_CON_TRES_SENTENCIAS = "1504-2019"
PALABRAS_DE_LA_CASACION = 3646
PALABRAS_DEL_REEMPLAZO = 157

#: Y en qué POSICIÓN las devuelve el buscador, medido sobre `ROL_CON_DOS_SENTENCIAS`: la de
#: casación, que es la que trae el razonamiento, no es la primera.
#:
#: Importa porque la prosa las nombra en el orden contrario ("la de casación con el
#: razonamiento y la de reemplazo, que confirma en una línea"), y quien elige por el orden en
#: que lo leyó pide `cual=1` y se lleva las `PALABRAS_DEL_REEMPLAZO`: una línea que confirma,
#: sin la doctrina que se fue a buscar, y con cara de ser la sentencia del rol. Pasó.
#:
#: Es UNA medición sobre un rol, así que lo que se afirma es que la casación no es la 1, no
#: que siempre sea la 2. El número que vale es el de la enumeración de la detención.
CUAL_DE_LA_CASACION_MEDIDO = 2


def _es_del_rol(sentencia: Sentencia, rol: int, anio: int) -> bool:
    """Si la sentencia que llegó corresponde al rol que se pidió.

    El buscador publica el rol como texto y no siempre con el mismo formato, así que se
    comparan sus dígitos: lo que se quiere descartar es haber recibido OTRA causa, no una
    diferencia de puntuación.
    """
    digitos = re.sub(r"\D", "", sentencia.rol or "")
    return digitos == f"{rol}{anio}"


def _enumerar(sentencias: list[Sentencia]) -> str:
    """Las opciones como las lee quien tiene que elegir una.

    Va el rol y el caratulado además del rótulo: en `laborales` el mapeo no declara
    `resultado_recurso` ni `tipo_recurso`, así que sin ellos las opciones salían todas como
    "sin rótulo" y sólo se distinguían por el largo. Y ahí el propio buscador mezcla causas
    distintas con el mismo número (`T-364-2020` contra `O-364-2020`), que es justo lo que el
    caratulado separa.

    Y la FECHA, porque el caratulado tampoco siempre distingue: en `familia` llega como
    `ANONIMIZADO` y ese buscador tampoco declara tipo ni resultado, así que sin la fecha las
    opciones quedaban en el mismo rol, el mismo caratulado y un número de palabras. El rol y
    la fecha son lo que identifica una cita, que es lo que se vino a verificar.
    """
    # La extensión sólo entra si la hay: sin ella el rótulo decía "None palabras", y decía
    # eso justamente en apelaciones, que no publica la extensión y es donde más sentencias
    # comparten rol (medido: trece bajo 2476-2023). O sea el mensaje que existe para que se
    # elija entre varias salía roto en el buscador donde más se usa.
    return "; ".join(
        f"{i}: {s.rol or 'sin rol'} del {s.fecha_sentencia or 'sin fecha'},"
        f" {s.caratulado or 'sin caratulado'}"
        f" [{s.resultado_recurso or s.tipo_recurso or 'sin rótulo'}"
        + (f", {s.palabras} palabras]" if s.palabras is not None else "]")
        for i, s in enumerate(sentencias, 1)
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
        #: Cuerpo de la última respuesta. Lo guarda para que `texto` pueda releer el campo
        #: del fallo completo sin repetir la petición.
        self._ultima_respuesta: str | None = None

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
        html = self._req(
            "GET", f"{BASE}/busqueda?{BUSCADORES[buscador].ruta}", paso=PASO_SESION
        ).text

        token = _TOKEN.search(html)
        ident = _ID_BUSCADOR.search(html)
        if not token or not ident:
            raise EstructuraInesperada(
                "No se pudo derivar el token de sesión ni el identificador del buscador "
                f"desde {BASE}/busqueda. El sitio cambió: consultar igual produciría "
                "resultados vacíos indistinguibles de 'no hay jurisprudencia'."
            )
        # El identificador que la página entrega tiene que ser el que se midió para ESTE
        # buscador. No es paranoia: el 23 de agosto de 2026, pedir una ruta que no existe
        # (`Compendio_Extranjeria`) devolvió 200 con la página de OTRO buscador, con su
        # identificador y sus campos, y las búsquedas siguientes contestaron su corpus.
        #
        # Sin esta comprobación eso es indistinguible de haber consultado el buscador pedido:
        # la respuesta tiene la forma correcta y los resultados son de otra cosa.
        # Comparados como enteros: el patrón sólo captura dígitos, y si el sitio empezara a
        # rellenar con ceros (`0269`) la comparación de cadenas diría que cambió el buscador
        # cuando es el mismo. Un guardia que salta por el formato deja de decir algo del dato.
        medido = IDENTIFICADORES_MEDIDOS.get(buscador)
        if medido is not None and int(ident.group(1)) != medido:
            raise EstructuraInesperada(
                f"La página de {buscador!r} entregó el identificador {ident.group(1)} y lo "
                f"medido es {medido}. O el sitio reasignó los identificadores, o esa ruta está "
                "sirviendo la página de otro buscador, que responde con su corpus y no con el "
                "que se pidió."
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
        desplazamiento: int = 0,
    ) -> ResultadoJurisprudencia:
        """Busca sentencias. Sin ningún criterio devolvería el índice entero, y eso no es
        una búsqueda: es un volcado.

        `desplazamiento` es desde qué coincidencia empieza la página. Medido el 22 de agosto de
        2026 contra el buscador de Corte Suprema: con 0, 10 y 250 devuelve tres páginas SIN una
        sola sentencia repetida, así que la coincidencia 251 sí se alcanza. Pedir más allá de
        `visibles` devuelve una página vacía con 200, no un error.
        """
        if orden not in ORDENES:
            raise ValueError(f"Orden '{orden}' desconocido. Usar una de: {', '.join(ORDENES)}.")
        if not 1 <= filas <= FILAS_MAXIMAS:
            raise ValueError(f"Las filas por página van de 1 a {FILAS_MAXIMAS}.")
        if desplazamiento < 0:
            raise ValueError("El desplazamiento no puede ser negativo.")

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

        self._ultima_respuesta = self._req(
            "POST",
            f"{BASE}/busqueda/buscar_sentencias",
            # El buscador tarda minutos con una consulta amplia, y el aviso es lo único que
            # distingue eso de un cuelgue mientras se espera. La frase no nombra qué se busca:
            # el texto libre lo escribe quien consulta y puede traer el nombre de una parte.
            paso="buscando sentencias",
            files={
                "_token": (None, self._token),
                "id_buscador": (None, self._id_buscador),
                "filtros": (None, json.dumps(filtros, ensure_ascii=False)),
                "numero_filas_paginacion": (None, str(filas)),
                "offset_paginacion": (None, str(desplazamiento)),
                "orden": (None, orden),
                "personalizacion": (None, "false"),
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/busqueda?{BUSCADORES[buscador.lower()].ruta}",
            },
        ).text
        return parse_sentencias(self._ultima_respuesta, buscador, desplazamiento)

    def texto(
        self, *, rol: int, anio: int, buscador: str = "suprema", cual: int | None = None
    ) -> TextoSentencia:
        """El texto completo de una sentencia, de una en una.

        Se resuelve con la misma búsqueda por rol y año: el buscador ya devuelve el texto en
        la respuesta del listado, así que no hace falta una petición aparte. Lo que cambia
        respecto de `buscar` es qué se entrega, no cuántas veces se consulta.

        Cuando el fallo está anonimizado, lo publicado es la versión con los datos de las
        personas naturales suprimidos por el propio tribunal, y se dice cuál de los dos
        campos se entregó.
        """
        if cual is not None and cual < 1:
            # `JurisClient` se usa también sin pasar por el protocolo, donde el esquema ya
            # exige `ge=1`. Sin esta comprobación, `cual=0` entregaba en silencio la primera
            # (el `or` lo convertía en 1) y `cual=-1` indexaba desde el final: el selector
            # volvía a elegir un fallo por su cuenta, que es lo que existe para no hacer.
            raise ValueError(f"`cual` empieza en 1 y se pidió {cual}.")

        # Con `cual`, se pide UNA fila desplazada hasta ella. Pedir `filas=cual` traería
        # también todas las anteriores con su texto completo, y una sentencia de trece páginas
        # son veinticinco mil caracteres: con un índice alto eso son megabytes descargados para
        # devolver uno, justo en la herramienta que existe para pedirlos de a uno.
        #
        # Sin `cual`, dos filas: alcanzan para DETECTAR que hay más de una sin arrastrar de más.
        if cual is None:
            r = self.buscar(rol=rol, anio=anio, filas=2, buscador=buscador)
        else:
            r = self.buscar(rol=rol, anio=anio, filas=1, desplazamiento=cual - 1, buscador=buscador)
            # `cual` es una POSICIÓN dentro del orden que la búsqueda devuelve, y entre la
            # enumeración y esta llamada ese orden podría cambiar (una sentencia nueva del
            # mismo rol, o dos empatadas por fecha que se ordenen al revés). Lo que sí se
            # comprueba es que lo que llegó siga siendo del rol pedido: sin identificador
            # estable medido en este buscador, no hay con qué comprobar más, y construir la
            # selección sobre la clave del `url` sería suponer que dura, que no está medido.
            if r.sentencias and not _es_del_rol(r.sentencias[0], rol, anio):
                raise EstructuraInesperada(
                    f"Se pidió la sentencia {cual} del rol {rol}-{anio} y llegó "
                    f"{r.sentencias[0].rol!r}: el listado cambió entre una consulta y otra, o "
                    "el buscador dejó de ordenarlas igual. No se entrega, porque una sentencia "
                    "de otro rol se lee como la que se fue a verificar."
                )
            if not r.sentencias and r.visibles:
                # La página vacía por pasarse del final NO es "la sentencia no existe": el rol
                # está y el índice se fue de rango. Se separa antes de llegar a la rama de
                # abajo, que diría que no aparece ninguna.
                raise ValueError(
                    f"Se pidió la sentencia número {cual} del rol {rol}-{anio} y el buscador "
                    f"entrega {r.visibles}."
                )
        if not r.sentencias:
            if r.ocultas:
                raise PlataformaRechaza(
                    f"La sentencia {rol}-{anio} existe en el índice pero no se entrega a una "
                    f"consulta anónima: {r.ocultas} coincidencia(s) reservada(s). No es que no "
                    "exista, es que no se publica."
                )
            if r.ocultas is None:
                raise EstructuraInesperada(
                    f"No aparece ninguna sentencia {rol}-{anio} en el buscador de {buscador}, "
                    "y en este buscador NO se puede saber si existe reservada: el número que "
                    "la plataforma entrega cuenta el índice completo. O sea esto no prueba que "
                    "la sentencia no exista."
                )
            raise EstructuraInesperada(
                f"No hay ninguna sentencia {rol}-{anio} en el buscador de {buscador}, ni "
                "reservada. El rol puede estar equivocado o pertenecer a otro buscador."
            )

        # Más de una bajo el mismo rol: NO se elige. La ambigüedad se decide por `visibles`,
        # que es lo que la plataforma DECLARA, y no por cuántas filas llegaron: una respuesta
        # que declare tres y traiga una (truncada, o el contrato cambió) dejaba pasar la misma
        # elección silenciosa que esto existe para cerrar.
        #
        # Y una reservada cuenta: en suprema, donde `ocultas` corresponde a la consulta, una
        # visible más una reservada da `visibles == 1` y entregarla la haría pasar por la
        # única del rol. Si la cita que se fue a verificar es la reservada, se devuelve otro
        # fallo del mismo rol, verosímil y distinto.
        if cual is None and r.visibles + (r.ocultas or 0) > 1:
            # Se vuelve a pedir con todas para poder ENUMERARLAS, y ANTES de decidir por qué
            # se detiene: con reservadas el mensaje también las enumera, y hacerlo después
            # dejaba ese camino listando las dos filas que se habían traído para detectar la
            # ambigüedad. Sin esto, un rol de tres (medido: 1504-2019 en apelaciones) decía
            # "tiene 3" y listaba dos. Es una petición más y sólo ocurre en el caso ambiguo.
            if r.visibles > len(r.sentencias):
                r = self.buscar(
                    rol=rol, anio=anio, filas=min(r.visibles, TOPE_AL_ENUMERAR), buscador=buscador
                )
            if len(r.sentencias) < min(r.visibles, TOPE_AL_ENUMERAR):
                # Se pidieron y no llegaron. Va ANTES de decidir por qué se detiene: el
                # relleno también puede volver truncado, y entonces cualquiera de los dos
                # mensajes de abajo enumeraría una página parcial, o sea volvería a obligar a
                # elegir sin ver todas las alternativas.
                raise EstructuraInesperada(
                    f"El rol {rol}-{anio} declara {r.visibles} sentencias en {buscador} y la "
                    f"respuesta trajo {len(r.sentencias)}: no se pueden enumerar para que se "
                    "elija una, y devolver la que llegó la haría pasar por la única."
                )
            if r.ocultas:
                raise PlataformaRechaza(
                    f"El rol {rol}-{anio} tiene {r.visibles} sentencia(s) que se pueden ver y "
                    f"{r.ocultas} reservada(s) a una consulta anónima. No se entrega ninguna "
                    "sin decir cuál en `cual`: la que falta puede ser justamente la que se "
                    "busca, y las visibles son "
                    f"{_enumerar(r.sentencias)}."
                )
            faltan = max(0, r.visibles - len(r.sentencias))
            raise ValueError(
                f"El rol {rol}-{anio} tiene {r.visibles} sentencias en {buscador} y esta "
                f"herramienta entrega una: hay que decir cuál en `cual`. Son: "
                f"{_enumerar(r.sentencias)}"
                + (f" (y {faltan} más, que no caben en este mensaje)" if faltan else "")
                + ". No se elige por ti: en suprema está medido que un rol trae la casación "
                "con el razonamiento y la de reemplazo que confirma en una línea, y la "
                "equivocada se ve igual de válida."
            )

        # Siempre la primera de la página: sin `cual` es la única que hay, y con `cual` la
        # página ya viene desplazada hasta ella.
        indice = 0

        # El texto viene en la misma respuesta del listado, así que no hace falta otra
        # petición: se relee el cuerpo que `buscar` acaba de traer. `Sentencia` no lo lleva a
        # propósito, para que una búsqueda no arrastre veinticinco mil caracteres por fila.
        campos = BUSCADORES[buscador.lower()].campos
        docs = json.loads(self._ultima_respuesta or "{}").get("response", {}).get("docs", [])
        crudo = docs[indice] if len(docs) > indice else {}
        s = r.sentencias[indice]
        anon = s.anonimizada
        clave = campos["texto_anonimizado"] if anon else campos["texto"]
        texto = str(crudo.get(clave, "") or "")
        if not texto:
            raise EstructuraInesperada(
                f"La sentencia {rol}-{anio} llegó sin el campo {clave!r}, que es donde el "
                "buscador publica su texto. Devolver una cadena vacía se leería como una "
                "sentencia sin contenido."
            )
        return TextoSentencia(
            rol=s.rol,
            anonimizada=anon,
            fuente=clave,
            palabras=s.palabras,
            paginas=s.paginas,
            texto=texto,
        )

    def _bloqueo_encubierto(self, r: httpx.Response) -> str | None:
        """El buscador responde JSON. Un cuerpo con verificación en vez de resultados es un
        bloqueo aunque venga con HTTP 200."""
        if "json" in r.headers.get("content-type", ""):
            return None
        cuerpo = r.text[:2000].lower()
        if "recaptcha" in cuerpo and "buscar_sentencias" in str(r.url):
            return "el buscador respondió con una verificación en vez de resultados"
        return None
