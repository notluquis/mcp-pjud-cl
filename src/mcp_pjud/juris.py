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
1.223.925 indexadas. Un resultado que no diga eso se lee como el universo completo, que es
el mismo defecto que motivó el resto del proyecto. Por eso la búsqueda no devuelve una
lista pelada sino `ResultadoJurisprudencia`, donde el número de ocultas es un campo y no
una nota al pie.
"""

from __future__ import annotations

import json
import re
from datetime import date

import httpx
from pydantic import BaseModel, Field

from .client import INTERVALO_MINIMO, Transporte
from .parser import EstructuraInesperada

BASE = "https://juris.pjud.cl"

#: Sólo Corte Suprema está verificada contra el sistema real. No es prudencia de más: cada
#: buscador declara sus propios campos Solr (`rol_era_sup_s` en Suprema, `rol_era_ape_s` en
#: Apelaciones), así que exponer los otros sin medirlos devolvería campos vacíos en vez de
#: un error, que es la falla que este proyecto existe para no cometer.
BUSCADORES = {"suprema": "Corte_Suprema"}

_TOKEN = re.compile(r'name="_token"\s+value="([^"]+)"')
_ID_BUSCADOR = re.compile(r"id_buscador_activo\s*=\s*(\d+)")

#: Filas por página que ofrece el buscador. Pedir más de lo que ofrece su propio control
#: sería empujarlo fuera de su uso normal.
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

    `ocultas` no es una advertencia: es la diferencia entre lo que el índice tiene y lo que
    una consulta anónima puede ver.
    """

    sentencias: list[Sentencia]
    visibles: int = Field(description="Cuántas coincidencias son visibles para esta consulta.")
    coincidencias: int = Field(description="Cuántas hay en el índice, visibles o no.")
    ocultas: int = Field(
        description="Coincidencias que existen y NO se entregan. Si es mayor que cero, la "
        "lista es un subconjunto: no se puede afirmar que no exista lo que no aparece."
    )
    motivos_de_reserva: dict[str, int] = Field(
        description="Por qué están ocultas, según la condición de publicación que declara "
        "el propio buscador. Ej: 'Anonimizadas', 'Reservado restringido'."
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


def parse_sentencias(cuerpo: str) -> ResultadoJurisprudencia:
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
    visibles = int(respuesta.get("numFound", 0))
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

    # `counts` viene como lista plana [etiqueta, cantidad, etiqueta, cantidad, ...]
    crudo = condicion.get("counts") or []
    motivos = {
        str(crudo[i]): int(crudo[i + 1])
        for i in range(0, len(crudo) - 1, 2)
        if int(crudo[i + 1]) > 0
    }

    sentencias = [
        Sentencia(
            rol=d.get("rol_era_sup_s", ""),
            caratulado=d.get("caratulado_s", ""),
            fecha_sentencia=_fecha(d.get("fec_sentencia_sup_dt")),
            sala=d.get("gls_sala_sup_s", ""),
            tipo_recurso=d.get("gls_tip_recurso_sup_s", ""),
            resultado_recurso=d.get("resultado_recurso_sup_s", ""),
            corte_origen=d.get("gls_corte_s", ""),
            rol_corte_apelaciones=d.get("rol_era_ape_s", ""),
            redactor=d.get("gls_redactor_s", ""),
            ministros=_lista(d.get("sent__gls_int_firma_sup_s")),
            condicion_publicacion=d.get("gls_condicion_publicacion_s", ""),
            anonimizada=bool(d.get("sit_fallo_anonimizado_i", 0)),
            url=d.get("url_acceso_sentencia", ""),
        )
        for d in respuesta["docs"]
    ]

    return ResultadoJurisprudencia(
        sentencias=sentencias,
        visibles=visibles,
        coincidencias=coincidencias,
        ocultas=max(0, coincidencias - visibles),
        motivos_de_reserva=motivos,
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

    def __enter__(self) -> JurisClient:
        return self

    def abrir_sesion(self, buscador: str = "suprema") -> None:
        if buscador not in BUSCADORES:
            raise ValueError(
                f"Buscador '{buscador}' no verificado. Disponible: "
                f"{', '.join(sorted(BUSCADORES))}. Los demás declaran otros campos y "
                "devolverían datos vacíos en vez de un error."
            )
        html = self._req("GET", f"{BASE}/busqueda?{BUSCADORES[buscador]}").text

        token = _TOKEN.search(html)
        ident = _ID_BUSCADOR.search(html)
        if not token or not ident:
            raise EstructuraInesperada(
                "No se pudo derivar el token de sesión ni el identificador del buscador "
                f"desde {BASE}/busqueda. El sitio cambió: consultar igual produciría "
                "resultados vacíos indistinguibles de 'no hay jurisprudencia'."
            )
        self._token, self._id_buscador = token.group(1), ident.group(1)

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

        if not self._token:
            self.abrir_sesion()

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
                "Referer": f"{BASE}/busqueda?{BUSCADORES['suprema']}",
            },
        )
        return parse_sentencias(r.text)

    def _bloqueo_encubierto(self, r: httpx.Response) -> str | None:
        """El buscador responde JSON. Un cuerpo con verificación en vez de resultados es un
        bloqueo aunque venga con HTTP 200."""
        if "json" in r.headers.get("content-type", ""):
            return None
        cuerpo = r.text[:2000].lower()
        if "recaptcha" in cuerpo and "buscar_sentencias" in str(r.url):
            return "el buscador respondió con una verificación en vez de resultados"
        return None
