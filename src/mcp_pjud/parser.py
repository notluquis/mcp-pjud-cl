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
from collections.abc import Mapping
from datetime import date, time
from typing import NamedTuple

from lxml import etree, html
from pydantic import BaseModel, Field

# Marcador de que una fila de Historia es una actuación del ministro de fe.
TRAMITE_RECEPTOR = "actuación receptor"


class Historia(NamedTuple):
    """Cómo leer la tabla de Historia de una competencia.

    Las tres cosas viajan juntas a propósito. Antes el sufijo del panel estaba en la tabla y
    las columnas seguían clavadas a civil, así que poner `panel="Cob"` habría corrido las
    filas de cobranza por el mapa de nueve columnas de civil: `Estado Firma` habría caído en
    `foja` y la georreferencia se habría leído de la celda equivocada. Lo único que lo
    impedía era que civil exige el encabezado `georref.`, que cobranza no trae, o sea una
    protección accidental. Con esto no se puede declarar el panel sin declarar sus columnas.
    """

    #: Identificador COMPLETO del panel, no un sufijo.
    #:
    #: Antes se guardaba el sufijo y el código anteponía `historia`, lo que funcionaba mientras
    #: las dos competencias mapeadas se llamaran así. No se generaliza: suprema usa
    #: `movimientosSup`, apelaciones `movimientosApe` y laboral `movimientoLab`, en singular
    #: mientras las otras dos van en plural. Un esquema de prefijo habría buscado paneles
    #: inexistentes, y buscar un panel que no está devuelve vacío.
    panel: str
    #: Orden de las celdas en cada fila.
    columnas: tuple[str, ...]
    #: Encabezados que se exigen. Su ausencia significa que la estructura cambió.
    encabezados: tuple[str, ...]


#: La de cobranza, medida pidiendo un detalle real el 17 de agosto de 2026.
#:
#: La diferencia con civil no es que le falten columnas: reemplaza `Foja` por `Estado Firma`
#: y la pone ANTES de `Fec. Trámite`. Leerla con el mapa de civil no da error, da algo peor:
#: `fec_tramite` sale de la celda de `Estado Firma`, cuyo valor es "Firmado", así que no se
#: parsea ninguna fecha y `fecha_diligencia` queda en `None`. Un plazo que sí corrió se
#: informaría como no informado.
HISTORIA_COBRANZA = Historia(
    panel="historiaCob",
    columnas=(
        "folio",
        "doc",
        "anexo",
        "etapa",
        "tramite",
        "desc_tramite",
        "estado_firma",
        "fec_tramite",
        "georref",
    ),
    encabezados=("folio", "desc. trámite", "estado firma", "fec. trámite", "georref."),
)

#: La de civil, medida sobre respuestas reales.
HISTORIA_CIVIL = Historia(
    panel="historiaCiv",
    columnas=(
        "folio",
        "doc",
        "anexo",
        "etapa",
        "tramite",
        "desc_tramite",
        "fec_tramite",
        "foja",
        "georref",
    ),
    encabezados=("folio", "desc. trámite", "fec. trámite", "georref."),
)

#: La de suprema. Medida sobre `135500-2020`.
#:
#: No trae `Georref.` ni `Etapa`, y agrega tres que ninguna otra publica: el año del trámite,
#: un correlativo interno y la sala que lo resolvió. La sala importa para citar un fallo, así
#: que se conserva en vez de recortarla para que calce con la forma de civil.
HISTORIA_SUPREMA = Historia(
    panel="movimientosSup",
    columnas=(
        "folio",
        "doc",
        "anexo",
        "anio",
        "fec_tramite",
        "tramite",
        "desc_tramite",
        "correlativo",
        "sala",
        "estado",
    ),
    encabezados=("folio", "fecha trámite", "des. trámite", "salas"),
)

#: La de las Cortes de Apelaciones. Medida sobre `Exhorto-1504-2019`.
#:
#: Nombra distinto dos columnas que existen en civil: `Descripción` en vez de `Desc. Trámite` y
#: `Fecha` en vez de `Fec. Trámite`. Y su georreferencia se escribe `Georeferencia`, sin punto y
#: con otra ortografía, así que la lista blanca de encabezados no puede compartirse.
HISTORIA_APELACIONES = Historia(
    panel="movimientosApe",
    columnas=(
        "folio",
        "doc",
        "anexo",
        "tramite",
        "desc_tramite",
        "fec_tramite",
        "sala",
        "estado",
        "georref",
    ),
    encabezados=("folio", "descripción", "fecha", "georeferencia"),
)

