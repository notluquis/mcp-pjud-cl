"""Parser de la tabla Historia del detalle de causa.

Recibe HTML como string y no toca la red: así se prueba contra fixtures reales sin
consultar al Poder Judicial.

Lo que este módulo existe para resolver está en dos columnas:

    Fec. Trámite:  "22/06/2026 (18/06/2026)"
                        registro      DILIGENCIA  <- la que corre los plazos

    Desc. Trámite: "Requerimiento de Pago (Ficto) Diligencia:18/06/2026 09:00"
                                                            misma fecha, con hora

Confundir la de registro con la de diligencia es el error que este proyecto existe
para evitar: el ebook oficial no trae ninguna de las dos.
"""

from __future__ import annotations

import re
from datetime import date, time

from lxml import etree, html
from pydantic import BaseModel, Field

# Marcador de que una fila de Historia es una actuación del ministro de fe.
TRAMITE_RECEPTOR = "actuación receptor"

COLUMNAS = [
    "folio",
    "doc",
    "anexo",
    "etapa",
    "tramite",
    "desc_tramite",
    "fec_tramite",
    "foja",
    "georref",
]

# La plataforma devuelve sus avisos de validación como una llamada a swal() dentro de un
# <script>, con HTTP 200. Ej: swal("","Por favor ingresar Rol para la búsqueda","warning")
_AVISO = re.compile(r'swal\(\s*"[^"]*"\s*,\s*"([^"]+)"')

_FECHA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
# "22/06/2026 (18/06/2026)" -> registro y, entre paréntesis, diligencia.
_FEC_TRAMITE = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\s*\(\s*(\d{2}/\d{2}/\d{4})\s*\))?")
# "...Diligencia:18/06/2026 09:00": la hora es opcional.
_DILIGENCIA = re.compile(r"Diligencia:\s*(\d{2}/\d{2}/\d{4})(?:\s+(\d{1,2}):(\d{2}))?", re.I)


class PlataformaRechaza(Exception):
    """La Oficina Judicial Virtual rechazó la consulta por sus propias reglas.

    Responde con un `<script>swal(...)` en vez de un código de error, así que sin esto el
    aviso llegaría al usuario disfrazado de resultado o de estructura rota.
    """


class EstructuraInesperada(Exception):
    """El HTML no tiene la forma esperada.

    Se levanta en vez de devolver una lista vacía: un falso negativo acá significa
    que un plazo se da por no corrido cuando sí corrió.
    """


class Actuacion(BaseModel):
    """Una fila de la tabla Historia."""

    folio: str
    etapa: str
    tramite: str
    desc_tramite: str = Field(description="Texto literal de la celda, sin normalizar.")

    fecha_diligencia: date | None = Field(
        default=None,
        description="Fecha real de la diligencia del receptor, en ISO 8601. ES LA QUE "
        "CUENTA PARA LOS PLAZOS PROCESALES. Nula si la fila no la informa.",
    )
    hora_diligencia: time | None = Field(
        default=None, description="Hora de la diligencia, cuando la descripción la trae."
    )
    fecha_registro: date | None = Field(
        default=None,
        description="Fecha en que el trámite se registró en el sistema, en ISO 8601. "
        "NO es la que corre los plazos.",
    )
    discrepancia_fechas: bool = Field(
        default=False,
        description="True si la fecha entre paréntesis de 'Fec. Trámite' y la de "
        "'Diligencia:' en la descripción no coinciden. Revisar a mano.",
    )

    cuaderno: str = Field(
        default="", description="Cuaderno al que pertenece la actuación. Ej: '0 - Principal'."
    )
    foja: str
    georreferenciado: bool = Field(
        description="Si la actuación tiene registro georreferenciado (art. 9 inc. 3 "
        "Ley 20.886). False significa AUSENTE, lo que puede ser jurídicamente relevante."
    )
    tiene_documento: bool = Field(description="Si el folio trae documento descargable.")

    @property
    def es_actuacion_receptor(self) -> bool:
        return TRAMITE_RECEPTOR in self.tramite.lower()


def _fecha(txt: str) -> date | None:
    m = _FECHA.search(txt)
    if not m:
        return None
    d, mes, a = (int(x) for x in m.groups())
    try:
        return date(a, mes, d)
    except ValueError:  # 31/02/2026 y similares: dato malo, no reventar la fila entera.
        return None


def _celdas(fila) -> list:
    return fila.xpath("./td")


