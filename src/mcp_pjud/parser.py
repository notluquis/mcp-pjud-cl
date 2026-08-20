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
from collections.abc import Iterator, Mapping
from datetime import date, time
from typing import NamedTuple

from lxml import etree, html
from pydantic import BaseModel, Field


class Panel(NamedTuple):
    """Cómo se lee un panel del detalle de causa.

    Las tres cosas viajan juntas a propósito. Antes el sufijo del panel estaba en la tabla y
    las columnas seguían clavadas a civil, así que poner `panel="Cob"` habría corrido las
    filas de cobranza por el mapa de nueve columnas de civil: `Estado Firma` habría caído en
    `foja` y la georreferencia se habría leído de la celda equivocada. Lo único que lo
    impedía era que civil exige el encabezado `georref.`, que cobranza no trae, o sea una
    protección accidental. Con esto no se puede declarar el panel sin declarar sus columnas.

    Era el mismo tipo escrito tres veces, uno por familia de panel. Los tres declaraban estos
    tres campos y dos repetían el docstring casi textual, y de ahí salió que el mensaje de "no
    trae ninguna tabla" quedara con dos redacciones para la misma condición.
    """

    #: Identificador COMPLETO del panel, no un sufijo.
    #:
    #: Antes se guardaba el sufijo y el código anteponía `historia`, lo que funcionaba mientras
    #: las dos competencias mapeadas se llamaran así. No se generaliza: suprema usa
    #: `movimientosSup`, apelaciones `movimientosApe` y laboral `movimientoLab`, en singular
    #: mientras las otras dos van en plural, y cobranza escribe `notificacionCob` también en
    #: singular. Un esquema de prefijo habría buscado paneles inexistentes, y buscar un panel
    #: que no está devuelve vacío.
    panel: str
    #: Orden de las celdas en cada fila. La celda `i` es `columnas[i]`.
    columnas: tuple[str, ...]
    #: Los encabezados que el sitio publica, COMPLETOS y en orden. No es una lista blanca: se
    #: comparan por cantidad y posición, porque con pertenencia una columna insertada o
    #: permutada pasaba entera y el mapeo posicional corría los campos posteriores.
    encabezados: tuple[str, ...]


#: Nombres por familia, para que las constantes y la tabla sigan diciendo de qué hablan.
Historia = Panel
Notificaciones = Panel
Liquidaciones = Panel


# Marcador de que una fila de Historia es una actuación del ministro de fe.
TRAMITE_RECEPTOR = "actuación receptor"


#: La de civil. Medida sobre `C-142-2026`.
#:
#: Publica UNA sola fecha, rotulada `Fecha Trámite`. La de notificación no viene, y por eso el
#: campo correspondiente queda nulo: igualarlo a la de trámite sería inventar una fecha, que es
#: exactamente lo que este proyecto existe para no hacer.
NOTIFICACIONES_CIVIL = Notificaciones(
    panel="notificacionesCiv",
    columnas=(
        "rol",
        "estado",
        "tipo",
        "fec_tramite",
        "tipo_parte",
        "nombre",
        "tramite",
        "observacion",
    ),
    encabezados=(
        "rol",
        "est. notif.",
        "tipo notif.",
        "fecha trámite",
        "tipo part.",
        "nombre",
        "trámite",
        "obs. fallida",
    ),
)

#: La de cobranza. Medida sobre `C-208-2019`.
#:
#: Es la única de las tres que publica las DOS fechas, y difieren: una notificación por carta
#: trajo `01/04/2019` de notificación contra `29/03/2019` de trámite, tres días. Es la misma
#: forma que la fecha doble de la Historia, con otro nombre, y por eso se entregan separadas.
#:
#: Ojo con el identificador del panel, que va en singular mientras civil y laboral lo escriben
#: en plural.
NOTIFICACIONES_COBRANZA = Notificaciones(
    panel="notificacionCob",
    columnas=(
        "tipo",
        "estado",
        "fec_notificacion",
        "fec_tramite",
        "tramite",
        "tipo_parte",
        "nombre",
    ),
    encabezados=(
        "tip.not.",
        "est.not.",
        "fec.not.",
        "fec.tram.",
        "trámite",
        "tip.part.",
        "nombre",
    ),
)