#: La de laboral. Medida sobre `O-364-2020`.
#:
#: Es la más parecida a civil: la misma forma con `Estado` donde civil pone `Foja`. Ojo con el
#: nombre del panel, que va en singular mientras suprema y apelaciones lo llevan en plural.
HISTORIA_LABORAL = Historia(
    panel="movimientoLab",
    columnas=(
        "folio",
        "doc",
        "anexo",
        "etapa",
        "tramite",
        "desc_tramite",
        "fec_tramite",
        "estado",
        "georref",
    ),
    encabezados=("folio", "desc. trámite", "fecha trámite", "georref."),
)

#: Columnas de la tabla de Historia en civil. Se conserva el nombre porque hay tests y
#: comentarios que lo referencian; la fuente única es `HISTORIA_CIVIL.columnas`.
COLUMNAS = HISTORIA_CIVIL.columnas

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
    foja: str | None = Field(
        default=None,
        description="Foja del expediente. La publica civil; cobranza no la trae, y ahí es "
        "ausente y no vacía.",
    )
    estado_firma: str | None = Field(
        default=None,
        description="Estado de firma del trámite. La publica cobranza en lugar de la foja; "
        "civil no la trae.",
    )
    estado: str | None = Field(
        default=None,
        description="Estado del trámite. La publican laboral, suprema y apelaciones.",
    )
    sala: str | None = Field(
        default=None,
        description="Sala que resolvió el trámite. Sólo en suprema y en Cortes de "
        "Apelaciones, donde forma parte de cómo se cita el fallo.",
    )
    correlativo: str | None = Field(
        default=None, description="Correlativo interno del trámite. Sólo en suprema."
    )
    anio_tramite: str | None = Field(
        default=None,
        description="Año que suprema publica en columna aparte, además de la fecha.",
    )
    georreferenciado: bool = Field(
        description="Si la actuación tiene registro georreferenciado (art. 9 inc. 3 "
        "Ley 20.886). False significa AUSENTE, lo que puede ser jurídicamente relevante."
    )
    tiene_documento: bool = Field(description="Si el folio trae documento descargable.")

    @property
    def es_actuacion_receptor(self) -> bool:
        return TRAMITE_RECEPTOR in self.tramite.lower()


#: Fechas que la plataforma imprime cuando el campo está vacío, no cuando pasó algo ese día.
#:
#: Medido en `diligenciaCob`: una diligencia de embargo cumplida traía `31/12/1969` en su
#: columna de fecha. Es el epoch de Unix visto desde una zona al oeste de Greenwich, o sea el
#: valor cero renderizado como fecha.
#:
#: Devolverlas como fechas reales es peor que devolver nulo: alguien computaría un plazo desde
#: 1969. Y es el error que este proyecto existe para no cometer, con el signo invertido: no
#: falta un dato, sobra uno que tiene forma de dato.
_FECHAS_CENTINELA = frozenset({date(1969, 12, 31), date(1970, 1, 1)})


def _fecha(txt: str) -> date | None:
    m = _FECHA.search(txt)
    if not m:
        return None
    d, mes, a = (int(x) for x in m.groups())
    try:
        parsed = date(a, mes, d)
    except ValueError:  # 31/02/2026 y similares: dato malo, no reventar la fila entera.
        return None
    return None if parsed in _FECHAS_CENTINELA else parsed


def _celdas(fila) -> list:
    return fila.xpath("./td")