def parse_historia(html_detalle: str, cuaderno: str = "") -> list[Actuacion]:
    """Extrae todas las filas de la pestaña Historia del detalle de causa."""
    doc = html.fromstring(html_detalle)
    # Los comentarios traen copias del texto de las celdas; sin esto se duplican.
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    panes = doc.xpath('//*[@id="historiaCiv"]')
    if not panes:
        raise EstructuraInesperada(
            "No existe el panel 'historiaCiv' en el detalle de causa. "
            "La estructura de la Oficina Judicial Virtual cambió."
        )

    tablas = panes[0].xpath(".//table")
    if not tablas:
        raise EstructuraInesperada("El panel 'historiaCiv' no contiene ninguna tabla.")

    encabezados = [" ".join(th.text_content().split()).lower() for th in tablas[0].xpath(".//th")]
    for esperado in ("folio", "desc. trámite", "fec. trámite", "georref."):
        if not any(esperado in h for h in encabezados):
            raise EstructuraInesperada(
                f"Falta la columna {esperado!r} en Historia. Encabezados: {encabezados}"
            )

    actuaciones = []
    for fila in tablas[0].xpath(".//tr"):
        celdas = _celdas(fila)
        if len(celdas) < len(COLUMNAS):
            continue  # fila de encabezado o de paginación
        actuaciones.append(_fila_a_actuacion(celdas, cuaderno))

    if not actuaciones:
        # Encabezados presentes y cero filas es anómalo: toda causa tiene al menos el
        # folio de ingreso. Esta forma la produce una respuesta truncada, una conexión
        # cortada a mitad de tabla, o HTML que lxml no logra recuperar, y en todos esos
        # casos devolver una lista vacía se leería como "no hubo actuaciones".
        #
        # Se prefiere un error que alguien pueda reportar antes que un silencio que se
        # computa como plazo no corrido. Si aparece una causa que legítimamente no tiene
        # folios, esto va a fallar y hay que reportarlo: la decisión es deliberada.
        raise EstructuraInesperada(
            "La tabla de Historia tiene encabezados pero ninguna fila. La respuesta "
            "puede venir truncada o la estructura cambió. No se devuelve una lista "
            "vacía porque se leería como que la causa no tiene actuaciones."
        )
    return actuaciones


def _fila_a_actuacion(celdas: list, cuaderno: str = "") -> Actuacion:
    txt = {c: " ".join(celdas[i].text_content().split()) for i, c in enumerate(COLUMNAS)}

    # "22/06/2026 (18/06/2026)": la primera es el registro, la de paréntesis la diligencia.
    registro = diligencia = None
    if m := _FEC_TRAMITE.search(txt["fec_tramite"]):
        registro = _fecha(m.group(1))
        if m.group(2):
            diligencia = _fecha(m.group(2))

    # "Diligencia:18/06/2026 09:00" en la descripción: misma fecha, pero con hora.
    hora = None
    desde_desc = None
    if m := _DILIGENCIA.search(txt["desc_tramite"]):
        desde_desc = _fecha(m.group(1))
        if m.group(2):
            try:
                hora = time(int(m.group(2)), int(m.group(3)))
            except ValueError:
                hora = None

    # Las dos fuentes deben coincidir. Si no, se reporta en vez de elegir en silencio.
    discrepancia = bool(diligencia and desde_desc and diligencia != desde_desc)
    if diligencia is None:
        diligencia = desde_desc

    return Actuacion(
        folio=txt["folio"],
        etapa=txt["etapa"],
        tramite=txt["tramite"],
        desc_tramite=txt["desc_tramite"],
        fecha_diligencia=diligencia,
        hora_diligencia=hora,
        fecha_registro=registro,
        discrepancia_fechas=discrepancia,
        cuaderno=cuaderno,
        foja=txt["foja"],
        # La celda trae un enlace a geoReferencia() cuando hay registro; si no, va vacía.
        georreferenciado=bool(celdas[COLUMNAS.index("georref")].xpath(".//a")),
        tiene_documento=bool(celdas[COLUMNAS.index("doc")].xpath(".//form | .//a")),
    )


def actuaciones_receptor(html_detalle: str, cuaderno: str = "") -> list[Actuacion]:
    """Sólo las actuaciones del ministro de fe: lo que el ebook oficial omite."""
    return [a for a in parse_historia(html_detalle, cuaderno) if a.es_actuacion_receptor]


class Cuaderno(BaseModel):
    """Un cuaderno de la causa. El detalle muestra uno solo a la vez."""

    nombre: str
    referencia: str = Field(description="Identificador opaco para pedir ese cuaderno.")


def parse_cuadernos(html_detalle: str) -> list[Cuaderno]:
    """Cuadernos disponibles en el detalle.

    El detalle sólo despliega la Historia de UN cuaderno. Una causa con cuaderno de
    apremio esconde ahí actuaciones que no aparecen en el principal: leer sólo el que
    viene por defecto devuelve una respuesta completa en apariencia a la que le faltan
    justamente las diligencias que interesan.
    """
    doc = html.fromstring(html_detalle)
    return [
        Cuaderno(nombre=" ".join(op.text_content().split()), referencia=op.get("value", ""))
        for op in doc.xpath('//select[@id="selCuaderno"]/option')
        if op.get("value")
    ]


