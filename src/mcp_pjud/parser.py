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

#: El origen de la Oficina Judicial Virtual. Vive acá y no en el cliente porque el parser lo
#: necesita para armar el enlace de descarga de un audio, y el cliente importa del parser y no
#: al revés. `client.BASE` es este mismo, reexportado.
BASE_SITIO = "https://oficinajudicialvirtual.pjud.cl"

#: Los encabezados del listado de audios, medidos el 22-08-2026. El correlativo va en un `th`
#: dentro de cada fila, así que la cabecera declara cinco columnas y las filas traen cuatro.
_ENCABEZADOS_AUDIO = ("nro", "descargar", "audio", "fecha", "referencia")


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
Diligencias = Panel


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


#: La de cobranza, medida sobre `C-208-2019`. Es la única competencia que la publica.
#:
#: Es donde cobranza guarda de verdad las diligencias del ministro de fe: su Historia nombra
#: tres filas `Actuacion - Receptor` y ninguna trae fecha de diligencia, así que leerlas de ahí
#: daría una lista parcial y sin el dato que se busca.
#:
#: `RIT` y `RUC` son de la causa a la que la diligencia SE DIRIGE, que no es necesariamente la
#: que se está consultando. Por eso viajan en el modelo en vez de descartarse: sin ellos no se
#: puede saber si la diligencia es de esta causa o de otra, y leerla como propia sería atribuir
#: a este expediente un trámite ajeno.
#:
#: Las dos primeras columnas son documentos, y quedan fuera del modelo por lo mismo que
#: `documento` en las liquidaciones: en la fila medida las dos vienen sin documento
#: (`cursor:no-drop`), así que sólo está medido el caso AUSENTE. Declarar `tiene_documento`
#: con eso sería publicar un mapeo sin una sola medición positiva.
DILIGENCIAS_COBRANZA = Diligencias(
    panel="diligenciaCob",
    columnas=(
        "doc_ida",
        "doc_vta",
        "estado",
        "rit",
        "ruc",
        "tipo",
        "fec_tramite",
        "destinatario",
        "responsable",
    ),
    encabezados=(
        "doc. ida",
        "doc. vta.",
        "estado diligencia",
        "rit",
        "ruc",
        "tipo diligencia",
        "fecha trámite",
        "destinatario",
        "responsable",
    ),
)