def parse_historia(
    html_detalle: str, cuaderno: str = "", competencia: str = "civil"
) -> list[Actuacion]:
    """Extrae todas las filas de la pestaña Historia del detalle de causa."""
    spec = COMPETENCIAS[competencia.lower()]
    if spec.historia is None:
        raise EstructuraInesperada(
            f"No está verificado cómo se llama el panel de historia en {competencia}. "
            "Leerlo con el nombre de otra competencia devolvería vacío, que se lee como "
            "'no hubo actuaciones'."
        )
    panel = spec.historia.panel

    doc = html.fromstring(html_detalle)
    # Los comentarios traen copias del texto de las celdas; sin esto se duplican.
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    panes = doc.xpath(f'//*[@id="{panel}"]')
    if not panes:
        raise EstructuraInesperada(
            f"No existe el panel {panel!r} en el detalle de causa. "
            "La estructura de la Oficina Judicial Virtual cambió."
        )

    tablas = panes[0].xpath(".//table")
    if not tablas:
        raise EstructuraInesperada(f"El panel {panel!r} no contiene ninguna tabla.")

    encabezados = [" ".join(th.text_content().split()).lower() for th in tablas[0].xpath(".//th")]
    for esperado in spec.historia.encabezados:
        if not any(esperado in h for h in encabezados):
            raise EstructuraInesperada(
                f"Falta la columna {esperado!r} en Historia. Encabezados: {encabezados}"
            )

    actuaciones = []
    for fila in tablas[0].xpath(".//tr"):
        celdas = _celdas(fila)
        if len(celdas) < len(spec.historia.columnas):
            continue  # fila de encabezado o de paginación
        actuaciones.append(_fila_a_actuacion(celdas, cuaderno, spec.historia.columnas))

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


def _fila_a_actuacion(
    celdas: list, cuaderno: str = "", columnas: tuple[str, ...] = HISTORIA_CIVIL.columnas
) -> Actuacion:
    txt = {c: " ".join(celdas[i].text_content().split()) for i, c in enumerate(columnas)}

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
        # `etapa` y `georref` no existen en todas: suprema no publica ninguna de las dos.
        # Antes se leían con corchetes, o sea mapear una competencia sin ellas reventaba con un
        # KeyError en vez de decir qué faltaba.
        etapa=txt.get("etapa", ""),
        tramite=txt["tramite"],
        desc_tramite=txt["desc_tramite"],
        fecha_diligencia=diligencia,
        hora_diligencia=hora,
        fecha_registro=registro,
        discrepancia_fechas=discrepancia,
        cuaderno=cuaderno,
        foja=txt.get("foja"),
        estado_firma=txt.get("estado_firma"),
        estado=txt.get("estado"),
        sala=txt.get("sala"),
        correlativo=txt.get("correlativo"),
        anio_tramite=txt.get("anio"),
        # La celda trae un enlace a geoReferencia() cuando hay registro; si no, va vacía. En
        # suprema la columna no existe, y ahí `False` significa que la competencia no publica
        # el dato, no que la actuación no esté georreferenciada.
        georreferenciado=(
            bool(celdas[columnas.index("georref")].xpath(".//a"))
            if "georref" in columnas
            else False
        ),
        tiene_documento=bool(celdas[columnas.index("doc")].xpath(".//form | .//a")),
    )


def actuaciones_receptor(
    html_detalle: str, cuaderno: str = "", competencia: str = "civil"
) -> list[Actuacion]:
    """Sólo las actuaciones del ministro de fe: lo que el ebook oficial omite."""
    return [
        a for a in parse_historia(html_detalle, cuaderno, competencia) if a.es_actuacion_receptor
    ]


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
    """Una fila del listado de resultados de búsqueda.

    Los campos opcionales existen porque las competencias no publican las mismas columnas:
    la civil no trae estado ni RUC, la penal trae los dos, y la de apelaciones trae la
    ubicación física del expediente. Se declaran como opcionales en vez de inventar un valor,
    porque vacío y ausente no son lo mismo.
    """

    rol: str
    fecha_ingreso: str
    caratulado: str
    tribunal: str = Field(
        description="Tribunal o corte donde está radicada. En apelaciones y suprema es la corte."
    )
    referencia: str = Field(
        description="Identificador opaco para pedir el detalle. Caduca a los 30 minutos; "
        "no se construye ni se guarda, se usa en el acto."
    )
    competencia: str = Field(description="Competencia en la que se encontró.")
    ruc: str | None = Field(default=None, description="Sólo en penal y cobranza.")
    estado: str | None = Field(
        default=None,
        description="Lo que la competencia publica en su columna de estado, textual. No es "
        "el mismo dato en todas: cobranza publica 'Estado Procesal' y laboral, penal, "
        "apelaciones y suprema publican 'Estado Causa'. Civil no publica ninguno. Se entrega "
        "sin normalizar para no aplanar dos cosas distintas en una.",
    )
    tipo_recurso: str | None = Field(default=None, description="Sólo en suprema.")
    ubicacion: str | None = Field(default=None, description="Sólo en apelaciones.")