#: La de laboral. Medida sobre `O-364-2020`.
#:
#: La más corta de las tres: no trae el rol ni el tipo de notificación, y como civil publica una
#: sola fecha.
NOTIFICACIONES_LABORAL = Notificaciones(
    panel="notificacionesLab",
    columnas=("estado", "fec_tramite", "tipo_parte", "nombre", "tramite", "observacion"),
    encabezados=(
        "estado notif.",
        "fecha trámite",
        "tipo parte",
        "nombre",
        "trámite",
        "obs. fallida",
    ),
)


#: La de cobranza, medida sobre `C-208-2019`. Es la única competencia que la publica.
#:
#: Responde la pregunta que da sentido a un juicio de cobro y que hasta ahora no se contestaba:
#: cuánto se debe y a qué fecha. La causa medida trae tres liquidaciones sucesivas, de
#: $4.481.885 en 2019 a $24.563.365 en 2022.
LIQUIDACIONES_COBRANZA = Liquidaciones(
    panel="liquidacionCob",
    columnas=("documento", "fecha", "cuaderno", "estado", "monto"),
    encabezados=(
        "liquidación",
        "fecha liquidación",
        "cuaderno",
        "estado",
        "monto líquido",
    ),
)


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
    encabezados=(
        "folio",
        "doc.",
        "anexo",
        "etapa",
        "trámite",
        "desc. trámite",
        "estado firma",
        "fec. trámite",
        "georref.",
    ),
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
    encabezados=(
        "folio",
        "doc.",
        "anexo",
        "etapa",
        "trámite",
        "desc. trámite",
        "fec. trámite",
        "foja",
        "georref.",
    ),
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
    encabezados=(
        "folio",
        "doc.",
        "anexo",
        "año",
        "fecha trámite",
        "trámite",
        "des. trámite",
        "correlativo",
        "salas",
        "estado",
    ),
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
    encabezados=(
        "folio",
        "doc.",
        "anexo",
        "trámite",
        "descripción",
        "fecha",
        "sala",
        "estado",
        "georeferencia",
    ),
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
    encabezados=(
        "folio",
        "doc.",
        "anexos",
        "etapa",
        "trámite",
        "desc. trámite",
        "fecha trámite",
        "estado",
        "georref.",
    ),
)

#: Los litigantes de cada competencia. Medidos sobre las fixtures de las cinco.
#:
#: Civil llama `Participante` a lo que las otras cuatro llaman `Sujeto`, y laboral agrega dos
#: columnas que ninguna otra publica: si la parte tiene abogado defensor, y un estado. Por eso
#: hay cinco constantes y no una: leer laboral con el mapa de las demás correría el RUT al
#: campo del sujeto.
LITIGANTES_CIVIL = Panel(
    panel="litigantesCiv",
    columnas=("sujeto", "rut", "persona", "nombre"),
    encabezados=("participante", "rut", "persona", "nombre o razón social"),
)

LITIGANTES_COBRANZA = Panel(
    panel="litigantesCob",
    columnas=("sujeto", "rut", "persona", "nombre"),
    encabezados=("sujeto", "rut", "persona", "nombre o razón social"),
)

LITIGANTES_SUPREMA = Panel(
    panel="litigantesSup",
    columnas=("sujeto", "rut", "persona", "nombre"),
    encabezados=("sujeto", "rut", "persona", "nombre o razón social"),
)

LITIGANTES_APELACIONES = Panel(
    panel="litigantesApe",
    columnas=("sujeto", "rut", "persona", "nombre"),
    encabezados=("sujeto", "rut", "persona", "nombre o razón social"),
)

LITIGANTES_LABORAL = Panel(
    panel="litigantesLab",
    columnas=("estado", "abogado_defensor", "sujeto", "rut", "persona", "nombre"),
    encabezados=("est.", "abog. defensor", "sujeto", "rut", "persona", "nombre o razón social"),
)