#: La de laboral, medida el 22 de agosto de 2026 sobre tres causas de 2019 y 2023.
#:
#: No es la de cobranza con dos columnas menos: donde cobranza publica `Destinatario` y
#: `Responsable`, laboral publica `Referencia`, y la fecha va al final en vez de al medio.
#: Leerla con el mapa de cobranza pondría la referencia en el destinatario y correría la fecha.
#:
#: Y acá los documentos SÍ están medidos, al revés que en cobranza: `Doc. Ida` trae el oficio
#: despachado y `Doc. Vta.` el que volvió. Una diligencia `enviada` trae sólo el de ida, y una
#: `cumplida` trae los dos: la ausencia del segundo es el dato de que el oficio no ha vuelto.
DILIGENCIAS_LABORAL = Diligencias(
    panel="diligenciasLab",
    columnas=("doc_ida", "doc_vta", "estado", "rit", "ruc", "tipo", "referencia", "fec_tramite"),
    encabezados=(
        "doc. ida",
        "doc. vta.",
        "estado diligencia",
        "rit",
        "ruc",
        "tipo diligencia",
        "referencia",
        "fecha trámite",
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

#: A qué ruta lleva cada función de JavaScript que abre un panel de anexos, con el parámetro
#: que espera. La clave es el nombre EXACTO de la función, que es lo que la celda de la
#: Historia trae en su `onclick`.
#:
#: Va por función y no por competencia porque una competencia tiene varias: civil abre
#: `anexoCausaCivil` y `anexoSolicitudCivil`, con parámetros distintos y en rutas distintas.
#: Una tabla por competencia sólo podía servir una de las dos.
#:
#: El nombre se compara completo, sin prefijos: `anexoSolicitudCivil` y
#: `anexoSolicitudCivilSII` se diferencian en el sufijo, y quedarse con el prefijo mandaría la
#: referencia del SII a la ruta que no es. Eso no da error: da otro panel.
#:
#: Sólo van las MEDIDAS, una por una, contra causas reales. Las que el sitio nombra y nadie
#: ejecutó no están: ofrecerlas sería publicar una capacidad que nadie verificó.
_MODAL_ANEXO: dict[str, str] = {
    "anexoCausaCivil": "anexoCausaCivil.php",
    "anexoSolicitudCivil": "anexoCausaSolicitudCivil.php",
    "anexoSolicitudCivilEscrit": "anexoCausaSolEscritoCivil.php",
    "anexoEscritoLaboral": "anexoEscritoLaboral.php",
    "anexoRecursoApelaciones": "anexoRecursoApelaciones.php",
    "escritoSuprema": "escritoSuprema.php",
}

#: Los escritos que el tribunal todavía no resuelve. El sitio rotula la pestaña "Escritos por
#: Resolver" en civil y "Escritos Pendientes" en laboral, y eso es lo que son: la cola de lo
#: presentado y no proveído, no el listado de todo lo que se presentó.
#:
#: Se mide en las causas recientes y no en las viejas, y eso confunde: cuatro fixtures de civil
#: lo traen vacío con escritos de sobra en su Historia, porque ya fueron resueltos. Medido el
#: 22 de agosto de 2026 sobre cinco causas de dos días de antigüedad: todas traen filas.
ESCRITOS_CIVIL = Panel(
    panel="escritosCiv",
    columnas=("doc", "anexo", "fecha_ingreso", "tipo", "solicitante"),
    encabezados=("doc.", "anexo", "fecha de ingreso", "tipo escrito", "solicitante"),
)

#: Los paneles cuyas columnas salen del ENCABEZADO y de los que nunca se vio una fila.
#:
#: La distinción importa y por eso está acá y no en un comentario suelto: de los demás paneles
#: se midió qué trae cada celda, y de éstos sólo cómo se llaman las columnas. El sitio las
#: publica en su tabla vacía, así que el orden y la cantidad SÍ están medidos y la validación
#: posicional protege igual. Lo que no está medido es el contenido: si una celda trae un
#: formulario donde acá se lee texto, va a salir vacía en vez de romper.
#:
#: Se abrieron sesenta y una causas el 22 de agosto de 2026, en cinco barridos, buscando una
#: fila de cualquiera de los tres. Ninguna la trajo: son paneles de una etapa (la liquidación
#: en cumplimiento, la acumulación en suprema) o de una cola transitoria (los escritos
#: pendientes), así que aparecen cuando la causa está en ese momento y no antes.
#:
#: Lo que se gana mapeándolos igual: el día que una causa los traiga, la respuesta los va a
#: incluir en vez de descartarlos en silencio. Lo que se pierde si el mapeo está mal: una
#: columna leída de la celda equivocada, que es lo que la validación de encabezados acota.
SIN_FILAS_OBSERVADAS = frozenset({"EscPendLab", "liquidacionLab", "agregadosSup"})

#: Los escritos por resolver de laboral. El sitio rotula su pestaña "Escritos Pendientes".
#:
#: No es el de civil con una columna más: agrega `Referencia` y pone `Solicitante` ANTES de
#: `Tipo Ingreso`, al revés que civil. Leerlo con el mapa de civil pondría el solicitante en el
#: tipo de escrito.
ESCRITOS_LABORAL = Panel(
    panel="EscPendLab",
    columnas=("doc", "anexo", "fecha_ingreso", "referencia", "solicitante", "tipo"),
    encabezados=("doc.", "anexo", "fecha ing.", "referencia", "solicitante", "tipo ingreso"),
)

#: La liquidación de laboral, que no se parece a la de cobranza.
#:
#: Cobranza liquida el crédito por documento y fecha; laboral publica a QUIÉN se le paga: RUT,
#: nombre y monto. Son dos preguntas distintas con el mismo rótulo, y por eso son dos mapas.
LIQUIDACIONES_LABORAL = Liquidaciones(
    panel="liquidacionLab",
    columnas=("documento", "rut", "nombre", "monto"),
    encabezados=("liquidación", "rut", "nombre", "monto líquido"),
)

#: Las causas agregadas a una de la Corte Suprema: las que se ven junto con ella.
CAUSAS_AGREGADAS_SUPREMA = Panel(
    panel="agregadosSup",
    columnas=("doc", "folio", "anio", "rit", "tribunal", "materia", "caratulado"),
    encabezados=("doc.", "folio", "año", "rit causa", "tribunal", "materia", "caratulado"),
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

#: El exhorto visto desde el tribunal EXHORTADO: los trámites que el tribunal de origen
#: despachó junto con él, o sea lo que este tribunal tuvo a la vista.
#: Medido sobre E-468-2026, que trae seis.
#:
#: Este panel es el único que depende de la CAUSA y no de la competencia: sólo lo traen las
#: causas que SON un exhorto, y en las demás no existe. Por eso su ausencia no se lee acá sino
#: en `parse_piezas_exhorto`, contra lo que dice la cabecera.
#:
#: Los encabezados van con la errata del sitio, que escribe `Támite` y `Fec. Támite` sin la
#: erre. Se calza con lo que la plataforma emite y no con lo correcto: un parser que busque
#: `Trámite` no encuentra nada. Si algún día la corrigen esto levanta en vez de devolver vacío,
#: que es la dirección segura del cambio.
PIEZAS_EXHORTO_CIVIL = Panel(
    panel="piezasExhortoCiv",
    columnas=(
        "folio",
        "doc",
        "cuaderno",
        "anexo",
        "etapa",
        "tramite",
        "desc_tramite",
        "fec_tramite",
        "foja",
    ),
    encabezados=(
        "folio",
        "doc.",
        "cuaderno",
        "anexo",
        "etapa",
        "támite",
        "desc. támite",
        "fec. támite",
        "foja",
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
        description="Si el sitio OFRECE la georreferencia de esta actuación, no si existe.\n\n"
        "Está medido que no es lo mismo: el 20 de agosto de 2026, una de las seis actuaciones "
        "georreferenciadas de C-1156-2026 abría un panel que responde 'No existen "
        "Georreferencia para mostrar'. Verdadero significa que hay dónde preguntar, y "
        "confirmarlo cuesta una petición por actuación.\n\n"
        "Falso significa AUSENTE **sólo donde la competencia publica la columna**, y ahí sí "
        "puede ser jurídicamente relevante (art. 9 inc. 3 Ley 20.886). Suprema no la publica, "
        "así que su falso significa que no hay dónde mirar, no que la diligencia no se "
        "georreferenció. Mirar `COMPETENCIAS[competencia].historia.columnas` para saber cuál "
        "de las dos cosas es."
    )
    tiene_documento: bool = Field(
        description="Si la columna `Doc.` del folio ofrece algo. Verdadero NO garantiza que "
        "este servidor pueda traerlo: cuando `documento_ruta` viene en nulo, la celda abre el "
        "documento con un modal de JavaScript cuyo endpoint no está medido."
    )
    tiene_anexo: bool = Field(
        default=False,
        description="Si la columna `Anexo` del folio ofrece algo. Es un SEGUNDO canal de "
        "documentos, distinto de `Doc.`: un folio puede traer la resolución en uno y los "
        "anexos del escrito en el otro.\n\n"
        "Se puede pedir SÓLO donde `anexo_referencia` viene con valor. En las demás la celda "
        "abre un modal de JavaScript cuya ruta no está verificada contra la plataforma, así "
        "que verdadero significa que hay algo y no que este servidor lo pueda traer.\n\n"
        "Se publica igual porque el silencio es peor. Sin este campo, un folio con anexo se "
        "veía idéntico a uno sin nada, y quien preguntara por los documentos de la causa "
        "recibía una respuesta que parecía completa. Verdadero significa: acá hay algo que "
        "hay que ir a buscar al expediente.\n\n"
        "Falso significa AUSENTE sólo donde la competencia publica la columna. En `penal` no "
        "hay tabla de Historia medida, así que ahí no se sabe.",
    )
    documento_ruta: str | None = Field(
        default=None,
        description="Qué ruta de la plataforma entrega ese documento. Cada competencia usa la "
        "suya. NULO cuando la actuación no trae documento.",
    )
    georreferencia_referencia: str | None = Field(
        default=None,
        description="Con qué se pide la georreferencia de esta actuación. NULO cuando la "
        "competencia no publica la columna o la actuación no la ofrece.\n\n"
        "Tenerla no garantiza que haya georreferencia: está medido que una de seis abre un "
        "panel que responde que no existe ninguna.",
    )
    anexo_ruta: str | None = Field(
        default=None,
        description="Qué ruta de la plataforma entrega los anexos de este folio. Va junto con "
        "`anexo_referencia` y hacen falta las dos, igual que para el documento: una misma "
        "competencia abre paneles distintos según el trámite, y civil tiene dos con "
        "parámetros distintos.",
    )
    anexo_referencia: str | None = Field(
        default=None,
        description="Con qué se piden los anexos de este folio. NULO cuando el folio no trae "
        "anexo, y también cuando lo trae por un panel que no está medido: ahí `tiene_anexo` "
        "queda en verdadero y esto en nulo, que significa que hay anexos y este servidor no "
        "los puede traer.",
    )
    documento_referencia: str | None = Field(
        default=None,
        description="La referencia opaca con la que la plataforma identifica ese documento. "
        "Junto con `documento_ruta` es lo único que permite pedirlo después: sin ellas se sabe "
        "que el documento existe y no cuál es. NULO cuando la actuación no trae documento.",
    )

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
    `actuaciones_receptor` devuelve lista vacía SIN error. Vuelto a medir el 23-08-2026, con
    esta función devuelta al `any(esperado in real for real in encabezados)` que tenía y con
    `tests/test_resistencia.py` cubriendo los veintitrés paneles: cuarenta y seis de sus ciento
    quince casos de deformación pasan en silencio. Es un piso y no un total: se midió con los
    encabezados COMPLETOS de hoy, y los de entonces eran listas parciales que exigían menos.
    Antes se midieron diez de cuarenta y cinco, con nueve paneles cubiertos.
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


#: La referencia que un modal de JavaScript lleva como único argumento, para las filas que
#: abren el documento así en vez de con un formulario.
#:
#: Anclado al inicio y con el nombre acotado a una función suelta a propósito. La primera
#: versión aceptaba cualquier llamada dentro del `onclick`, y las filas que SÍ traen formulario
#: llevan `$(this).closest("form").submit()`: de ahí sacaba `"form"` como si fuera la
#: referencia del documento. Un valor plausible y falso, que es peor que no traer ninguno.
_REFERENCIA_EN_MODAL = re.compile(r"^\s*([A-Za-z_]\w*)\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?\s*$")


def _referencia_en_modal(celda, funcion: str) -> str | None:
    """La referencia que una celda pasa a un modal de JavaScript.

    El sitio abre varios paneles así: `geoReferencia('...')`, `detalleExhortosCivil('...')`.
    Se exige el nombre de la función y no cualquier llamada, porque los enlaces que envían un
    formulario llevan `$(this).closest("form").submit()` y de ahí salía `"form"` como si fuera
    una referencia: un valor plausible y falso.
    """
    patron = re.compile(rf"^\s*{re.escape(funcion)}\w*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?\s*$")
    for elemento in celda.iter():
        m = patron.match(elemento.get("onclick") or "")
        if m:
            return m.group(1)
    return None


def _anexo_de_la_celda(celda) -> tuple[str | None, str | None]:
    """Con qué se piden los anexos de un folio: su ruta y su referencia.

    Mismo contrato que `_documento_de_la_celda` y por la misma razón: saber que HAY anexo no
    sirve para pedirlo, y la ruta no se puede deducir de la competencia porque civil tiene dos.

    El nombre de la función se compara COMPLETO. `anexoSolicitudCivil` es prefijo de
    `anexoSolicitudCivilSII`, que vive en otra ruta, y quedarse con el prefijo mandaría la
    referencia de una a la otra. Eso no devuelve un error: devuelve otro panel.

    Una función que no esté medida deja la ruta en nulo y conserva la referencia en nulo
    también: `tiene_anexo` sigue en verdadero, que significa "hay algo y este servidor no lo
    puede traer".
    """
    for elemento in celda.iter():
        m = _REFERENCIA_EN_MODAL.match(elemento.get("onclick") or "")
        if m and (ruta := _MODAL_ANEXO.get(m.group(1))):
            return ruta, m.group(2)
    return None, None


def _documento_de_la_celda(celda) -> tuple[str | None, str | None]:
    """Con qué se pide el documento de una actuación: su ruta y su referencia.

    Antes se leía únicamente si el formulario existía, o sea la respuesta decía que HAY
    documento y no CUÁL, y con eso no se puede pedir: quien lo quisiera tendría que volver a
    consultar el detalle entero para encontrarlo.

    Se lee del formulario y NO de una tabla por competencia, y eso importa: cada una nombra
    esto a su manera, y una tabla escrita a mano tendría que acertarle a las cinco y envejecer
    con la sexta. Medido sobre las fixtures:

    | Competencia | Campo | Ruta |
    |---|---|---|
    | civil | `dtaDoc` | `docuN.php` |
    | cobranza | `dtaDoc` | `docuCobranza.php` |
    | laboral | `valorRef` | `docReformadoLaboral.php` |
    | apelaciones | `valorDoc` | `docCausaApelaciones.php` |
    | suprema | `valorFile` | `docCausaSuprema.php` |

    La primera versión de esta función buscaba `dtaDoc` a secas, que es el nombre de civil, y
    devolvía nulo en las otras cuatro con `tiene_documento` en verdadero. O sea el falso
    negativo que vino a arreglar, reintroducido para cuatro competencias.

    Se devuelven tal cual y sin interpretar: la referencia es opaca y versionada por sesión.
    """
    for formulario in celda.iter("form"):
        ruta = (formulario.get("action") or "").rsplit("/", 1)[-1] or None
        for oculto in formulario.iter("input"):
            nombre, valor = oculto.get("name"), oculto.get("value")
            # El certificado de envío es otro documento, y en varias competencias viaja en la
            # misma fila. Confundirlos entregaría el certificado como si fuera la resolución.
            if nombre and valor and nombre != "dtaCert":
                return ruta, valor

    # Y algunas filas no traen formulario: abren el documento con un modal de JavaScript que
    # lleva la referencia como argumento. Está medido en laboral, en la fila del texto de la
    # demanda. La referencia se rescata igual, y la ruta queda nula a propósito: el nombre de
    # la función no es un endpoint, y a cuál llama no está medido. Inventarlo sería adivinar.
    for enlace in celda.iter("a"):
        m = _REFERENCIA_EN_MODAL.match(enlace.get("onclick") or "")
        if m:
            return None, m.group(2)
    return None, None


def _no_agrega_nada_a_la_anterior(fila: Actuacion, anterior: Actuacion) -> bool:
    """Si esta fila es la anterior otra vez, sin nada propio que la anterior no tenga ya.

    En cobranza la plataforma repite algunas filas de la Historia. Medido campo por campo
    sobre la respuesta real, la repetición del folio 68 contra su original:

        etapa:       'Excepciones / Objeta Liquidación'  ->  ''
        tramite:     'Resolución'                        ->  ''
        documento:   sí, con ruta y referencia           ->  ninguno

    O sea no es una copia idéntica: es una versión empobrecida. De 80 filas, 9 son esto, y el
    folio 5 aparece tres veces. Entregarlas como actuaciones distintas infla el panel del que
    cuelgan los plazos, y una fila con el trámite en blanco tampoco puede reconocerse como
    actuación de receptor: ese filtro la pierde.

    Por eso la regla no es "se parece" sino "no agrega nada": mismo folio y misma descripción,
    y CADA uno de sus campos o está vacío o vale lo mismo que en la anterior. Una fila que
    difiera en la fecha, el estado o el documento trae algo propio y se conserva, aunque
    comparta folio y descripción.

    La condición floja tampoco sirve: en civil hay cinco filas legítimas sin trámite, medidas
    en tres fixtures, y mirar sólo eso las habría borrado.
    """
    if fila.folio != anterior.folio or fila.desc_tramite != anterior.desc_tramite:
        return False
    previos = anterior.model_dump()
    return all(not valor or valor == previos[campo] for campo, valor in fila.model_dump().items())


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
    actuaciones: list[Actuacion] = []
    for celdas, _ in _filas_del_panel(html_detalle, spec.historia):
        fila = _fila_a_actuacion(celdas, cuaderno, spec.historia.columnas)
        if actuaciones and _no_agrega_nada_a_la_anterior(fila, actuaciones[-1]):
            continue
        actuaciones.append(fila)

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

    documento = _documento_de_la_celda(celdas[columnas.index("doc")])
    anexo = (
        _anexo_de_la_celda(celdas[columnas.index("anexo")]) if "anexo" in columnas else (None, None)
    )
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
        georreferencia_referencia=(
            _referencia_en_modal(celdas[columnas.index("georref")], "geoReferencia")
            if "georref" in columnas
            else None
        ),
        tiene_documento=bool(celdas[columnas.index("doc")].xpath(".//form | .//a")),
        # La columna `Anexo` es un segundo canal de documentos y hasta acá no se leía ninguna
        # celda de ella. Un folio con anexo salía idéntico a uno sin nada, así que preguntar
        # por los documentos de la causa devolvía una lista que parecía completa: el falso
        # negativo de la regla 4, en la columna de al lado de la que sí se leía.
        tiene_anexo=(
            bool(celdas[columnas.index("anexo")].xpath(".//form | .//a"))
            if "anexo" in columnas
            else False
        ),
        anexo_ruta=anexo[0],
        anexo_referencia=anexo[1],
        documento_ruta=documento[0],
        documento_referencia=documento[1],
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
    """Una liquidación del crédito. La publican cobranza y laboral.

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
        "cero, que sería una deuda saldada.\n\n"
        "La forma medida es la de cobranza (`$24.563.365.-`). En laboral el panel nunca trajo "
        "una fila, así que si imprime el monto de otra manera esto va a venir nulo con "
        "`monto_publicado` lleno, y ahí el dato está en el segundo.",
    )
    monto_publicado: str = Field(
        description="El monto tal como lo imprime el sitio, ej: '$24.563.365.-'. Se conserva "
        "porque es lo que aparece en el expediente y es contra lo que alguien va a comparar."
    )
    rut: str | None = Field(
        default=None,
        description="A QUIÉN se le paga, en las liquidaciones de laboral. Es un RUT de persona "
        "natural: dato personal de un tercero. NULO en cobranza, que liquida el crédito por "
        "documento y no por persona, y también mientras el panel de laboral no traiga una fila: "
        "su contenido sale del encabezado y nadie lo ha visto lleno.",
    )
    nombre: str | None = Field(
        default=None,
        description="El nombre de esa persona, tal como el sitio lo publica. NULO en cobranza "
        "por lo mismo.",
    )


def _las_que_publican(panel: str) -> str:
    """Qué competencias publican un panel, sacado de `COMPETENCIAS` y no escrito al lado.

    Los mensajes de "esta competencia no lo publica" enumeraban a mano quién sí, y uno de
    ellos ya se había separado de su fuente: decía "sólo cobranza" de un panel que laboral
    también publica, mientras la docstring de la misma función ya nombraba a las dos.
    """
    publican = sorted(n for n in COMPETENCIAS if getattr(COMPETENCIAS[n], panel) is not None)
    if len(publican) < 2:
        return f"sólo {''.join(publican)}"
    return f"{', '.join(publican[:-1])} y {publican[-1]}"


def parse_liquidaciones(html_detalle: str, competencia: str = "cobranza") -> list[Liquidacion]:
    """Las liquidaciones del crédito. Las publican cobranza y laboral.

    Una causa puede no tener ninguna liquidada todavía, así que la lista vacía es una respuesta
    legítima y no un fallo.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.liquidaciones is None:
        raise EstructuraInesperada(
            f"La competencia {competencia!r} no publica liquidaciones. Leerlo en otra "
            "devolvería una lista vacía, que se leería como que no hay deuda liquidada."
        )

    liquidaciones = []
    for _celdas_crudas, txt in _filas_del_panel(html_detalle, spec.liquidaciones):
        liquidaciones.append(
            Liquidacion(
                # Con `get` y no corchetes: los dos paneles comparten el monto y nada más, así
                # que pedir por índice lo que la otra competencia no publica reventaría con un
                # KeyError en vez de decir que ese panel no trae la columna.
                fecha=_fecha(txt.get("fecha", "")),
                cuaderno=txt.get("cuaderno", ""),
                estado=txt.get("estado", ""),
                monto=_monto(txt["monto"]),
                monto_publicado=txt["monto"],
                rut=txt.get("rut"),
                nombre=txt.get("nombre"),
            )
        )
    return liquidaciones


class Diligencia(BaseModel):
    """Una diligencia del ministro de fe. La publican cobranza y laboral.

    En cobranza es el panel donde se guardan de verdad: su tabla de Historia nombra algunas
    como `Actuacion - Receptor`, sin tilde y con guion, y ninguna trae fecha de diligencia,
    así que leerlas de ahí daría una lista parcial y sin el dato que se busca.

    No es una `Actuacion` y no se puede tratar como tal. Una actuación de civil trae la fecha
    doble que corre los plazos; acá el sitio publica una sola columna de fecha, y en la fila
    medida trae el valor cero.
    """

    estado: str = Field(
        description="Si la diligencia se practicó, y HAY QUE MIRARLO antes de leer la fecha. "
        "Valor medido: 'cumplida'. Que la fecha venga nula NO significa que no se practicó: "
        "significa que el sitio no publicó ninguna."
    )
    tipo: str = Field(
        description="Qué diligencia es. Ej: 'Oficios Varios 3'. Es lo que el sitio imprime, "
        "sin normalizar: dos causas pueden escribir distinto la misma diligencia."
    )
    fecha_tramite: date | None = Field(
        default=None,
        description="La única fecha que el panel publica, en ISO 8601. NO es la fecha de "
        "diligencia de civil: acá no viene la fecha doble, así que no se puede afirmar cuándo "
        "el ministro de fe la practicó. NULA también cuando el sitio imprime `31/12/1969`, que "
        "es el valor cero renderizado como fecha y no una diligencia de 1969: informarla haría "
        "computar un plazo desde ahí.",
    )
    destinatario: str | None = Field(
        default=None,
        description="A quién se dirige la diligencia. Medido: 'No Asignado', o sea el panel "
        "publica la fila antes de que haya alguien encargado de practicarla. NULO en laboral, "
        "que no publica la columna.",
    )
    responsable: str | None = Field(
        default=None,
        description="Quién figura a cargo de la diligencia, tal como lo publica el sitio. Es "
        "el nombre de una persona natural: es un dato personal de un tercero. NULO en laboral, "
        "que no publica la columna.",
    )
    referencia: str | None = Field(
        default=None,
        description="Con qué se despachó la diligencia, como lo rotula el sitio. Medido en "
        "laboral: 'Envío Automatico'. NULO en cobranza, que no publica la columna.",
    )
    documento_ida_ruta: str | None = Field(
        default=None,
        description="Qué ruta entrega el oficio DESPACHADO. NULO cuando la fila no lo trae, y "
        "también en cobranza, donde sólo está medido el caso sin documento.",
    )
    documento_ida_referencia: str | None = Field(
        default=None, description="Con qué se pide ese documento. Va junto con su ruta."
    )
    documento_vuelta_ruta: str | None = Field(
        default=None,
        description="Qué ruta entrega el oficio que VOLVIÓ. Su ausencia es un dato: está "
        "medido que una diligencia `enviada` trae sólo el de ida, y una `cumplida` los dos.",
    )
    documento_vuelta_referencia: str | None = Field(
        default=None, description="Con qué se pide ese documento. Va junto con su ruta."
    )
    rit: str = Field(
        description="RIT de la causa A LA QUE la diligencia se dirige, que NO es "
        "necesariamente la que se consultó. Leerlo como el RIT de esta causa haría informar "
        "como propia una diligencia de otro expediente."
    )
    ruc: str = Field(
        description="RUC de esa misma causa, con el mismo cuidado que `rit`: es de la causa "
        "destinataria de la diligencia, no de la consultada."
    )


def parse_diligencias(html_detalle: str, competencia: str = "cobranza") -> list[Diligencia]:
    """Las diligencias del ministro de fe. Las publican cobranza y laboral en un panel propio.

    Una causa puede no tener ninguna, así que la lista vacía es una respuesta legítima y no un
    fallo: de cinco causas de cobranza medidas, sólo una trae filas acá.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.diligencias is None:
        # Quiénes lo publican sale de `COMPETENCIAS` y no escrito acá: este mensaje decía
        # "sólo cobranza" mientras la docstring de arriba ya nombraba a las dos, o sea el
        # error contradecía a la función que lo levanta.
        raise EstructuraInesperada(
            f"La competencia {competencia!r} no publica el panel de diligencias del ministro "
            f"de fe: lo tienen medido {_las_que_publican('diligencias')}. Leerlo en otra "
            "devolvería una lista vacía, que se leería como que no se practicó ninguna "
            "diligencia."
        )

    columnas = spec.diligencias.columnas
    diligencias = []
    for celdas, txt in _filas_del_panel(html_detalle, spec.diligencias):
        ida = _documento_de_la_celda(celdas[columnas.index("doc_ida")])
        vuelta = _documento_de_la_celda(celdas[columnas.index("doc_vta")])
        diligencias.append(
            Diligencia(
                estado=txt["estado"],
                tipo=txt["tipo"],
                fecha_tramite=_fecha(txt["fec_tramite"]),
                # Los tres que una competencia publica y la otra no. `get` y no corchetes: con
                # corchetes, agregar una competencia que no traiga la columna revienta con un
                # KeyError en vez de decir que ese panel no la publica.
                destinatario=txt.get("destinatario"),
                responsable=txt.get("responsable"),
                referencia=txt.get("referencia"),
                rit=txt["rit"],
                ruc=txt["ruc"],
                documento_ida_ruta=ida[0],
                documento_ida_referencia=ida[1],
                documento_vuelta_ruta=vuelta[0],
                documento_vuelta_referencia=vuelta[1],
            )
        )
    return diligencias


class Corte(BaseModel):
    """Una Corte de Apelaciones, con el código que las búsquedas exigen."""

    codigo: int = Field(description="Lo que va en el parámetro `corte` de las búsquedas.")
    nombre: str = Field(description="Nombre tal como lo publica la plataforma.")


class Tribunal(BaseModel):
    """Un tribunal de primera instancia, con el código que las búsquedas exigen."""

    codigo: int = Field(description="Lo que va en el parámetro `tribunal` de las búsquedas.")
    nombre: str = Field(description="Nombre tal como lo publica la plataforma.")


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
    referencia: str | None = Field(
        default=None,
        description="La referencia con la que la plataforma abre el detalle de este exhorto. "
        "Se guarda para cuando ese panel esté medido: hoy no hay herramienta que la use.",
    )


class CausaDeOrigen(BaseModel):
    """La causa de la Corte de Apelaciones de la que subió el recurso.

    Cierra la arista hacia ABAJO, igual que `Exhorto` la cierra hacia el lado: sin esto el
    detalle de una causa de la Corte Suprema dice que hubo una apelación y no dice dónde está
    la causa apelada, que es donde vive todo lo que ocurrió antes.

    Los cuatro rótulos del panel son UN dato, la identidad de una causa, y por eso ninguno
    viaja en nulo: el mismo número de rol existe en las diecisiete cortes y, dentro de una, en
    varios libros a la vez. Un rol sin corte no ubica nada.
    """

    corte: str = Field(
        description="NOMBRE de la Corte de Apelaciones, tal como el sitio lo emite. Ej: 'C.A. "
        "DE CONCEPCIÓN'. NO es el código que las búsquedas exigen: para consultar esta causa "
        "hay que resolverlo con `listar_cortes` y pasar el entero, igual que con el tribunal "
        "de destino de un exhorto. Pasar el nombre donde va el código no devuelve un error, "
        "devuelve las causas de otra jurisdicción."
    )
    libro: str = Field(
        description="Libro en que la corte tramitó el recurso. Ej: 'Protección'. Es lo que va "
        "en `tipo` al buscar en apelaciones, que es la única competencia donde el rol lleva el "
        "libro adelante en vez de una letra: sin él, `14988-2020` no identifica una causa."
    )
    rol: int = Field(
        description="Número de rol en la corte, sin el libro ni el año. El sitio lo publica "
        "junto al año y con espacios alrededor del guion ('14988 - 2020'); se entrega partido "
        "porque es así como lo piden las búsquedas de este servidor, que exigen enteros."
    )
    anio: int = Field(description="Año de ingreso a la corte, cuatro dígitos.")
    recurso: str = Field(
        description="Qué se recurrió, tal como el sitio lo emite y sin normalizar. Ej: "
        "'(Civil) Apelación Protección'."
    )


class Georreferencia(BaseModel):
    """Dónde y cuándo el ministro de fe registró que practicó una diligencia.

    Es el registro del art. 9 inc. 3 de la Ley 20.886, y trae algo que no hay en ninguna otra
    parte de la respuesta: la **hora**. Las dos fechas de la Historia son del día, y ésta viene
    del aparato con que se tomó la coordenada.

    Eso la vuelve una TERCERA fuente sobre cuándo ocurrió la diligencia, independiente de las
    dos que el sitio publica en la tabla. No reemplaza a `fecha_diligencia`, que es la que
    corre los plazos: sirve para contrastarla.

    Trae coordenadas de un domicilio de terceros. Se entregan porque son lo que la plataforma
    publica y lo que hace útil el registro, con el mismo criterio que el RUT de los litigantes,
    y por eso mismo no se guardan en este repositorio.
    """

    existe: bool = Field(
        description="Falso cuando la actuación ofrece georreferencia y el panel responde que "
        "no hay ninguna. Está medido: una de seis. En ese caso los demás campos vienen nulos, "
        "y eso NO es lo mismo que no haber preguntado."
    )
    latitud: float | None = Field(default=None, description="Latitud, como la publica el sitio.")
    longitud: float | None = Field(default=None, description="Longitud, como la publica el sitio.")
    precision_metros: float | None = Field(
        default=None,
        description="Radio de incertidumbre en metros. Medidas en una sola causa: 6,0 · 10,04 "
        "· 26,68 · 56,22 y 103,13.\n\n"
        "Informarla SIEMPRE junto con las coordenadas. Un radio de 103 metros abarca una "
        "manzana entera en zona urbana, así que ahí la coordenada dice el sector y no la "
        "puerta, y presentarla como una dirección exacta es afirmar de más.",
    )
    fecha_dispositivo: date | None = Field(
        default=None,
        description="Cuándo el aparato tomó la coordenada. Es la ÚNICA fecha del proyecto que "
        "viene con hora, y es una fuente independiente de las dos de la Historia.",
    )
    hora_dispositivo: time | None = Field(
        default=None, description="La hora de esa toma, que ninguna otra fecha del proyecto trae."
    )
    intentos: int | None = Field(
        default=None,
        description="Cuántas veces el aparato intentó fijar la posición, según el sitio. Sin "
        "medir qué significa un número alto.",
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
    estado: str | None = Field(
        default=None,
        description="Estado de la parte, tal como el sitio lo emite: la clase del icono, sin "
        "interpretar. Sólo laboral publica la columna, y ahí NUNCA es nulo. Un nulo significa "
        "que esta competencia no publica el dato, no que la parte no tenga estado.",
    )


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


def _referencia_del_exhorto(celdas, columnas: tuple[str, ...]) -> str | None:
    """La referencia con la que la plataforma abre el detalle de un exhorto.

    Viaja en el `onclick` de la celda del rol de destino, no en un formulario. Se guarda
    porque es lo único que permitiría seguir la arista sin reconstruir una búsqueda, y hoy
    `detalleExhortos.php` está mapeado y sin ejecutar: cuando se mida, el dato ya está.
    """
    if "rol_destino" not in columnas:
        return None
    celda = celdas[columnas.index("rol_destino")]
    for elemento in celda.iter():
        m = _REFERENCIA_EN_MODAL.match(elemento.get("onclick") or "")
        if m:
            return m.group(2)
    return None


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
            referencia=_referencia_del_exhorto(celdas, spec.exhortos.columnas),
        )
        for celdas, txt in _filas_del_panel(html_detalle, spec.exhortos)
    ]


#: Lo que la cabecera pone en `Proc.` cuando la causa ES un exhorto. Medido sobre E-468-2026.
#:
#: Se compara por contención y no por igualdad para no depender del relleno con que el sitio
#: pinta la celda. Errarle en cualquiera de los dos sentidos no pasa en silencio: en
#: `parse_piezas_exhorto` esta lectura se contrasta contra la presencia del panel.
_PROCEDIMIENTO_EXHORTO = "exhorto"


def _valor_de_la_cabecera(html_detalle: str, rotulo: str) -> str:
    """Lo que la cabecera del detalle publica bajo un rótulo. Ej: `Proc.` devuelve `Exhorto`.

    La cabecera no es una tabla de datos: no tiene `id`, no tiene encabezados y cada dato es un
    `<td>` con su rótulo en un `<strong>` y el valor suelto detrás. Por eso no pasa por `Panel`
    ni por la validación posicional, que necesitan columnas: se busca el rótulo y se lee la
    cola del `<strong>`, que es donde cae el valor.
    """
    doc = html.fromstring(html_detalle)
    # Los comentarios de la cabecera traen copias de los valores; sin esto se leen dos veces.
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    buscado = rotulo.rstrip(":").lower()
    for etiqueta in doc.xpath('//table[contains(@class, "table-titulos")]//td/strong'):
        if " ".join(etiqueta.text_content().split()).rstrip(":").lower() == buscado:
            return " ".join((etiqueta.tail or "").split())

    raise EstructuraInesperada(
        f"La cabecera del detalle no publica {rotulo!r}. Es de donde sale qué clase de causa "
        "es ésta, y sin ese dato la única forma de saberlo sería deducirlo de qué paneles "
        "llegaron, que es lo que este módulo no hace."
    )


def causa_es_exhorto(html_detalle: str, competencia: str = "civil") -> bool:
    """Si ESTA causa es un exhorto: una que otro tribunal abrió acá para practicar diligencias.

    Los dos lados del exhorto se ven desde causas distintas y traen paneles distintos. La que
    lo ORDENA trae `exhortosCiv` con la fila del despacho; la que lo RECIBE trae
    `piezasExhortoCiv` con lo que el tribunal de origen le mandó, y no trae el otro.

    Se lee de la cabecera y NO de qué panel llegó, y ésa es la decisión que hace falta. Deducir
    "no es un exhorto" de que el panel no esté ata la afirmación a que la plataforma no
    renombre un `id`: el día que lo renombre, la respuesta no diría "no pude leerlo", diría
    "esta causa no es un exhorto", que es una afirmación falsa y no un error.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.piezas_exhorto is None:
        raise EstructuraInesperada(
            f"No está verificado qué pone la cabecera de {competencia} cuando la causa es un "
            "exhorto. Sólo civil está medida, y responder que no lo es sin haberlo medido "
            "descarta en silencio las piezas que el tribunal de origen despachó."
        )
    return _PROCEDIMIENTO_EXHORTO in _valor_de_la_cabecera(html_detalle, "Proc.").lower()


class PiezaExhorto(BaseModel):
    """Un trámite de la causa de ORIGEN que vino junto con el exhorto.

    NO es una actuación de esta causa, y por eso no comparte tipo con `Actuacion` ni viaja en
    `historia`: es tramitación que ocurrió en el otro tribunal, antes de que el exhorto llegara,
    y es lo que el tribunal exhortado tuvo a la vista. Los plazos de esta causa no se computan
    desde acá.
    """

    folio: str
    cuaderno: str = Field(
        default="", description="Cuaderno de la causa de ORIGEN al que pertenece la pieza."
    )
    etapa: str = Field(default="", description="Etapa en que la causa de origen la despachó.")
    tramite: str = Field(default="", description="Tipo de trámite. Ej: 'Resolución', 'Escrito'.")
    desc_tramite: str = Field(default="", description="Texto literal de la celda, sin normalizar.")
    fecha_registro: date | None = Field(
        default=None,
        description="Cuándo el tribunal de origen registró el trámite, en ISO 8601.",
    )
    fecha_diligencia: date | None = Field(
        default=None,
        description="La fecha entre paréntesis, cuando la celda trae las dos. Nula en las seis "
        "piezas medidas: ahí el sitio publica una sola fecha en esta columna.",
    )
    foja: str = Field(default="", description="Foja del expediente de origen.")
    tiene_documento: bool = Field(description="Si la columna `Doc.` de la pieza ofrece algo.")
    tiene_anexo: bool = Field(
        default=False,
        description="Si la columna `Anexo` de la pieza ofrece algo. Es el mismo canal que "
        "`Actuacion.tiene_anexo`, pero acá NO se puede pedir: las piezas sólo están medidas "
        "en civil, y de las rutas de anexo sólo se ejecutó la de laboral. Por eso esta pieza "
        "no trae referencia de anexo y la actuación laboral sí. La pieza puede traer su "
        "documento principal y un anexo aparte.",
    )
    documento_ruta: str | None = Field(
        default=None,
        description="Qué ruta de la plataforma entrega ese documento. NULO si no trae.",
    )
    documento_referencia: str | None = Field(
        default=None,
        description="La referencia opaca con la que la plataforma identifica ese documento. "
        "Junto con `documento_ruta` es lo único que permite pedirlo después. NULO si no trae.",
    )


def parse_piezas_exhorto(
    html_detalle: str, competencia: str = "civil"
) -> list[PiezaExhorto] | None:
    """Los trámites que el tribunal de origen despachó junto con el exhorto.

    Devuelve `None` cuando, y sólo cuando, la causa NO es un exhorto: ahí el panel no existe
    porque la pregunta no aplica. Una lista vacía diría "es un exhorto y no le mandaron nada",
    que es otra cosa.

    Las dos lecturas se contrastan a propósito, y una contradicción levanta en vez de elegir.
    No son intercambiables: creerle a la cabecera tiraría piezas que están ahí, y creerle al
    panel inventaría un exhorto donde el sitio dice que no lo hay. Las dos direcciones pierden,
    así que la única respuesta honesta es decir que no se entiende la respuesta.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.piezas_exhorto is None:
        raise EstructuraInesperada(
            f"No está verificado cómo se leen las piezas del exhorto en {competencia}. La de "
            "civil lleva el cuaderno al medio de las nueve columnas, así que leer otra con ese "
            "mapa correría los campos y la fecha caería en la foja."
        )

    procedimiento = _valor_de_la_cabecera(html_detalle, "Proc.")
    doc = html.fromstring(html_detalle)
    hay_panel = bool(doc.xpath(f'//*[@id="{spec.piezas_exhorto.panel}"]'))

    if _PROCEDIMIENTO_EXHORTO not in procedimiento.lower():
        if hay_panel:
            raise EstructuraInesperada(
                f"La cabecera dice que el procedimiento es {procedimiento!r} y el detalle igual "
                f"trae el panel {spec.piezas_exhorto.panel!r}. Descartarlo por la cabecera "
                "tiraría la tramitación que el tribunal de origen despachó, y leerlo igual "
                "diría que ésta es una causa exhortada cuando el sitio dice que no lo es."
            )
        return None

    if not hay_panel:
        raise EstructuraInesperada(
            f"La cabecera dice que esta causa es un exhorto ({procedimiento!r}) y el detalle no "
            f"trae el panel {spec.piezas_exhorto.panel!r}. Devolver la lista vacía se leería "
            "como que el tribunal de origen no despachó ninguna pieza."
        )

    piezas = []
    for celdas, txt in _filas_del_panel(html_detalle, spec.piezas_exhorto):
        # Misma columna que la `Fec. Trámite` de la Historia, con el nombre mal escrito: puede
        # traer las dos fechas. Se separan aunque las seis filas medidas traigan una sola,
        # porque quedarse con la primera es exactamente confundir el registro con la diligencia.
        registro = diligencia = None
        if m := _FEC_TRAMITE.search(txt["fec_tramite"]):
            registro = _fecha(m.group(1))
            if m.group(2):
                diligencia = _fecha(m.group(2))

        documento = _documento_de_la_celda(celdas[spec.piezas_exhorto.columnas.index("doc")])
        piezas.append(
            PiezaExhorto(
                folio=txt["folio"],
                cuaderno=txt["cuaderno"],
                etapa=txt["etapa"],
                tramite=txt["tramite"],
                desc_tramite=txt["desc_tramite"],
                fecha_registro=registro,
                fecha_diligencia=diligencia,
                foja=txt["foja"],
                tiene_documento=bool(
                    celdas[spec.piezas_exhorto.columnas.index("doc")].xpath(".//form | .//a")
                ),
                # Las piezas declaran `anexo` igual que la historia, y quedarse corto acá dejaba
                # el mismo falso negativo en el panel de al lado: arreglado para un llamador y
                # no para el otro, que es peor que no haberlo arreglado.
                tiene_anexo=bool(
                    celdas[spec.piezas_exhorto.columnas.index("anexo")].xpath(".//form | .//a")
                ),
                documento_ruta=documento[0],
                documento_referencia=documento[1],
            )
        )
    if not piezas:
        # Esta causa ES un exhorto, y un exhorto existe porque el tribunal de origen despachó
        # algo: las piezas medidas incluyen `Ordena despachar mandamiento` y `Exhórtese`, o sea
        # los actos que lo crearon. Cero filas acá es una respuesta truncada, y la lista vacía
        # se leería como que el tribunal de origen no mandó ninguna pieza.
        raise EstructuraInesperada(
            f"El panel de piezas del exhorto de {competencia} tiene encabezados y ninguna "
            "fila, en una causa que la cabecera declara exhorto. La respuesta viene truncada "
            "o la estructura cambió. No se devuelve la lista vacía porque se leería como que "
            "el tribunal de origen no despachó ninguna pieza."
        )
    return piezas


#: Cómo el panel publica el rol de la causa de origen: número, guion y año, con espacios
#: alrededor del guion. Los espacios van en el patrón porque son los que trae la respuesta
#: medida (`14988 - 2020`), no una tolerancia por si acaso.
#:
#: Se aplica con `fullmatch` y no con `search`: buscar dentro se quedaría con los primeros
#: dígitos de cualquier cosa que el sitio agregue en esa celda, y un rol truncado se ve tan
#: bien como uno correcto.
_ROL_DE_ORIGEN = re.compile(r"(\d+)\s*-\s*(\d{4})")

#: Los cuatro rótulos que el panel tiene que traer. Se busca cada uno por su nombre y no por
#: su posición: acá no hay mapeo posicional del que protegerse, que es lo que `Panel` cuida.
_ROTULOS_ORIGEN = ("corte", "libro", "rol ing", "recurso")


def parse_causa_de_origen(html_detalle: str, competencia: str = "suprema") -> CausaDeOrigen | None:
    """La causa de la Corte de Apelaciones de la que subió el recurso.

    Devuelve `None` en dos casos, los dos medidos: cuando la competencia no publica el panel, y
    cuando la causa no trae ninguno porque no subió desde una Corte de Apelaciones. Lo segundo
    es tres de dieciséis causas de suprema, no una rareza.

    Lo que sí levanta es el panel PRESENTE y sin los cuatro rótulos, que nunca se observó: lo
    que hay ahí es la identidad de OTRA causa, y media identidad no ubica ninguna. Un
    `CausaDeOrigen` con la corte y sin el rol se lee como que el sitio no publica el dato.

    No pasa por `Panel` ni por la validación posicional: no es una tabla de filas sino cuatro
    pares de rótulo y valor, con el rótulo en un `<strong>` y el valor en su cola. Es la misma
    forma que la cabecera de la causa, y por eso la búsqueda va ACOTADA al panel y no al
    documento: las dos tablas llevan la clase `table-titulos` y la cabecera de suprema publica
    su propio `Libro`, con otro valor (`Civil / 135500 - 2020` contra `Protección`). Buscar
    suelto devuelve el de la causa que se está mirando en el campo de la causa de la que viene.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.causa_de_origen is None:
        return None

    doc = html.fromstring(html_detalle)
    # Los comentarios del detalle traen copias de los valores; sin esto se leen dos veces.
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    panes = doc.xpath(f'//*[@id="{spec.causa_de_origen}"]')
    if not panes:
        # MEDIDO el 22 de agosto de 2026, sobre dieciséis causas de suprema: TRES no traen el
        # panel. No es una respuesta rota, es una causa que no subió desde una Corte de
        # Apelaciones, y las hay de sobra (exequátur, contienda de competencia, desafuero).
        #
        # Levantar acá era la conducta anterior, decidida cuando este estado no estaba medido, y
        # se llevaba puesto el detalle ENTERO de casi una de cada cinco causas de suprema. El
        # nulo dice lo que corresponde: no hay causa de origen que publicar.
        return None

    valores: dict[str, str] = {}
    for etiqueta in panes[0].xpath('.//table[contains(@class, "table-titulos")]//td/strong'):
        # Se recorta por los dos lados porque el sitio no es parejo con el espacio adelante
        # del dos puntos: esta misma respuesta escribe `Libro :` en la cabecera.
        rotulo = " ".join(etiqueta.text_content().split()).rstrip(":").strip().lower()
        valores.setdefault(rotulo, " ".join((etiqueta.tail or "").split()))

    # Decisión: el panel presente y sin los cuatro rótulos LEVANTA, no vuelve con campos nulos.
    #
    # Los dos silencios no cuestan lo mismo. Un `CausaDeOrigen` con la corte y sin el rol
    # afirma que hay una causa de origen, no dice cuál, y se lee como que el sitio no publica
    # el dato: es la mitad inútil, y es la mitad que se ve bien. Levantar se nota.
    #
    # Y el estado vacío no está medido: el sitio trae un aviso `No Existen Registros.` para
    # este panel, pero en la única respuesta guardada viene oculto con `display:none` JUNTO con
    # los cuatro datos, así que no hay con qué distinguir "esta causa no subió de una corte"
    # de "la estructura cambió". Adivinar cuál de las dos es sería exponer sin medir; el día
    # que alguien consulte una causa de suprema sin causa de origen, esto va a levantar y el
    # mensaje dice qué hay que medir.
    faltan = [r for r in _ROTULOS_ORIGEN if not valores.get(r)]
    if faltan:
        raise EstructuraInesperada(
            f"El panel {spec.causa_de_origen!r} existe y no publica {faltan}. O esta causa no "
            "subió desde una Corte de Apelaciones, y el estado vacío del panel no está medido, "
            "o la estructura cambió. No se entregan los campos en nulo: un rol sin corte no "
            "ubica ninguna causa, porque el mismo número existe en las diecisiete."
        )

    rol = _ROL_DE_ORIGEN.fullmatch(valores["rol ing"])
    if not rol:
        raise EstructuraInesperada(
            f"El panel {spec.causa_de_origen!r} publica {valores['rol ing']!r} donde va el rol "
            "de la causa de origen, y eso no es un rol. Se levanta en vez de entregarlo en "
            "nulo, porque un nulo se leería como que el sitio no lo publica y sin el rol la "
            "causa apelada no se puede buscar."
        )

    return CausaDeOrigen(
        corte=valores["corte"],
        libro=valores["libro"],
        rol=int(rol.group(1)),
        anio=int(rol.group(2)),
        recurso=valores["recurso"],
    )


def _estado_de_parte(celdas, columnas: tuple[str, ...]) -> str | None:
    """El estado de la parte, que laboral publica como icono y no como texto.

    Leerlo con `text_content()` devolvía cadena vacía en las cuatro filas medidas, y ésa se
    normalizaba a nulo. El nulo ya significa "esta competencia no publica el dato", así que el
    dato existía y se informaba como ausente: el falso negativo de siempre, en un campo chico.

    Se devuelve la clase del icono SIN interpretar. Las cuatro filas medidas traen la misma
    (`fa-check-square-o`), o sea hay un solo valor observado y no se sabe qué emite el sitio
    para los demás estados. Traducirlo a "vigente" o "notificado" sería inventar el mapa.
    """
    if "estado" not in columnas:
        return None
    celda = celdas[columnas.index("estado")]
    texto = " ".join(celda.text_content().split())
    if texto:
        return texto
    for icono in celda.iter():
        clases = (icono.get("class") or "").split()
        # `fa` y `fa-lg` son la familia y el tamaño: no dicen nada del estado.
        significativas = [c for c in clases if c.startswith("fa-") and c != "fa-lg"]
        if significativas:
            return " ".join(significativas)
    # La columna existe y no se pudo leer nada de ella. Devolver `None` acá repetiría el
    # error que esta función vino a arreglar, una capa más abajo: `None` significa "esta
    # competencia no publica el dato", y la competencia SÍ lo publica.
    raise EstructuraInesperada(
        "La columna de estado de la parte existe y no trae ni texto ni un icono reconocible. "
        "El sitio cambió cómo la publica. No se devuelve nulo porque nulo significa que la "
        "competencia no informa el dato, y ésta sí lo informa."
    )


#: Lo que el panel responde cuando la actuación ofrece georreferencia y no hay ninguna. Medido
#: sobre una de las seis actuaciones georreferenciadas de C-1156-2026.
_SIN_GEORREFERENCIA = "no existen georreferencia"

#: Los tres datos que el panel escribe como texto, con las tildes que el sitio emite.
_DATOS_GEO = re.compile(
    r"coordenada:\s*(\d{2}-\d{2}-\d{4})\s*(\d{1,2}:\d{2}).*?"
    r"Precisi[oó]n:\s*([\d.,]+).*?"
    r"Intentos:\s*(\d+)",
    re.S | re.I,
)


def parse_georreferencia(html_modal: str) -> Georreferencia:
    """Lee el panel de georreferencia de UNA actuación.

    No recibe competencia: el panel es el mismo en las cinco rutas que lo publican, y lo que
    cambia entre ellas es la ruta, no la respuesta. Eso está medido sólo en civil, así que si
    alguna difiere, lo que corresponde es que este parser levante y no que adivine.
    """
    doc = html.fromstring(html_modal)
    etree.strip_elements(doc, etree.Comment, with_tail=False)
    plano = " ".join(doc.text_content().split())

    if _SIN_GEORREFERENCIA in plano.lower():
        # No es un error: la actuación ofrecía el panel y el panel dice que no hay nada. Se
        # informa como tal, porque un error se leería como que no se pudo consultar.
        return Georreferencia(existe=False)

    valores = {
        e.get("id"): (e.get("value") or "").strip()
        for e in doc.iter("input")
        if e.get("id") in ("latitud", "longitud")
    }
    if not valores.get("latitud") or not valores.get("longitud"):
        raise EstructuraInesperada(
            "El panel de georreferencia no dice que esté vacío y tampoco trae latitud y "
            "longitud. La estructura del sitio cambió. No se devuelve una georreferencia sin "
            "coordenadas porque se leería como que la diligencia no se ubicó."
        )

    m = _DATOS_GEO.search(plano)
    if not m:
        raise EstructuraInesperada(
            "El panel de georreferencia trae coordenadas y no la fecha del dispositivo, la "
            "precisión ni los intentos. Entregar la ubicación sin cuándo se tomó ni con qué "
            "margen es la mitad del dato, y es la mitad que no permite contrastar un plazo."
        )
    fecha, hora, precision, intentos = m.groups()
    dia = _fecha(fecha.replace("-", "/"))
    if dia is None:
        # El panel trae una fecha con el formato correcto y un día que no existe, como
        # `31-02-2026`. Devolverla en nulo publicaría `existe=true` sin fecha, y esa es
        # justamente la tercera fuente por la que esta herramienta existe: sin ella no hay con
        # qué contrastar la que corre los plazos, y el nulo se leería como "el sitio no la trae".
        raise EstructuraInesperada(
            f"El panel de georreferencia trae {fecha!r} como fecha del dispositivo, que no es "
            "una fecha. Se levanta en vez de entregarla en nulo, porque un nulo se leería como "
            "que el sitio no la publica y esta es la única fecha con hora del proyecto."
        )
    # Los números y la hora, traducidos a `EstructuraInesperada` como ya se hace tres líneas
    # más arriba con la fecha. Sin esto salían crudos: `float` revienta con un separador de
    # miles ('1.234,56' queda en '1.234.56') y `time` con una hora fuera de rango, y un
    # `ValueError` desde acá no dice qué panel cambió ni que la lectura se abandonó.
    try:
        return Georreferencia(
            existe=True,
            latitud=float(valores["latitud"]),
            longitud=float(valores["longitud"]),
            precision_metros=float(precision.replace(",", ".")),
            fecha_dispositivo=dia,
            hora_dispositivo=time(*(int(x) for x in hora.split(":"))),
            intentos=int(intentos),
        )
    except ValueError as mal:
        raise EstructuraInesperada(
            f"El panel de georreferencia trae un valor que no se pudo leer ({mal}): "
            f"latitud={valores['latitud']!r}, longitud={valores['longitud']!r}, "
            f"precisión={precision!r}, hora={hora!r}, intentos={intentos!r}. Se levanta en "
            "vez de entregar la ubicación a medias, que se leería como medida."
        ) from mal


class Anexo(BaseModel):
    """Un documento que acompaña a un escrito, en el segundo canal del folio.

    Es lo que la columna `Anexo` de la Historia ofrece y hasta la versión 0.9.0 no se podía
    pedir. No es una copia de lo que entrega `Doc.`: ahí va la resolución o el escrito, y acá
    los papeles que se acompañaron, que es donde vive la prueba documental.

    Que el folio SÍ entregue un documento por el otro canal es lo que hacía invisible esta
    falta: una respuesta con documento se lee como completa mucho mejor que una fila en blanco.

    Los campos que vienen en nulo dependen del panel: cada competencia publica columnas
    distintas y no son las mismas cinco con otro nombre. Civil no publica folio, suprema no
    publica fecha y en cambio dice cuántos ejemplares hay y si el documento físico se exige.
    Un nulo significa que ESE panel no publica la columna, no que el dato no exista.
    """

    folio: str | None = Field(
        default=None,
        description="Folio de la causa al que pertenece el anexo, para volver a ubicarlo en "
        "la Historia. Sólo el panel de escritos de laboral lo publica.",
    )
    fecha: date | None = Field(
        default=None,
        description="Fecha que el panel publica para el anexo, en ISO 8601. NO es una fecha "
        "de plazos: la que corre plazos es `fecha_diligencia` de la actuación.",
    )
    descripcion: str = Field(
        default="",
        description="Qué es el documento, escrito por quien lo acompañó. Ej: 'Pasajes aéreos'. "
        "Es texto libre, no una clasificación. Sale de la columna `Referencia`, y en suprema "
        "de `Observación del Documento`, que es la que cumple ese papel ahí.",
    )
    tipo: str | None = Field(
        default=None,
        description="Cómo clasifica el sitio el documento. Ej: 'Anexo Escrito'. Sólo suprema "
        "publica la columna.",
    )
    cantidad: str | None = Field(
        default=None,
        description="Cuántos ejemplares declara el sitio, tal cual lo emite. Sólo suprema.",
    )
    documento_fisico: str | None = Field(
        default=None,
        description="Lo que suprema publica en `Docto. Físico`, sin interpretar. Medido: 'No "
        "Requerido'. Sólo suprema publica la columna.",
    )
    documento_ruta: str | None = Field(
        default=None,
        description="Qué ruta de la plataforma entrega este anexo. Sale del formulario de la "
        "fila, y esa ruta NO se ha ejecutado: lo medido es el panel que la nombra. NULO si la "
        "fila no trae formulario.",
    )
    documento_referencia: str | None = Field(
        default=None,
        description="La referencia opaca con la que se pide este anexo. Junto con "
        "`documento_ruta` es lo único que permite traerlo después.",
    )


#: Cómo se lee el panel de cada ruta de anexo medida. La clave es la ruta, porque es lo que la
#: celda de la Historia entrega en `anexo_ruta`.
#:
#: **No comparten forma.** Medidos el 22 de agosto de 2026, uno por uno, contra causas reales:
#: civil trae tres columnas y no publica folio, laboral cuatro con folio, apelaciones agrega
#: `Doc. Principal` adelante y suprema publica seis que no se parecen a ninguna de las otras.
#: Leer una con el mapa de otra corre los campos, que es como la fecha termina en la celda de
#: la descarga.
_PANELES_ANEXO: dict[str, Panel] = {
    "anexoCausaCivil.php": Panel(
        panel="anexoCausaCivil.php",
        columnas=("doc", "fecha", "descripcion"),
        encabezados=("doc.", "fecha", "referencia"),
    ),
    "anexoCausaSolicitudCivil.php": Panel(
        panel="anexoCausaSolicitudCivil.php",
        columnas=("doc", "fecha", "descripcion"),
        encabezados=("doc.", "fecha", "referencia"),
    ),
    "anexoCausaSolEscritoCivil.php": Panel(
        panel="anexoCausaSolEscritoCivil.php",
        columnas=("doc", "fecha", "descripcion"),
        encabezados=("doc.", "fecha", "referencia"),
    ),
    "anexoEscritoLaboral.php": Panel(
        panel="anexoEscritoLaboral.php",
        columnas=("doc", "folio", "fecha", "descripcion"),
        encabezados=("doc.", "folio", "fecha", "referencia"),
    ),
    "anexoRecursoApelaciones.php": Panel(
        panel="anexoRecursoApelaciones.php",
        # `Doc. Principal` es el documento del recurso mismo y no un anexo. En la fila medida
        # viene vacía y sin formulario, así que no se ofrece: nunca se vio de qué ruta cuelga.
        columnas=("doc_principal", "doc", "fecha", "descripcion"),
        encabezados=("doc. principal", "doc.", "fecha", "referencia"),
    ),
    "escritoSuprema.php": Panel(
        panel="escritoSuprema.php",
        columnas=("doc", "doc_fisico", "tipo", "cantidad", "descripcion", "documento_fisico"),
        encabezados=(
            "doc.",
            "doc. físico",
            "tipo documento",
            "cantidad",
            "observación del documento",
            "docto. físico",
        ),
    ),
}


def parse_anexos(html_modal: str, ruta: str) -> list[Anexo]:
    """Lee el panel de anexos de UN folio, con el mapa de la ruta que lo entregó.

    La ruta la trae cada actuación en `anexo_ruta`. Sin ella no se puede leer el panel: los
    cinco medidos publican columnas distintas, y elegir el mapa por competencia serviría uno
    solo de los dos que tiene civil.

    Cero filas levanta, y esa es la diferencia con notificaciones y liquidaciones, donde la
    lista vacía es un estado real de la causa. Acá no lo es: este panel sólo se pide cuando la
    actuación trajo `anexo_referencia`, o sea cuando el sitio YA dijo que hay algo. Una tabla
    vacía significa que la ruta cambió o que se pidió la equivocada.

    Está medido en este mismo canal: pedir el listado de audios por la ruta análoga a la de
    otro modal respondió 200 con la tabla vacía, que devuelta como lista se lee igual que
    "este folio no tiene anexos".
    """
    spec = _PANELES_ANEXO.get(ruta)
    if spec is None:
        raise ValueError(
            f"No está medido cómo se lee el panel {ruta!r}. Los medidos son: "
            f"{', '.join(sorted(_PANELES_ANEXO))}. Leerlo con el mapa de otro correría los "
            "campos, y la fecha caería en la celda de la descarga."
        )

    doc = html.fromstring(html_modal)
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    tablas = doc.xpath("//table")
    if not tablas:
        raise EstructuraInesperada(
            f"El panel {ruta!r} no trae ninguna tabla. La estructura del sitio cambió."
        )
    encabezados = [" ".join(th.text_content().split()).lower() for th in tablas[0].xpath(".//th")]
    _validar_encabezados(encabezados, spec.encabezados, ruta)

    anexos = []
    for fila in tablas[0].xpath(".//tr"):
        celdas = _celdas(fila)
        if len(celdas) < len(spec.columnas):
            continue
        txt = {c: " ".join(celdas[i].text_content().split()) for i, c in enumerate(spec.columnas)}
        documento = _documento_de_la_celda(celdas[spec.columnas.index("doc")])
        anexos.append(
            Anexo(
                folio=txt.get("folio"),
                fecha=_fecha(txt.get("fecha", "")),
                descripcion=txt.get("descripcion", ""),
                tipo=txt.get("tipo"),
                cantidad=txt.get("cantidad"),
                documento_fisico=txt.get("documento_fisico"),
                documento_ruta=documento[0],
                documento_referencia=documento[1],
            )
        )

    if not anexos:
        raise EstructuraInesperada(
            f"El panel {ruta!r} trae encabezados y ninguna fila. Este panel sólo se pide "
            "cuando la actuación ofreció anexos, así que cero filas no significa que el folio "
            "no tenga: significa que la respuesta cambió o que se pidió otra ruta. Devolver "
            "una lista vacía diría que el escrito se acompañó sin documentos."
        )
    return anexos


class EscritoPendiente(BaseModel):
    """Un escrito presentado que el tribunal todavía NO resuelve.

    El sitio rotula la pestaña "Escritos por Resolver" en civil y "Escritos Pendientes" en
    laboral. No es el listado de todo lo presentado: es la cola de lo que espera proveído, y
    por eso una causa con años de tramitación suele traerla vacía mientras una de esta semana
    trae dos.

    Es lo que responde "¿ya me proveyeron el escrito?", que es una pregunta distinta de la que
    responde la Historia, donde el escrito aparece cuando YA fue resuelto.
    """

    fecha_ingreso: date | None = Field(
        default=None,
        description="Cuándo ingresó el escrito, en ISO 8601. NO es una fecha de plazos: el "
        "plazo lo corre la resolución que recaiga, y todavía no la hay.",
    )
    tipo: str = Field(
        default="",
        description="Qué se pidió, como lo rotula el sitio. Ej: 'Ingreso Solicitud', 'Ingreso "
        "Exhorto', 'Designación de Martillero'.",
    )
    solicitante: str = Field(
        default="",
        description="Quién lo presentó, por su calidad procesal y no por su nombre. Ej: "
        "'Demandante'.",
    )
    referencia: str | None = Field(
        default=None,
        description="Lo que laboral publica en su columna `Referencia`. NULO en civil, que no "
        "la publica, y en laboral mientras no se vea una fila: su contenido no está medido.",
    )
    tiene_documento: bool = Field(
        default=False, description="Si la columna `Doc.` del escrito ofrece algo."
    )
    documento_ruta: str | None = Field(
        default=None,
        description="Qué ruta entrega el escrito mismo. NULO cuando la fila no trae formulario.",
    )
    documento_referencia: str | None = Field(
        default=None,
        description="La referencia opaca con la que se pide ese documento. Junto con "
        "`documento_ruta` es lo único que permite traerlo.",
    )
    tiene_anexo: bool = Field(
        default=False,
        description="Si el escrito acompañó documentos. Mismo segundo canal que en la "
        "Historia: `Doc.` trae el escrito y `Anexo` los papeles que se acompañaron.",
    )
    anexo_ruta: str | None = Field(
        default=None,
        description="A qué panel se piden esos anexos, para `obtener_anexos_escrito`. NULO "
        "cuando el escrito no trae anexo o cuando su panel no está medido.",
    )
    anexo_referencia: str | None = Field(
        default=None, description="Con qué se piden. NULO por las mismas dos razones."
    )


def parse_escritos_pendientes(
    html_detalle: str, competencia: str = "civil"
) -> list[EscritoPendiente]:
    """Los escritos presentados que el tribunal todavía no resuelve.

    La lista vacía es una respuesta y no un error: significa que no queda nada por proveer, que
    es el estado normal de una causa al día. Por eso acá NO va el guardia de cero filas que sí
    tiene la Historia.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.escritos_pendientes is None:
        raise EstructuraInesperada(
            f"No está verificado cómo se leen los escritos por resolver en {competencia}. En "
            "laboral el panel se llama distinto y publica dos columnas que civil no tiene, así "
            "que leerlo con este mapa correría los campos."
        )
    columnas = spec.escritos_pendientes.columnas
    escritos = []
    for celdas, txt in _filas_del_panel(html_detalle, spec.escritos_pendientes):
        documento = _documento_de_la_celda(celdas[columnas.index("doc")])
        anexo = _anexo_de_la_celda(celdas[columnas.index("anexo")])
        escritos.append(
            EscritoPendiente(
                fecha_ingreso=_fecha(txt["fecha_ingreso"]),
                tipo=txt["tipo"],
                solicitante=txt["solicitante"],
                referencia=txt.get("referencia"),
                tiene_documento=bool(celdas[columnas.index("doc")].xpath(".//form | .//a")),
                documento_ruta=documento[0],
                documento_referencia=documento[1],
                tiene_anexo=bool(celdas[columnas.index("anexo")].xpath(".//form | .//a")),
                anexo_ruta=anexo[0],
                anexo_referencia=anexo[1],
            )
        )
    return escritos


class CausaAgregada(BaseModel):
    """Otra causa que se ve JUNTO con ésta en la Corte Suprema.

    Es lo que la plataforma rotula "Agregados". No es la causa de origen ni un exhorto: son
    causas distintas que el tribunal ve en la misma cuenta, así que lo que ocurra en ellas puede
    resolverse el mismo día y no aparece en la historia de ésta.

    **Sus columnas salen del encabezado y ninguna fila se ha visto.** El panel vino vacío en las
    veintidós causas de suprema que se abrieron para medirlo, así que lo que trae cada celda no
    está comprobado: si una publica un formulario donde acá se lee texto, el campo va a salir
    vacío en vez de fallar.
    """

    folio: str = Field(default="", description="Folio con que la causa agregada figura acá.")
    anio: str = Field(default="", description="Año que el panel publica en columna aparte.")
    rit: str = Field(default="", description="Rol de la causa agregada.")
    tribunal: str = Field(default="", description="Tribunal de esa causa, por su nombre.")
    materia: str = Field(default="", description="Qué se litiga en ella.")
    caratulado: str = Field(default="", description="Carátula de esa causa.")
    documento_ruta: str | None = Field(
        default=None, description="Qué ruta entrega su documento, si la fila lo trae."
    )
    documento_referencia: str | None = Field(
        default=None, description="Con qué se pide. Va junto con su ruta."
    )


def parse_causas_agregadas(html_detalle: str, competencia: str = "suprema") -> list[CausaAgregada]:
    """Las causas que se ven junto con ésta. Sólo suprema publica el panel.

    La lista vacía es una respuesta: la mayoría de las causas no tiene ninguna agregada, y de
    hecho es lo único que se ha visto. Levantar acá diría que la respuesta vino rota cuando lo
    normal es justamente que no haya nada.
    """
    spec = COMPETENCIAS[competencia.lower()]
    if spec.causas_agregadas is None:
        raise EstructuraInesperada(
            f"La competencia {competencia!r} no publica el panel de causas agregadas: lo "
            f"tiene {_las_que_publican('causas_agregadas')}. Leerlo en otra devolvería una "
            "lista vacía, que se leería como que esta causa no tiene ninguna agregada."
        )
    columnas = spec.causas_agregadas.columnas
    agregadas = []
    for celdas, txt in _filas_del_panel(html_detalle, spec.causas_agregadas):
        documento = _documento_de_la_celda(celdas[columnas.index("doc")])
        agregadas.append(
            CausaAgregada(
                folio=txt["folio"],
                anio=txt["anio"],
                rit=txt["rit"],
                tribunal=txt["tribunal"],
                materia=txt["materia"],
                caratulado=txt["caratulado"],
                documento_ruta=documento[0],
                documento_referencia=documento[1],
            )
        )
    return agregadas


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
    columnas = spec.litigantes.columnas
    litigantes = [
        Litigante(
            sujeto=txt["sujeto"],
            nombre=txt["nombre"],
            rut=txt["rut"],
            persona=txt["persona"],
            abogado_defensor=txt.get("abogado_defensor") or None,
            estado=_estado_de_parte(celdas, columnas),
        )
        for celdas, txt in _filas_del_panel(html_detalle, spec.litigantes)
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
            f"La competencia {competencia!r} no publica materias: tiene el panel "
            f"{_las_que_publican('materias')}. Leerlo en otra devolvería una lista vacía, que "
            "se leería como que la causa no tiene materias."
        )
    materias = [
        Materia(
            codigo=txt["codigo"],
            glosa=txt["glosa"],
            estado=txt["estado"],
            fecha_termino=_fecha(txt["fecha_termino"]),
        )
        for _celdas, txt in _filas_del_panel(html_detalle, spec.materias)
    ]
    if not materias:
        # Una causa laboral sin materia no existe: la materia es QUÉ se litiga, y es lo que
        # el tribunal registra al ingresarla. Encabezados y cero filas es una respuesta
        # truncada o una estructura que cambió, y devolver la lista vacía publicaría "esta
        # causa no litiga nada".
        raise EstructuraInesperada(
            f"El panel de materias de {competencia} tiene encabezados y ninguna fila. Toda "
            "causa laboral tiene materia, así que la respuesta viene truncada o la estructura "
            "cambió. No se devuelve la lista vacía porque se leería como que no se litiga nada."
        )
    return materias


class DetalleCausa(BaseModel):
    """Los paneles MAPEADOS del detalle, leídos de una sola vez. No es el expediente completo.

    Decirlo es parte del contrato, porque la ausencia se lee como inexistencia. Quedan dos
    paneles sin mapear, los dos de apelaciones: los exhortos de la corte y la incompetencia. Lo
    que no está acá **no está dicho**, no está negado.

    No se mapean porque no hay qué mapear: su tabla trae dos columnas, la primera en blanco y la
    segunda con el rótulo, y en la mitad de los detalles de apelaciones el panel ni siquiera
    aparece.

    Y tres de los que SÍ se leen tienen las columnas medidas del encabezado y ninguna fila
    observada, que es otra cosa que conviene saber: `SIN_FILAS_OBSERVADAS` los nombra.

    Y dos canales que sí se pueden pedir y NO vienen incluidos, porque cuestan una petición
    aparte cada uno: los anexos de un folio, con `anexo_ruta` y `anexo_referencia` de su
    actuación, y el listado de audios de audiencia, con `audio_referencia`. Que esos campos
    vengan con valor significa que hay algo que este servidor puede traer y todavía no trajo.

    Cada campo distingue tres estados, y la diferencia entre los dos últimos es la que este
    proyecto existe para no borrar:

    - `None`: esta competencia NO publica ese panel. La pregunta no tiene respuesta acá.
    - `[]`: el panel existe y no trae filas. Es una respuesta: no hay notificaciones
      practicadas, no hay liquidaciones, no hay exhortos despachados.

    Dos paneles NO pueden venir vacíos y por eso no están en esa lista: `litigantes`, porque
    una causa sin partes no existe, y `materias`, porque una causa laboral sin materia tampoco.
    Si el sitio los devuelve sin filas se levanta en vez de publicar la lista vacía.
    - Con elementos: lo que hay.

    Devolver lista vacía en el primer caso las haría indistinguibles, y "esta competencia no lo
    informa" se leería como "no ocurrió".

    `piezas_exhorto` trae un cuarto caso que esos tres no saben decir. El panel existe en civil,
    pero sólo en las causas que SON un exhorto: "esta competencia no lo publica" y "esta causa
    no es un exhorto" son cosas distintas, y meter las dos en `None` borra justo la distinción
    que la lista de arriba protege. Por eso viaja al lado `causa_es_exhorto`, con el mismo
    oficio que `causa_encontrada`: nombrar cuál de los dos silencios es éste.

    `causa_de_origen` no es una lista, así que nunca viene en `[]`: o trae entera la causa de
    la que subió el recurso, o viene en nulo porque la competencia no publica ese panel. Un
    panel presente que no se entiende levanta, y no se degrada a campos vacíos.
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
        description="Cuánto se debe y a qué fecha. Lo publican cobranza y laboral.",
    )
    diligencias: list[Diligencia] | None = Field(
        default=None,
        description="Diligencias del ministro de fe, con su estado y quién figura a cargo. "
        "Lo publican cobranza y laboral. En la fila de cobranza medida su fecha NO es la que "
        "corre los plazos: el sitio imprime el valor cero y se entrega en nulo. En laboral no "
        "está medida.",
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
    causa_es_exhorto: bool | None = Field(
        default=None,
        description="Si ESTA causa es un exhorto: una que otro tribunal abrió acá para que se "
        "practiquen diligencias suyas. Sale de la cabecera de la causa, no de qué paneles "
        "llegaron. NULO significa que la competencia no tiene la pregunta medida, NO que la "
        "causa no lo sea: sin este campo, `piezas_exhorto` en nulo diría las dos cosas a la vez.",
    )
    audio_referencia: str | None = Field(
        default=None,
        description="Con qué se pide el listado de audios de las audiencias de esta causa, si "
        "las tiene. NULO cuando la causa no ofrece grabación y también cuando su competencia "
        "no está medida: sólo laboral lo está.\n\n"
        "Que venga con valor significa que HAY audiencia grabada, que es un dato en sí: la "
        "Historia dice que hubo audiencia, y esto dice que quedó registrada.",
    )
    causa_de_origen: CausaDeOrigen | None = Field(
        default=None,
        description="La causa de la Corte de Apelaciones desde la que subió el recurso. Es "
        "cómo se sigue la causa hacia abajo: sin ella el detalle dice que hubo apelación y no "
        "dice dónde está lo que ocurrió antes. Sólo suprema publica el panel, y en las demás "
        "viene en NULO por eso, no porque la causa no venga de ninguna parte.\n\n"
        "Su `corte` es el NOMBRE y las búsquedas piden el código: se resuelve con "
        "`listar_cortes` antes de consultarla.",
    )
    escritos_pendientes: list[EscritoPendiente] | None = Field(
        default=None,
        description="Los escritos presentados que el tribunal todavía NO resuelve. La lista "
        "vacía es una respuesta: no queda nada por proveer. NULO si la competencia no tiene "
        "medido el panel.",
    )
    causas_agregadas: list[CausaAgregada] | None = Field(
        default=None,
        description="Las causas que se ven JUNTO con ésta en la Corte Suprema. La lista vacía "
        "es lo normal y es una respuesta. NULO donde la competencia no publica el panel.",
    )
    piezas_exhorto: list[PiezaExhorto] | None = Field(
        default=None,
        description="Los trámites que el tribunal de ORIGEN despachó junto con el exhorto, o "
        "sea lo que este tribunal tuvo a la vista. NO son actuaciones de esta causa y no corren "
        "sus plazos. Viene en nulo cuando `causa_es_exhorto` no es verdadero, y ese campo dice "
        "cuál de las dos ausencias es.",
    )


class AudioAudiencia(BaseModel):
    """Un archivo de audio de una audiencia, tal como el sitio lo publica.

    Rompe el supuesto de que todo lo descargable de la plataforma es PDF: acá el archivo es un
    `.mp3`. Este servidor NO lo trae: entrega qué hay y con qué enlace, para que quien lo
    necesite lo baje y lo escuche. Un audio de audiencia son las voces de las partes, los
    testigos y el tribunal, y transcribirlo automáticamente no es lo mismo que oírlo.

    El audio viene TROCEADO por acto procesal, no en una pista única: el nombre de archivo dice
    de qué tramo es. Medido: once archivos para una sola audiencia preparatoria, del "Inicio" al
    "Fin", pasando por el llamado a conciliación y los hechos a probar.
    """

    numero: str = Field(description="El correlativo con que el sitio ordena los archivos.")
    archivo: str = Field(
        description="Nombre del archivo, tal cual. Trae el tramo de la audiencia al final, que "
        "es lo que dice de qué es la grabación. Ej: '...-05-Llamado a conciliacion.mp3'.\n\n"
        "Empieza con el RUC de la causa, así que nombrarlo completo publica ese identificador."
    )
    fecha: date | None = Field(
        default=None,
        description="Lo que el sitio publica en su columna `Fecha`. Medido: viene VACÍA en los "
        "once archivos, aunque la columna existe. La fecha de la audiencia hay que sacarla de "
        "la Historia o del propio nombre del archivo, no de acá.",
    )
    descarga_url: str = Field(
        description="Enlace directo al archivo, para abrirlo en un navegador. Este servidor no "
        "lo descarga.\n\nEl enlace lleva una referencia firmada que CADUCA: si deja de "
        "funcionar hay que volver a pedir el listado. Entregarlo tal cual al usuario es lo "
        "correcto; guardarlo para después, no."
    )


#: Con qué función abre cada competencia el listado de audios. Sólo laboral está MEDIDA: es la
#: única de cuyas causas se vio el enlace, y la única cuya respuesta se leyó.
#:
#: Se compara el nombre completo, igual que en los anexos: un prefijo mandaría la referencia de
#: una competencia a la ruta de otra, y eso no da error sino otra página.
_MODAL_AUDIO: dict[str, str] = {"listadoAudioLaboral": "audio/listadoAudio.php"}


def audio_de_la_causa(html_detalle: str) -> str | None:
    """Con qué se pide el listado de audios de esta causa, si la cabecera lo ofrece.

    Devuelve nulo cuando la causa no tiene audiencia grabada Y cuando la competencia no está
    medida: las dos son "no hay nada que pedir acá". Lo que las distingue está en la
    documentación, no en el dato, porque el sitio no publica esa diferencia.
    """
    doc = html.fromstring(html_detalle)
    etree.strip_elements(doc, etree.Comment, with_tail=False)
    for elemento in doc.iter():
        m = _REFERENCIA_EN_MODAL.match(elemento.get("onclick") or "")
        if m and m.group(1) in _MODAL_AUDIO:
            return m.group(2)
    return None


def parse_audios(html_modal: str) -> list[AudioAudiencia]:
    """Lee el listado de audios de una audiencia.

    Cero filas levanta, por lo mismo que en los anexos: este listado sólo se pide cuando el
    detalle de la causa ofreció el enlace, o sea cuando el sitio ya dijo que hay grabación. Y
    está medido que la ruta equivocada responde 200 con la tabla vacía, que devuelta como lista
    se lee igual que "esta audiencia no se grabó".

    El correlativo va en un `th` DENTRO de cada fila, no en un `td`, así que la fila trae cuatro
    celdas y cinco encabezados. Leerlo con el largo de la cabecera descartaría todas las filas.
    """
    doc = html.fromstring(html_modal)
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    tablas = doc.xpath("//table")
    if not tablas:
        raise EstructuraInesperada(
            "El listado de audios no trae ninguna tabla. La estructura del sitio cambió."
        )
    encabezados = [
        " ".join(th.text_content().split()).lower() for th in tablas[0].xpath(".//thead//th")
    ]
    _validar_encabezados(encabezados, _ENCABEZADOS_AUDIO, "listado de audios")

    audios = []
    for fila in tablas[0].xpath(".//tr"):
        celdas = _celdas(fila)
        numero = fila.xpath("./th")
        # Una celda MENOS que encabezados: el correlativo viaja en el `th` de la fila. Exigir
        # el largo de la cabecera, que es lo que hacen los demás paneles, descarta las once.
        if len(celdas) < len(_ENCABEZADOS_AUDIO) - 1 or not numero:
            continue
        enlaces = [
            a.get("href", "") for a in fila.iter("a") if "action=download" in (a.get("href") or "")
        ]
        if not enlaces:
            # Sin enlace no hay nada que entregar, y una fila sin él se leería como un archivo
            # disponible que después no se puede abrir.
            raise EstructuraInesperada(
                "Una fila del listado de audios no trae enlace de descarga. Entregarla igual "
                "diría que el archivo está disponible, y no habría con qué pedirlo."
            )
        audios.append(
            AudioAudiencia(
                numero=" ".join(numero[0].text_content().split()),
                archivo=" ".join(celdas[3].text_content().split()),
                fecha=_fecha(" ".join(celdas[2].text_content().split())),
                descarga_url=f"{BASE_SITIO}/{enlaces[0].removeprefix('./')}",
            )
        )

    if not audios:
        raise EstructuraInesperada(
            "El listado de audios trae encabezados y ninguna fila. Sólo se pide cuando el "
            "detalle ofreció el enlace, así que cero filas no significa que la audiencia no se "
            "haya grabado: significa que la respuesta cambió o que se pidió otra ruta."
        )
    return audios


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
    mostrado: bool = Field(
        description="Si es el que ESTA respuesta ya trae desplegado, o sea el que no hace "
        "falta volver a pedir."
    )


def parse_cuadernos(html_detalle: str) -> list[Cuaderno]:
    """Cuadernos disponibles en el detalle.

    El detalle sólo despliega la Historia de UN cuaderno. Una causa con cuaderno de
    apremio esconde ahí actuaciones que no aparecen en el principal: leer sólo el que
    viene por defecto devuelve una respuesta completa en apariencia a la que le faltan
    justamente las diligencias que interesan.
    """
    doc = html.fromstring(html_detalle)
    return [
        Cuaderno(
            nombre=" ".join(op.text_content().split()),
            referencia=op.get("value", ""),
            # El desplegable marca el que la respuesta trae puesto, y eso ahorra una petición
            # por causa: sin la marca, el recorrido vuelve a pedir el que ya está en la mano.
            # Medido en las dos fixtures de C-1156-2026: `c1156_principal` marca el principal
            # y `c1156_apremio` marca el de apremio, o sea la marca sigue a la respuesta y no
            # al orden de la lista.
            mostrado=op.get("selected") is not None,
        )
        # Por prefijo, porque el sitio le pone otro identificador en cobranza: `selCuadernoCob`.
        # Leer sólo `selCuaderno` devolvía lista vacía en TODA causa de cobranza, y una lista
        # vacía acá dice "esta causa tiene un solo cuaderno": la de dos se leía a medias y salía
        # con cara de completa, que es la regla 4 exacta.
        #
        # Por prefijo y no por una lista de los dos medidos, que sería lo natural en este
        # proyecto: acá los dos errores no cuestan lo mismo. Un sufijo nuevo que la lista no
        # nombre vuelve a producir el fallo silencioso de arriba; uno que el prefijo tome de más
        # termina pidiendo una página que `_es_el_cuaderno_pedido` no reconoce, y eso se levanta.
        # Medido sobre las fixtures: los ÚNICOS `<select>` con identificador que emiten estas
        # páginas son estos dos.
        for op in doc.xpath('//select[starts-with(@id, "selCuaderno")]/option')
        if op.get("value")
    ]


#: Cuántos segundos declara durar la referencia del LISTADO. Medido el 24 de agosto de 2026
#: sobre `CausaEncontrada.referencia`: es un JWT y su `exp - iat` da 1.800 exactos.
#:
#: Lo medido es lo que el token DECLARA, no lo que la plataforma hace: que rechace justo ahí no
#: se probó. Y es de este token y no de los otros. Sobre `documento_referencia` sigue siendo
#: verdad que cuánto dura no se midió, así que su prosa no se deriva de acá: aplanar las dos
#: haría la documentación más falsa mientras se siente limpieza.
SEGUNDOS_DECLARADOS_POR_LA_REFERENCIA = 1800


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
        description=f"Identificador opaco para pedir el detalle. Declara durar "
        f"{SEGUNDOS_DECLARADOS_POR_LA_REFERENCIA // 60} minutos; no se construye ni se guarda, "
        "se usa en el acto."
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
    #: En civil sí: la columna `Trámite` dice "Actuación Receptor". En cobranza NO, y la razón
    #: no es que la Historia no las nombre. Medido sobre una respuesta real: tres filas de
    #: `historiaCob` dicen `Actuacion - Receptor`, sin tilde y con guion, y ninguna trae fecha
    #: de diligencia. Las diligencias de verdad viven en `diligenciaCob`, con estructura propia
    #: (`Estado Diligencia`, `Tipo Diligencia`, `Destinatario`, `Responsable`).
    #:
    #: O sea leerlas desde Historia no daría una lista vacía sino una PARCIAL y sin el dato que
    #: se busca. `TRAMITE_RECEPTOR` tampoco las reconoce, por la tilde y el guion, y no se
    #: amplía: con la competencia rechazada antes, esa rama no podría ejecutarse.
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
    #: Si el rol que el listado publica NO lleva nada adelante, ni letra ni libro.
    #:
    #: Medido: suprema devuelve `999999-2020` a secas, mientras civil, laboral y cobranza usan
    #: una letra y apelaciones y penal el libro. Son tres formas y `rol_con_libro` sólo separa
    #: dos, así que el esquema decía "Letra del rol" también donde no va ninguna.
    #:
    #: Importa porque el modelo manda lo que el esquema le pida: una letra en suprema deja el
    #: rol esperado en `X-999999-2020`, ninguna fila calza, y el error habla de revisar `tipo`
    #: sin decir que ahí va vacío.
    rol_sin_prefijo: bool
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
    #: Cómo leer las piezas del exhorto, o `None` mientras no se haya medido.
    #:
    #: Declararlo es además declarar que está medido qué pone la cabecera en `Proc.` cuando la
    #: causa es un exhorto: `causa_es_exhorto` se apoya en el mismo campo. Van juntos porque
    #: leer el panel sin poder contrastarlo contra la cabecera devuelve la ambigüedad que
    #: `causa_es_exhorto` existe para deshacer.
    piezas_exhorto: Panel | None = None
    #: El `id` del panel donde la competencia publica la causa de la que subió el recurso, o
    #: `None` si no lo publica.
    #:
    #: Va como `id` suelto y no como `Panel`, que es el único caso de la tabla: ese panel no es
    #: una tabla de filas sino cuatro pares de rótulo y valor, así que no hay encabezados que
    #: comparar ni mapeo posicional del que protegerse. Declararle columnas vacías para que
    #: calzara el tipo habría hecho pasar por validado algo que nadie valida.
    causa_de_origen: str | None = None
    #: Cómo leer su panel de diligencias del ministro de fe, o `None` si no lo publica.
    #:
    #: Es distinto de `receptor`: aquél dice que el sitio EXPONE actuaciones de ministro de fe,
    #: y esto dice que están medidas las columnas del panel donde viven. Cobranza tiene los dos
    #: en verdadero y `receptor_en_historia` en falso, que es la combinación que describe su
    #: situación real: las diligencias existen, se leen, y no salen de la Historia.
    diligencias: Panel | None = None
    #: Cómo leer los escritos que el tribunal todavía no resuelve, o `None` mientras no se haya
    #: medido. Mismo default y por la misma razón que los dos de arriba.
    escritos_pendientes: Panel | None = None
    #: Cómo leer las causas agregadas a ésta, o `None` si la competencia no las publica.
    causas_agregadas: Panel | None = None


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
        causas_agregadas=CAUSAS_AGREGADAS_SUPREMA,
        materias=None,
        liquidaciones=None,
        notificaciones=None,
        rol_con_libro=False,
        rol_sin_prefijo=True,
        campos_rit={"conTipoBus": "0"},
        historia=HISTORIA_SUPREMA,
        receptor=False,
        receptor_en_historia=False,
        acota_por=None,
        causa_de_origen="corteApelaciones",
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
        rol_sin_prefijo=False,
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
        escritos_pendientes=ESCRITOS_CIVIL,
        piezas_exhorto=PIEZAS_EXHORTO_CIVIL,
        liquidaciones=None,
        notificaciones=NOTIFICACIONES_CIVIL,
        rol_con_libro=False,
        rol_sin_prefijo=False,
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
        diligencias=DILIGENCIAS_LABORAL,
        escritos_pendientes=ESCRITOS_LABORAL,
        liquidaciones=LIQUIDACIONES_LABORAL,
        notificaciones=NOTIFICACIONES_LABORAL,
        rol_con_libro=False,
        rol_sin_prefijo=False,
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
        rol_sin_prefijo=False,
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
        diligencias=DILIGENCIAS_COBRANZA,
        notificaciones=NOTIFICACIONES_COBRANZA,
        rol_con_libro=False,
        rol_sin_prefijo=False,
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
    # El aviso viene con las tildes escapadas al estilo de JavaScript. Se traducen SÓLO las
    # secuencias bien formadas, en vez de pasar la cadena entera por `unicode_escape`, que
    # tiene dos modos de falla medidos: con una tilde literal devuelve mojibake
    # ('bÃºsqueda'), y con una secuencia truncada levanta `UnicodeDecodeError` crudo. Ese
    # error saldría desde `_bloqueo_encubierto`, que mira TODAS las respuestas, así que un
    # aviso mal formado tumbaría la petición sin clasificarse como nada.
    return _ESCAPE_JS.sub(lambda e: chr(int(e.group(1), 16)), m.group(1))


#: Una secuencia `\uXXXX` bien formada, que es como el sitio escapa las tildes de sus avisos.
_ESCAPE_JS = re.compile(r"\\u([0-9a-fA-F]{4})")


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