class Competencia(NamedTuple):
    """Cómo leer los resultados de una competencia.

    Las seis comparten formulario, nombres de campo y ruta regular: lo único que difiere es
    qué columnas trae el listado y en qué orden. Por eso esto es una tabla de datos y no seis
    parsers: duplicar el recorrido de filas para cambiar dos índices es la forma más segura
    de que uno de los seis se quede atrás cuando la plataforma cambie.

    `columnas` mapea nombre de campo a posición dentro de la fila. La celda 0 es el control
    que abre el detalle, así que los datos empiezan en 1. Los índices salen de los encabezados
    que el propio sitio arma por competencia en `consultaUnificada.php`.
    """

    codigo: int
    columnas: Mapping[str, int]
    #: Cómo leer su tabla de Historia, o `None` mientras no se haya medido una respuesta
    #: real. En ese caso el detalle se rechaza en vez de adivinar.
    historia: Historia | None
    #: Si la competencia expone actuaciones de ministro de fe. Sólo existen `receptorCivil` y
    #: `receptorCobranza` en todo el sitio, así que en las demás la pregunta que da sentido a
    #: este proyecto no tiene respuesta y conviene decirlo en vez de devolver una lista vacía.
    receptor: bool
    #: Si esas actuaciones se leen desde la tabla de Historia.
    #:
    #: En civil sí: la columna `Trámite` dice "Actuación Receptor". En cobranza NO, y esto se
    #: midió sobre una respuesta real: los trámites de `historiaCob` son `Actuación`,
    #: `Resolución` y `Escrito`, nunca "Actuación Receptor", mientras las diligencias viven en
    #: un panel aparte, `diligenciaCob`, con estructura propia (`Estado Diligencia`,
    #: `Tipo Diligencia`, `Destinatario`, `Responsable`). La palabra "receptor" aparece en esa
    #: respuesta, o sea existen: lo que no existe es la forma de leerlas desde Historia.
    #:
    #: Sin esta distinción, pedir actuaciones de cobranza devolvía una lista vacía mientras las
    #: diligencias estaban en el panel de al lado. Es exactamente el falso negativo que este
    #: proyecto existe para evitar, y la razón por la que se separa del campo anterior.
    receptor_en_historia: bool
    #: Campos que la búsqueda POR ROL exige de más en esta competencia, con su valor.
    #:
    #: Existen porque el formulario del sitio es uno solo para las seis y cada competencia
    #: activa controles propios: suprema elige entre cuatro tipos de búsqueda (`conTipoBus`),
    #: apelaciones tiene el suyo (`conTipoBusApe`) y penal separa RIT de RUC con un radio
    #: aparte (`radio-groupPenal`). Sin ellos la plataforma responde "Por favor ingrese sólo
    #: números para el Tipo de Búsqueda", o devuelve un cuerpo que no trae listado ni aviso.
    #:
    #: Están acá y no en tres ramas dentro del método porque el modo de falla que importa es
    #: que una competencia quede sin su campo y nadie lo note: la tabla se lee de un vistazo y
    #: hay un test que compara el formulario que se manda contra lo que ella declara.
    campos_rit: Mapping[str, str]
    #: Con qué hay que acotar las búsquedas por nombre, por RUT y por fecha: `"tribunal"`,
    #: `"corte"` o `None` si la competencia no exige ninguna de las dos.
    #:
    #: No es una preferencia de este cliente: es una exigencia de la plataforma, distinta según
    #: la competencia, y medida una por una. En apelaciones responde con el aviso "Por favor
    #: seleccione una Corte para la búsqueda" en las tres búsquedas; en suprema las tres andan
    #: sin corte ni tribunal; en las cuatro de primera instancia el tribunal es obligatorio.
    #:
    #: Va acá y no en tres validaciones sueltas porque el cliente exigía tribunal siempre, y
    #: con eso habría rechazado por su cuenta consultas que la plataforma acepta. Rechazar de
    #: más es más difícil de notar que rechazar de menos: no gasta una petición, no deja rastro
    #: y se ve igual que "no hay causas".
    acota_por: str | None