#: Las materias de una causa laboral: qué se litiga, con su estado y su fecha de término.
#: Medida sobre `O-364-2020`, que trae nueve.
#: El exhorto visto desde el tribunal de ORIGEN: la causa que este tribunal despachó a otro.
#: Medido sobre C-1156-2026, que despacha E-875-2026 al 1º Juzgado Civil de Chillán.
#:
#: Cero filas es una respuesta legítima acá, y por eso no lleva el guardia que sí tienen los
#: litigantes: la mayoría de las causas no despacha ningún exhorto. Se midió: dos de las cuatro
#: respuestas civiles guardadas traen el panel con encabezados y ninguna fila.
EXHORTOS_CIVIL = Panel(
    panel="exhortosCiv",
    columnas=(
        "rol_origen",
        "tipo",
        "rol_destino",
        "fecha_orden",
        "fecha_ingreso",
        "tribunal_destino",
        "estado",
    ),
    encabezados=(
        "rol origen",
        "tipo exhorto",
        "rol destino",
        "fecha ordena exhorto",
        "fecha ingreso exhorto",
        "tribunal destino",
        "estado exhorto",
    ),
)

MATERIAS_LABORAL = Panel(
    panel="materiasLab",
    columnas=("codigo", "glosa", "estado", "fecha_termino"),
    encabezados=("código", "glosa de materia", "estado", "fecha término"),
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


def _validar_encabezados(encabezados: list[str], esperados: tuple[str, ...], panel: str) -> None:
    """Compara los encabezados por CANTIDAD y POSICIÓN, no por pertenencia.

    La versión anterior sólo exigía que ciertos textos estuvieran presentes en alguna parte, y
    con eso dos cambios del sitio pasaban enteros: insertar una columna al medio (los exigidos
    siguen ahí y las filas traen una celda de más) y permutar dos columnas (ni siquiera cambia
    la cantidad). En los dos casos el mapa posicional corre los campos posteriores.

    Lo que se entrega entonces no se ve roto: se ve como una fila con otros valores. En la
    Historia eso deja `fecha_diligencia` en nulo y el trámite corrido, con lo que
    `actuaciones_receptor` devuelve lista vacía SIN error. Medido con `tests/test_resistencia.py`:
    diez de los cuarenta y cinco casos de deformación pasaban en silencio.
    """
    if len(encabezados) != len(esperados):
        raise EstructuraInesperada(
            f"El panel {panel!r} trae {len(encabezados)} columnas y se esperaban "
            f"{len(esperados)}. La estructura cambió: leerla igual correría los campos "
            f"posteriores. Encabezados: {encabezados}"
        )
    for i, (esperado, real) in enumerate(zip(esperados, encabezados, strict=True)):
        if esperado not in real:
            raise EstructuraInesperada(
                f"En el panel {panel!r} la columna {i} dice {real!r} y se esperaba "
                f"{esperado!r}. Las columnas están en otro orden o se renombraron, y el "
                f"mapeo es posicional. Encabezados: {encabezados}"
            )


def _celdas(fila) -> list:
    return fila.xpath("./td")


def _filas_del_panel(html_detalle: str, spec: Panel) -> Iterator[tuple[list, dict[str, str]]]:
    """Localiza el panel, valida su tabla y entrega `(celdas, texto)` por fila de datos.

    Son los pasos que las tres lecturas repetían textualmente, con la línea que arma el
    diccionario de texto por columna idéntica byte a byte en tres lugares. La prueba de que se
    copiaron: el mensaje de "no trae ninguna tabla" había derivado en dos redacciones para la
    misma condición.

    Lo que queda DELIBERADAMENTE afuera, porque es lo que sostiene la regla 4:

    - El guardia de cero filas, que sólo aplica a la Historia. Su ausencia en notificaciones y
      liquidaciones es contrato escrito: una causa puede no tener ninguna practicada. Hornear
      cualquiera de las dos conductas acá rompería un contrato o eliminaría una protección.
    - Los mensajes que nombran el falso negativo concreto de cada panel. El de historia dice
      que una lista vacía se leería como que la causa no tiene actuaciones; el de liquidaciones,
      como que no hay deuda liquidada. Un texto genérico pierde justo lo que hace útil al fallo
      ruidoso.

    Y entrega las celdas crudas además del texto porque la Historia las necesita: lee enlaces
    dentro de la celda para saber si hay georreferencia y documento.
    """
    doc = html.fromstring(html_detalle)
    # Los comentarios traen copias del texto de las celdas; sin esto se duplican.
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    panes = doc.xpath(f'//*[@id="{spec.panel}"]')
    if not panes:
        raise EstructuraInesperada(
            f"No existe el panel {spec.panel!r} en el detalle de causa. "
            "La estructura de la Oficina Judicial Virtual cambió."
        )

    tablas = panes[0].xpath(".//table")
    if not tablas:
        raise EstructuraInesperada(f"El panel {spec.panel!r} no contiene ninguna tabla.")

    encabezados = [" ".join(th.text_content().split()).lower() for th in tablas[0].xpath(".//th")]
    _validar_encabezados(encabezados, spec.encabezados, spec.panel)

    for fila in tablas[0].xpath(".//tr"):
        celdas = _celdas(fila)
        if len(celdas) < len(spec.columnas):
            continue  # fila de encabezado o de paginación
        yield (
            celdas,
            {c: " ".join(celdas[i].text_content().split()) for i, c in enumerate(spec.columnas)},
        )


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
    actuaciones = [
        _fila_a_actuacion(celdas, cuaderno, spec.historia.columnas)
        for celdas, _ in _filas_del_panel(html_detalle, spec.historia)
    ]

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


class Notificacion(BaseModel):
    """Una fila del panel de notificaciones."""

    estado: str = Field(
        description="Si la notificación se practicó, y HAY QUE MIRARLO: la lista incluye "
        "intentos que NO se practicaron. Valores medidos: 'Realizada' en civil y laboral, "
        "'Pendiente' en laboral, 'realizada' y 'enviada' en cobranza. Una fila 'Pendiente' "
        "significa que la notificación no se ha practicado, así que su fecha NO hizo correr "
        "ningún plazo. 'enviada' es una carta despachada, que no es lo mismo que notificada."
    )
    tipo: str | None = Field(
        default=None, description="Vía por la que se notificó: 'mail', 'carta'. Laboral no la trae."
    )
    fecha_notificacion: date | None = Field(
        default=None,
        description="Cuándo se practicó la notificación, en ISO 8601. NULO donde la "
        "competencia no publica esta columna: sólo cobranza la trae. Nulo significa que el "
        "dato no está, NO que coincida con la fecha de trámite.",
    )
    fecha_tramite: date | None = Field(
        default=None,
        description="Fecha del trámite notificado, en ISO 8601. Es la única que publican civil "
        "y laboral. NO es por sí sola la fecha en que se notificó: mirar `estado` antes de "
        "computar un plazo con ella.",
    )
    tipo_parte: str = Field(
        description="Calidad de quien fue notificado. Ej: 'AB.DTE.' abogado demandante, "
        "'DDO.' demandado."
    )
    nombre: str = Field(description="Nombre de quien fue notificado, tal como lo publica el sitio.")
    tramite: str = Field(default="", description="Qué se notificó. Ej: 'resolución'.")
    observacion: str | None = Field(
        default=None,
        description="Por qué falló la notificación, cuando falló. Cobranza no trae la columna.",
    )
    rol: str | None = Field(default=None, description="Rol de la causa. Sólo civil lo repite acá.")


def parse_notificaciones(html_detalle: str, competencia: str = "civil") -> list[Notificacion]:
    """Extrae el panel de notificaciones del detalle de causa.

    Devuelve lista vacía cuando el panel existe y no trae filas, y ésa es la diferencia con
    `parse_historia`: una causa puede legítimamente no tener ninguna notificación practicada,
    mientras que toda causa tiene al menos el folio de ingreso en su historia. Tres de las
    cuatro causas civiles medidas traen el panel vacío.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.notificaciones is None:
        raise EstructuraInesperada(
            f"No está verificado cómo se leen las notificaciones en {competencia}. Leerlas con "
            "el mapa de otra competencia devolvería columnas corridas o una lista vacía."
        )

    notificaciones = []
    for _celdas_crudas, txt in _filas_del_panel(html_detalle, spec.notificaciones):
        notificaciones.append(
            Notificacion(
                estado=txt["estado"],
                tipo=txt.get("tipo") or None,
                fecha_notificacion=_fecha(txt["fec_notificacion"])
                if "fec_notificacion" in txt
                else None,
                fecha_tramite=_fecha(txt["fec_tramite"]),
                tipo_parte=txt["tipo_parte"],
                nombre=txt["nombre"],
                tramite=txt.get("tramite", ""),
                observacion=txt.get("observacion") or None,
                rol=txt.get("rol") or None,
            )
        )
    return notificaciones


#: `$24.563.365.-` como lo publica el sitio: peso chileno, punto como separador de miles y un
#: `.-` al final. Sin decimales, que es como se liquida en pesos.
_MONTO = re.compile(r"\$\s*([\d.]+)")


def _monto(txt: str) -> int | None:
    """El monto en pesos, o `None` si no tiene la forma medida.

    Devolver `None` y no cero: cero es una deuda saldada y esto es "no se pudo leer". Y ante
    una coma tampoco se adivina, porque significaría decimales donde se midió que no los hay,
    o un separador distinto, y las dos lecturas difieren en tres órdenes de magnitud.
    """
    if "," in txt:
        return None
    m = _MONTO.search(txt)
    if not m:
        return None
    digitos = m.group(1).replace(".", "")
    return int(digitos) if digitos.isdigit() else None


class Liquidacion(BaseModel):
    """Una liquidación del crédito en un juicio de cobranza.

    Una causa acumula liquidaciones sucesivas: la MÁS RECIENTE es la vigente y las anteriores
    son el historial. NO se suman. La causa medida fue de $4.481.885 en 2019 a $24.563.365 en
    2022, así que sumarlas informaría una deuda inflada varias veces.
    """

    fecha: date | None = Field(
        default=None,
        description="Fecha de la liquidación, en ISO 8601. Ordena el historial: la más reciente "
        "es la vigente y las anteriores NO se suman a ella.",
    )
    cuaderno: str = Field(default="", description="Cuaderno al que corresponde.")
    estado: str = Field(default="", description="Estado de la liquidación. Ej: 'Firmado'.")
    monto: int | None = Field(
        default=None,
        description="Monto líquido en pesos, sin separadores. Es el total adeudado A ESA "
        "FECHA, no un cargo que se sume a los demás: la deuda vigente es el monto de la "
        "liquidación más reciente. NULO si no se pudo leer con la forma medida, y nulo NO es "
        "cero, que sería una deuda saldada.",
    )
    monto_publicado: str = Field(
        description="El monto tal como lo imprime el sitio, ej: '$24.563.365.-'. Se conserva "
        "porque es lo que aparece en el expediente y es contra lo que alguien va a comparar."
    )


def parse_liquidaciones(html_detalle: str, competencia: str = "cobranza") -> list[Liquidacion]:
    """Las liquidaciones del crédito. Sólo cobranza las publica.

    Una causa puede no tener ninguna liquidada todavía, así que la lista vacía es una respuesta
    legítima y no un fallo.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.liquidaciones is None:
        raise EstructuraInesperada(
            f"La competencia {competencia!r} no publica liquidaciones: sólo cobranza tiene el "
            "panel. Leerlo en otra devolvería una lista vacía, que se leería como que no hay "
            "deuda liquidada."
        )

    liquidaciones = []
    for _celdas_crudas, txt in _filas_del_panel(html_detalle, spec.liquidaciones):
        liquidaciones.append(
            Liquidacion(
                fecha=_fecha(txt["fecha"]),
                cuaderno=txt["cuaderno"],
                estado=txt["estado"],
                monto=_monto(txt["monto"]),
                monto_publicado=txt["monto"],
            )
        )
    return liquidaciones


class Exhorto(BaseModel):
    """Una causa que este tribunal despachó a otro para que practique una diligencia.

    Se ve desde el tribunal de ORIGEN: `rol_destino` es la causa que se abrió en el otro
    tribunal, y ahí viven las actuaciones que este expediente no muestra. Un plazo que corre
    por una diligencia exhortada NO se computa desde acá.
    """

    rol_origen: str = Field(description="El rol de esta causa, la que ordena el exhorto.")
    rol_destino: str = Field(description="El rol que la causa recibió en el tribunal destino.")
    tribunal_destino: str = Field(description="Tribunal que debe practicar la diligencia.")
    tipo: str = Field(default="", description="Tipo de exhorto, según el sitio.")
    estado: str | None = Field(
        default=None,
        description="Estado del exhorto. Medido: 'Generado'. Otros valores no se conocen.",
    )
    fecha_orden: date | None = Field(
        default=None, description="Cuándo el tribunal ordenó despacharlo."
    )
    fecha_ingreso: date | None = Field(
        default=None, description="Cuándo ingresó al tribunal destino."
    )


class Litigante(BaseModel):
    """Una parte de la causa, con su calidad procesal.

    Trae RUT de personas naturales. Es lo que la plataforma publica y lo que identifica a una
    parte sin ambigüedad, y por eso se entrega: dos personas pueden llamarse igual. Quien
    conecte este servidor debe saber que recibe datos personales de terceros.
    """

    sujeto: str = Field(
        description="Calidad procesal. Ej: 'DTE.' demandante, 'DDO.' demandado, 'RECURRIDO'."
    )
    nombre: str = Field(description="Nombre o razón social, tal como lo publica el sitio.")
    rut: str = Field(
        default="", description="RUT con dígito verificador, como lo publica el sitio."
    )
    persona: str = Field(
        default="", description="Si es persona 'NATURAL' o 'JURIDICA', según el sitio."
    )
    abogado_defensor: str | None = Field(
        default=None, description="Si tiene abogado defensor. Sólo laboral publica la columna."
    )
    estado: str | None = Field(default=None, description="Estado de la parte. Sólo en laboral.")


class Materia(BaseModel):
    """Una materia de la causa: qué se está litigando."""

    codigo: str = Field(
        description="Código de la materia en la nomenclatura del sitio. Ej: 'L021'."
    )
    glosa: str = Field(description="Qué es. Ej: 'Despido injustificado', 'Feriado legal'.")
    estado: str = Field(default="", description="Estado de esa materia. Ej: 'Sentencia'.")
    fecha_termino: date | None = Field(
        default=None, description="Fecha de término de la materia, en ISO 8601."
    )


def parse_exhortos(html_detalle: str, competencia: str = "civil") -> list[Exhorto]:
    """Las causas que este tribunal despachó a otro.

    Cero filas es una respuesta, no un fallo: la mayoría de las causas no despacha ninguno.
    Está medido sobre las cuatro respuestas civiles guardadas, dos con el panel vacío y dos
    con la misma fila. Por eso este panel NO lleva el guardia de cero filas que sí llevan los
    litigantes, donde una causa sin partes no existe.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.exhortos is None:
        raise EstructuraInesperada(
            f"No está verificado cómo se leen los exhortos en {competencia}. Leerlos con el "
            "mapa de otra competencia devolvería el tribunal destino en el campo del tipo, "
            "que se ve plausible y es falso."
        )
    return [
        Exhorto(
            rol_origen=txt["rol_origen"],
            rol_destino=txt["rol_destino"],
            tribunal_destino=txt["tribunal_destino"],
            tipo=txt["tipo"],
            estado=txt["estado"] or None,
            fecha_orden=_fecha(txt["fecha_orden"]),
            fecha_ingreso=_fecha(txt["fecha_ingreso"]),
        )
        for _celdas, txt in _filas_del_panel(html_detalle, spec.exhortos)
    ]


def parse_litigantes(html_detalle: str, competencia: str = "civil") -> list[Litigante]:
    """Quiénes son parte en la causa y con qué calidad.

    Una causa sin litigantes publicados no existe, pero el panel puede venir vacío por lo mismo
    que el resto: respuesta truncada o estructura cambiada. Se devuelve lo que haya, y quien
    decida sobre eso tiene el resto de la respuesta para contrastar.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.litigantes is None:
        raise EstructuraInesperada(
            f"No está verificado cómo se leen los litigantes en {competencia}. Leerlos con el "
            "mapa de otra competencia devolvería el RUT en el campo del sujeto, que se ve "
            "plausible y es falso."
        )
    litigantes = [
        Litigante(
            sujeto=txt["sujeto"],
            nombre=txt["nombre"],
            rut=txt["rut"],
            persona=txt["persona"],
            abogado_defensor=txt.get("abogado_defensor") or None,
            estado=txt.get("estado") or None,
        )
        for _celdas, txt in _filas_del_panel(html_detalle, spec.litigantes)
    ]
    if not litigantes:
        # Toda causa tiene partes: es lo que la hace una causa. Un panel con encabezados y cero
        # filas es una respuesta truncada o una estructura que cambió, y devolver la lista
        # vacía publicaría "esta causa no tiene partes", que no existe.
        raise EstructuraInesperada(
            f"El panel de litigantes de {competencia} tiene encabezados y ninguna fila. Toda "
            "causa tiene partes, así que la respuesta viene truncada o la estructura cambió. "
            "No se devuelve la lista vacía porque se leería como que la causa no tiene partes."
        )
    return litigantes


def parse_materias(html_detalle: str, competencia: str = "laboral") -> list[Materia]:
    """Qué se litiga en la causa. Sólo laboral publica el panel."""
    spec = COMPETENCIAS[competencia.lower()]
    if spec.materias is None:
        raise EstructuraInesperada(
            f"La competencia {competencia!r} no publica materias: sólo laboral tiene el panel. "
            "Leerlo en otra devolvería una lista vacía, que se leería como que la causa no "
            "tiene materias."
        )
    return [
        Materia(
            codigo=txt["codigo"],
            glosa=txt["glosa"],
            estado=txt["estado"],
            fecha_termino=_fecha(txt["fecha_termino"]),
        )
        for _celdas, txt in _filas_del_panel(html_detalle, spec.materias)
    ]


class DetalleCausa(BaseModel):
    """Todo lo que la respuesta del detalle publica, leído de una sola vez.

    Cada campo distingue tres estados, y la diferencia entre los dos últimos es la que este
    proyecto existe para no borrar:

    - `None`: esta competencia NO publica ese panel. La pregunta no tiene respuesta acá.
    - `[]`: el panel existe y no trae filas. Es una respuesta: no hay notificaciones
      practicadas, no hay liquidaciones, no hay materias.
    - Con elementos: lo que hay.

    Devolver lista vacía en el primer caso las haría indistinguibles, y "esta competencia no lo
    informa" se leería como "no ocurrió".
    """

    causa_encontrada: bool = Field(
        default=True,
        description="Falso cuando la búsqueda no dio con el rol pedido. En ese caso TODOS los "
        "demás campos vienen en nulo por no haber causa que leer, NO porque la competencia no "
        "publique esos paneles: sin este campo las dos situaciones se verían iguales.",
    )
    historia: list[Actuacion] | None = Field(
        default=None,
        description="Todas las actuaciones, de todos los cuadernos. NULO si la competencia no "
        "tiene su panel de historia medido.",
    )
    litigantes: list[Litigante] | None = Field(
        default=None,
        description="Quiénes son parte y con qué calidad procesal. Trae RUT de personas "
        "naturales: son datos personales de terceros.",
    )
    notificaciones: list[Notificacion] | None = Field(
        default=None,
        description="Notificaciones practicadas Y no practicadas. Mirar `estado` antes de "
        "computar un plazo con sus fechas.",
    )
    liquidaciones: list[Liquidacion] | None = Field(
        default=None,
        description="Cuánto se debe y a qué fecha. Sólo cobranza liquida el crédito.",
    )
    materias: list[Materia] | None = Field(
        default=None, description="Qué se litiga. Sólo laboral publica el panel."
    )
    exhortos: list[Exhorto] | None = Field(
        default=None,
        description="Causas que este tribunal despachó a otro. Una lista con elementos "
        "significa que parte de la tramitación ocurre en OTRO expediente, y las actuaciones "
        "de esa parte no están acá.",
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
    #: Cómo leer su panel de litigantes: quiénes son parte y con qué calidad procesal.
    litigantes: Panel | None
    #: Cómo leer su panel de materias, o `None` si la competencia no lo publica.
    materias: Panel | None
    #: Cómo leer su panel de liquidaciones, o `None` si no lo publica.
    liquidaciones: Liquidaciones | None
    #: Cómo leer su panel de notificaciones, o `None` mientras no se haya medido.
    notificaciones: Notificaciones | None
    #: Si el rol que el listado publica lleva el LIBRO adelante en vez de una letra.
    #:
    #: Medido: apelaciones devuelve `Exhorto-1504-2019` y penal `Ordinaria-528-2017`, mientras
    #: civil, laboral y cobranza usan una letra y suprema no lleva prefijo. Donde va el libro,
    #: el número de rol NO identifica una causa: el mismo número y año existen en varios libros
    #: a la vez, con historias distintas.
    #:
    #: Está en la tabla porque el esquema MCP tiene que decirlo. La referencia lo explicaba y
    #: el esquema seguía anunciando "Letra del rol", y lo que el modelo lee es el esquema: con
    #: eso mandaba una letra, la desambiguación fallaba y el error parecía de la plataforma.
    rol_con_libro: bool
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
    #: Cómo leer su panel de exhortos despachados, o `None` mientras no se haya medido.
    #:
    #: Va al final y con valor por defecto porque `NamedTuple` exige que los campos con
    #: default cierren la lista. El default es `None`, o sea una competencia nueva rechaza los
    #: exhortos hasta que alguien los mida, que es la dirección segura del olvido.
    exhortos: Panel | None = None


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
        litigantes=LITIGANTES_SUPREMA,
        materias=None,
        liquidaciones=None,
        notificaciones=None,
        rol_con_libro=False,
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
        litigantes=LITIGANTES_APELACIONES,
        materias=None,
        liquidaciones=None,
        notificaciones=None,
        rol_con_libro=True,
        campos_rit={"conTipoBusApe": "0"},
        historia=HISTORIA_APELACIONES,
        receptor=False,
        receptor_en_historia=False,
        acota_por="corte",
    ),
    "civil": Competencia(
        3,
        {"rol": 1, "fecha_ingreso": 2, "caratulado": 3, "tribunal": 4},
        litigantes=LITIGANTES_CIVIL,
        materias=None,
        exhortos=EXHORTOS_CIVIL,
        liquidaciones=None,
        notificaciones=NOTIFICACIONES_CIVIL,
        rol_con_libro=False,
        campos_rit={},
        historia=HISTORIA_CIVIL,
        receptor=True,
        receptor_en_historia=True,
        acota_por="tribunal",
    ),
    "laboral": Competencia(
        4,
        {"rol": 1, "tribunal": 2, "caratulado": 3, "fecha_ingreso": 4, "estado": 5},
        litigantes=LITIGANTES_LABORAL,
        materias=MATERIAS_LABORAL,
        liquidaciones=None,
        notificaciones=NOTIFICACIONES_LABORAL,
        rol_con_libro=False,
        campos_rit={},
        historia=HISTORIA_LABORAL,
        receptor=False,
        receptor_en_historia=False,
        acota_por="tribunal",
    ),
    "penal": Competencia(
        5,
        {"rol": 1, "tribunal": 2, "ruc": 3, "caratulado": 4, "fecha_ingreso": 5, "estado": 6},
        litigantes=None,
        materias=None,
        liquidaciones=None,
        notificaciones=None,
        rol_con_libro=True,
        campos_rit={"radio-groupPenal": "1"},
        historia=None,
        receptor=False,
        receptor_en_historia=False,
        acota_por="tribunal",
    ),
    "cobranza": Competencia(
        6,
        {"rol": 1, "ruc": 2, "tribunal": 3, "caratulado": 4, "fecha_ingreso": 5, "estado": 6},
        litigantes=LITIGANTES_COBRANZA,
        materias=None,
        liquidaciones=LIQUIDACIONES_COBRANZA,
        notificaciones=NOTIFICACIONES_COBRANZA,
        rol_con_libro=False,
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