class CausaEncontrada(BaseModel):
    """Una fila del listado de resultados de búsqueda."""

    rol: str
    fecha_ingreso: str
    caratulado: str
    tribunal: str
    referencia: str = Field(
        description="Identificador opaco para pedir el detalle. Caduca a los 30 minutos; "
        "no se construye ni se guarda, se usa en el acto."
    )


#: Palabras que, dentro de un aviso de la plataforma, significan que se interpuso una
#: verificación y no que falte un campo. Distinguirlas importa: un aviso de validación se
#: corrige y se reintenta, uno de captcha exige detención total.
_SENAL_CAPTCHA = ("captcha", "recaptcha", "no soy un robot", "verificaci")


def leer_aviso(html_respuesta: str) -> str | None:
    """Devuelve el aviso de la plataforma, si la respuesta es uno."""
    m = _AVISO.search(html_respuesta)
    if not m:
        return None
    # El aviso viene con las tildes escapadas al estilo de JavaScript.
    return m.group(1).encode("utf-8").decode("unicode_escape")


def es_aviso_de_captcha(mensaje: str) -> bool:
    return any(s in mensaje.lower() for s in _SENAL_CAPTCHA)


def revisar_aviso(html_respuesta: str) -> None:
    """Levanta si la respuesta es un aviso de validación de la plataforma.

    No distingue el captcha: eso lo hace el cliente, donde viven las demás reglas de
    detención total. Acá sólo se traduce el aviso a una excepción.
    """
    mensaje = leer_aviso(html_respuesta)
    if mensaje:
        raise PlataformaRechaza(mensaje)


#: El control de "página siguiente" del listado. El argumento es un identificador opaco,
#: no un número: la plataforma pagina por token y no por índice.
_SIGUIENTE = re.compile(r"pagina\w*Sig\('([^']+)'")

#: Texto exacto con que la plataforma informa que no hubo coincidencias. Esa respuesta viene
#: sin bloque de navegación y sin total declarado, así que hay que reconocerla antes de
#: exigir esos datos: si no, una búsqueda legítima sin resultados se leería como un cambio de
#: estructura, que es el error contrario pero igual de equivocado.
SIN_RESULTADOS = "No se han encontrado resultados"


def es_sin_resultados(html_busqueda: str) -> bool:
    """Si la plataforma respondió con su mensaje conocido de búsqueda sin coincidencias."""
    return SIN_RESULTADOS in html_busqueda


def siguiente_pagina(html_busqueda: str) -> str | None:
    """Identificador de la página siguiente, o None si es la última."""
    m = _SIGUIENTE.search(html_busqueda)
    return m.group(1) if m else None


#: El total que declara el listado. Se acepta cualquier atributo en la etiqueta, espacios y
#: entidades entre medio, y separadores de miles.
#:
#: La versión anterior sólo reconocía `<b>7</b>` exacto. Con `1.234` devolvía None, y como el
#: guardia de completitud se saltaba cuando el total era desconocido, se desactivaba solo
#: justo a partir de mil registros, que es donde más falta hace.
_TOTAL = re.compile(r"Total\s+de\s+registros:\s*(?:&nbsp;|\s)*<b[^>]*>\s*([\d.,]+)\s*</b>", re.I)


def total_declarado(html_busqueda: str) -> int | None:
    """Cuántos resultados dice la plataforma que hay en total, o None si no lo declara."""
    m = _TOTAL.search(html_busqueda)
    if not m:
        return None
    return int(m.group(1).replace(".", "").replace(",", ""))


def parse_resultados(html_busqueda: str) -> list[CausaEncontrada]:
    """Extrae las filas del listado de una búsqueda de causas.

    Cada fila trae un identificador opaco en el onClick; sin él no se puede pedir el
    detalle, porque la Oficina Judicial Virtual no direcciona el detalle por rol.
    """
    revisar_aviso(html_busqueda)
    doc = html.fromstring(f"<table>{html_busqueda}</table>")
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    causas = []
    for fila in doc.xpath("//tr"):
        enlaces = fila.xpath('.//a[contains(@onclick, "detalleCausa")]/@onclick')
        if not enlaces:
            continue
        ref = re.search(r"detalleCausa\w*\('([^']+)'\)", str(enlaces[0]))
        celdas = [" ".join(td.text_content().split()) for td in fila.xpath("./td")]
        if not ref or len(celdas) < 5:
            continue
        causas.append(
            CausaEncontrada(
                rol=celdas[1],
                fecha_ingreso=celdas[2],
                caratulado=celdas[3],
                tribunal=celdas[4],
                referencia=ref.group(1),
            )
        )

    if not causas and not es_sin_resultados(html_busqueda):
        raise EstructuraInesperada(
            "El listado no trae filas ni el mensaje de 'sin resultados'. "
            "La estructura de la búsqueda cambió."
        )
    return causas