#: Verificado leyendo los encabezados que `consultaUnificada.php` arma para cada competencia.
COMPETENCIAS: Mapping[str, Competencia] = {
    "suprema": Competencia(
        1,
        {
            "rol": 1,
            "tipo_recurso": 2,
            "caratulado": 3,
            "fecha_ingreso": 4,
            "estado": 5,
            "tribunal": 6,
        },
        campos_rit={"conTipoBus": "0"},
        historia=HISTORIA_SUPREMA,
        receptor=False,
        receptor_en_historia=False,
        acota_por=None,
    ),
    "apelaciones": Competencia(
        2,
        {
            "rol": 1,
            "tribunal": 2,
            "caratulado": 3,
            "fecha_ingreso": 4,
            "estado": 5,
            "ubicacion": 7,
        },
        campos_rit={"conTipoBusApe": "0"},
        historia=HISTORIA_APELACIONES,
        receptor=False,
        receptor_en_historia=False,
        acota_por="corte",
    ),
    "civil": Competencia(
        3,
        {"rol": 1, "fecha_ingreso": 2, "caratulado": 3, "tribunal": 4},
        campos_rit={},
        historia=HISTORIA_CIVIL,
        receptor=True,
        receptor_en_historia=True,
        acota_por="tribunal",
    ),
    "laboral": Competencia(
        4,
        {"rol": 1, "tribunal": 2, "caratulado": 3, "fecha_ingreso": 4, "estado": 5},
        campos_rit={},
        historia=HISTORIA_LABORAL,
        receptor=False,
        receptor_en_historia=False,
        acota_por="tribunal",
    ),
    "penal": Competencia(
        5,
        {"rol": 1, "tribunal": 2, "ruc": 3, "caratulado": 4, "fecha_ingreso": 5, "estado": 6},
        campos_rit={"radio-groupPenal": "1"},
        historia=None,
        receptor=False,
        receptor_en_historia=False,
        acota_por="tribunal",
    ),
    "cobranza": Competencia(
        6,
        {"rol": 1, "ruc": 2, "tribunal": 3, "caratulado": 4, "fecha_ingreso": 5, "estado": 6},
        campos_rit={},
        historia=HISTORIA_COBRANZA,
        receptor=True,
        receptor_en_historia=False,
        acota_por="tribunal",
    ),
}


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


def parse_resultados(html_busqueda: str, competencia: str = "civil") -> list[CausaEncontrada]:
    """Extrae las filas del listado de una búsqueda de causas.

    Cada fila trae un identificador opaco en el onClick; sin él no se puede pedir el
    detalle, porque la Oficina Judicial Virtual no direcciona el detalle por rol.

    El recorrido es uno solo para las seis competencias, y lo que cambia entre ellas son los
    índices de `COMPETENCIAS`.
    """
    spec = COMPETENCIAS[competencia.lower()]
    revisar_aviso(html_busqueda)
    doc = html.fromstring(f"<table>{html_busqueda}</table>")
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    causas = []
    for fila in doc.xpath("//tr"):
        enlaces = fila.xpath('.//a[contains(@onclick, "detalleCausa")]/@onclick')
        if not enlaces:
            continue
        ref = re.search(r"detalleCausa\w*\('([^']+)'\)", str(enlaces[0]))
        if not ref:
            # La fila tiene el enlace que abre el detalle pero su argumento no se deja leer.
            # Saltarla en silencio pierde una causa dentro de un listado que igual devuelve
            # las demás, y ése es peor que devolver nada: la lista parece completa.
            raise EstructuraInesperada(
                f"Una fila del listado de {competencia} trae un control de detalle que no se "
                f"puede leer: {str(enlaces[0])[:120]!r}. La plataforma cambió cómo lo emite."
            )
        celdas = [" ".join(td.text_content().split()) for td in fila.xpath("./td")]
        # Se exige que estén TODAS las columnas que la competencia declara. Aceptar una fila
        # corta rellenando con vacío haría que un cambio de estructura pasara por causa sin
        # tribunal, que es un dato faltante disfrazado de dato.
        if len(celdas) <= max(spec.columnas.values()):
            raise EstructuraInesperada(
                f"Una fila del listado de {competencia} trae {len(celdas)} celdas y la "
                f"competencia declara columnas hasta la {max(spec.columnas.values())}. "
                "La estructura de la búsqueda cambió."
            )
        causas.append(
            CausaEncontrada(
                referencia=ref.group(1),
                competencia=competencia.lower(),
                **{campo: celdas[i] for campo, i in spec.columnas.items()},
            )
        )

    if not causas and not es_sin_resultados(html_busqueda):
        raise EstructuraInesperada(
            "El listado no trae filas ni el mensaje de 'sin resultados'. "
            "La estructura de la búsqueda cambió."
        )
    return causas
