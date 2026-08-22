"""Cliente HTTP de la consulta pública de causas.

Solo lectura. No existe código, ni siquiera desactivado, que ingrese, modifique o elimine
información en los sistemas del Poder Judicial.

Sobre el ritmo de las consultas: las condiciones de uso de la Oficina Judicial Virtual
no prohíben el acceso programático, pero su cláusula CUARTA prohíbe "dañar, inutilizar,
sobrecargar, deteriorar el Portal o impedir su normal utilización". El intervalo mínimo
entre peticiones es la implementación de esa cláusula, no una cortesía: no se relaja.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import metadata as _metadata_instalada
from importlib.metadata import version as _version_instalada
from io import BytesIO
from typing import TypeVar

import httpx
from pydantic import BaseModel, Field
from pypdf import PdfReader

from .parser import (
    BASE_SITIO,
    COMPETENCIAS,
    Actuacion,
    Anexo,
    AudioAudiencia,
    CausaEncontrada,
    Corte,
    DetalleCausa,
    EstructuraInesperada,
    Georreferencia,
    Liquidacion,
    Notificacion,
    Tribunal,
    actuaciones_receptor,
    audio_de_la_causa,
    causa_es_exhorto,
    es_aviso_de_captcha,
    es_sin_resultados,
    leer_aviso,
    parse_anexos,
    parse_audios,
    parse_causa_de_origen,
    parse_cuadernos,
    parse_exhortos,
    parse_georreferencia,
    parse_historia,
    parse_liquidaciones,
    parse_litigantes,
    parse_materias,
    parse_notificaciones,
    parse_piezas_exhorto,
    parse_resultados,
    siguiente_pagina,
    total_declarado,
)

#: La versión que se identifica ante el Poder Judicial, leída del paquete instalado.
#:
#: Estaba escrita a mano en el User-Agent y se quedó en `0.1` mientras el paquete iba en otra:
#: cada petición se identificaba como una versión que no era. No es cosmético. La regla 2 de
#: este proyecto exige un agente identificable, y ese header es la única forma que tiene la
#: institución de saber qué software la está consultando y a quién reclamarle.
#:
#: Cuando el paquete no está instalado (un árbol de fuentes suelto) se dice `desconocida` en
#: vez de inventar un número: un agente honesto vale más que uno preciso y falso.
try:
    VERSION = _version_instalada("mcp-pjud")
    #: La misma descripción que declara el paquete. El servidor MCP la publica en
    #: `server/discover`, y escribirla a mano ahí sería una segunda copia del mismo texto que
    #: alguien tendría que acordarse de cambiar en los dos lados.
    DESCRIPCION = _metadata_instalada("mcp-pjud")["Summary"]
except PackageNotFoundError:  # pragma: no cover - sólo fuera de una instalación
    VERSION = "desconocida"
    DESCRIPCION = ""

#: El origen del sitio. La definición vive en `parser`, que es quien arma el enlace de
#: descarga de un audio y no puede importar de acá. Reexportada para no escribirla dos veces.
BASE = BASE_SITIO
PORTADA = "https://www.pjud.cl/"

#: Enlace que la propia institución publica en la portada de www.pjud.cl como acceso
#: público a la consulta de causas. No requiere Clave Única.
ENTRADA = f"{BASE}/includes/sesion-consultaunificada.php"

#: Intervalo sostenido: a la larga no sale más de una petición cada 5 segundos. Es la
#: cláusula CUARTA implementada en código, no una constante de rendimiento.
INTERVALO_MINIMO = 5.0

#: Cuántas peticiones pueden salir juntas antes de que el ritmo sostenido empiece a mandar.
#:
#: Existe porque el ritmo se le debe al portal, y al portal le da lo mismo cómo se reparten
#: las peticiones dentro de un minuto: le importa cuántas recibe. Una consulta de actuaciones
#: son cinco peticiones encadenadas, y con un intervalo plano tardaba veinticinco segundos
#: para responder una sola pregunta.
#:
#: Hay que decir qué se cambió, porque contradice una decisión anterior de este mismo
#: proyecto: se habían descartado las librerías de control de ritmo justo por implementar un
#: balde de fichas que permite ráfagas. Lo que cambió no es la opinión sobre la librería sino
#: la especificación: antes era "al menos 5 segundos entre peticiones consecutivas" y ahora
#: es "a lo más una cada 5 segundos en régimen, con una ráfaga acotada al principio". El
#: promedio sostenido es el mismo; lo que se permite es que las primeras salgan juntas.
RAFAGA_MAXIMA = 4

#: Cuánto tarda de verdad el buscador de fallos, medido, y cuánto la página del mismo host.
#: Son las cifras que justifican `ESPERA_MAXIMA`, y viven acá porque se citan en tres archivos:
#: `tests/test_documentacion.py` verifica que ninguno quede con la vieja.
SEGUNDOS_BUSQUEDA_MEDIDOS = 47.8
SEGUNDOS_PAGINA_MEDIDOS = 4.3

#: El PEOR caso medido, que es el número que de verdad manda para el timeout. La cifra de
#: arriba era una sola muestra, y tomarla por techo costó tres diagnósticos equivocados
#: seguidos sobre las mismas tres consultas: primero "la plataforma está caída", después
#: "esas consultas no terminan", y recién a la tercera, midiendo con paciencia de 300
#: segundos, aparecieron en 81,2 s, 102,0 s y 38,7 s.
#:
#: Y la lección se repitió el mismo día: esta constante se puso en 115,6 s con la primera
#: consulta al buscador de Cortes de Apelaciones, y la segunda tardó 177,0 s. O sea la muestra
#: nueva tampoco era el techo. Por eso `ESPERA_MAXIMA` no se calcula pegado a este número.
#:
#: La lección no es el número: es que una muestra no es un techo. Si mañana aparece una más
#: lenta, sube esta constante en vez de concluir que la consulta no funciona.
SEGUNDOS_BUSQUEDA_PEOR_MEDIDO = 177.0

#: Cuánto se espera una respuesta antes de darla por perdida.
#:
#: Medido, y por eso es tan alto: una búsqueda del buscador de fallos por rol y año tardó
#: `SEGUNDOS_BUSQUEDA_MEDIDOS` en devolver el primer byte, contra `SEGUNDOS_PAGINA_MEDIDOS`
#: que tarda la página del mismo host. Es una consulta Solr con facetas sobre más de un
#: millón de documentos, así que la lentitud es del trabajo y no de la red.
#:
#: Con los 30 segundos que había antes, cuatro de cada cinco búsquedas morían por timeout y
#: eso se leía como "la plataforma está caída". Cortar antes de tiempo no protege a nadie: el
#: servidor igual hizo el trabajo, y quien consulta se queda sin el dato y con un diagnóstico
#: equivocado.
#:
#: Con los 90 que vinieron después pasó lo mismo en chico y costó más caro, porque el error
#: era más creíble: tres citas de Corte Suprema fallaban SIEMPRE, en todas las corridas, y esa
#: consistencia se leyó como "esas consultas no terminan". Terminaban en 81, 102 y 39
#: segundos. La de 102 era la única que el tope mataba, y con ella se dieron por perdidas las
#: tres. El valor de ahora es el doble del peor medido, `SEGUNDOS_BUSQUEDA_PEOR_MEDIDO`.
#:
#: Lo que cuesta: `_req` sostiene el turno durante toda la petición, así que una colgada frena
#: al resto del proceso hasta cuatro minutos. Se acepta por dos razones. La primera es no
#: soltar el turno antes de clasificar la respuesta, que es lo que permitía a una segunda
#: llamada consultar después de que la primera ya recibió un bloqueo. La segunda es que en
#: este proyecto esperar de más es barato y cortar de menos es caro: una espera larga molesta,
#: y un falso "no se encontró" se lee como que la causa no existe.
ESPERA_MAXIMA = 240.0

#: El balde es del proceso, no del cliente. `server.py` abre un `PjudClient` nuevo en cada
#: llamada de herramienta, así que un contador por instancia se reinicia solo y deja pasar la
#: primera petición de cada llamada sin esperar. La cláusula CUARTA habla del portal, no del
#: objeto.
_FICHAS = float(RAFAGA_MAXIMA)
_ULTIMA = 0.0
_TURNO = threading.Lock()

#: Motivo del bloqueo, si el Poder Judicial ya nos rechazó. Es del proceso y a propósito no
#: se limpia: la detención total significa que no se vuelve a consultar hasta que una persona
#: revise si la IP quedó restringida y reinicie el servidor.
#:
#: Se evaluó llevarlo por host, con el argumento de que un bloqueo consultando jurisprudencia
#: no debería dejar sin consulta de causas a quien tiene un plazo corriendo. Se descartó al
#: medir quién bloquea: los dos hosts responden con la cookie `TS<hex>` de F5 BIG-IP, o sea
#: están detrás del mismo cortafuegos, y el 403 llega antes de la aplicación. Seguir
#: consultando el otro host después de un rechazo es exactamente lo que convierte un bloqueo
#: temporal en una IP baneada, que es el riesgo que la regla de detención total existe para
#: evitar. Ante la duda, la respuesta correcta es parar y avisar.
_BLOQUEADO: str | None = None

#: Errores de httpx que se leen como rechazo y no como plataforma lenta. Un cortafuegos que
#: rechaza a nivel de red no manda un 403: corta la conexión, y eso llega como `ReadError` o
#: `ConnectError`. Sin esto, ese rechazo se propagaba como error de red y la detención total
#: no se activaba, así que quien envolviera las llamadas en un reintento seguía golpeando un
#: cortafuegos que ya lo rechazó. Reportado en la incidencia #34.
#:
#: `TimeoutException` queda FUERA a propósito, y es la parte que decide el corte: está medido
#: que una búsqueda en el buscador de fallos tarda hasta 177 segundos, así que armar la
#: detención total con un timeout dejaría el servidor detenido por una consulta lenta y
#: normal. Eso sería negarse el servicio a uno mismo, no cuidar la plataforma.
#:
#: `ConnectError` sí queda dentro, y es una decisión con costo: una wifi caída produce la
#: misma clase que un cortafuegos que rechaza el SYN. Se prefiere detener y que una persona
#: mire, porque el error opuesto es el que termina en una IP baneada. El mensaje dice que no
#: se puede distinguir, para que quien lo lea sepa qué revisar.
_RECHAZO_DE_CONEXION = (httpx.NetworkError, httpx.RemoteProtocolError)

#: La marca que F5 BIG-IP APM pone en su desafío. Viene con HTTP 200 y antes de la
#: aplicación, así que ni el código de estado ni `_SENAL_CAPTCHA`, que busca palabras en un
#: aviso de la aplicación, lo ven pasar.
_MARCA_APM = "APM_DO_NOT_TOUCH"


#: Cuántas páginas de resultados se recorren como máximo. La plataforma devuelve 100 por
#: página, así que el valor por defecto cubre mil causas: más que cualquier consulta
#: razonable, y bajo el intervalo de 5 segundos son unos 50 segundos.
#:
#: Existe para que una búsqueda demasiado amplia no se convierta en un barrido. Al
#: alcanzarlo se levanta `ResultadosTruncados` en vez de devolver una lista recortada en
#: silencio, que se leería como "no hay más".
PAGINAS_MAXIMAS = 10

#: Campos que la plataforma vuelve a emitir distintos en cada render de la misma fila. Se
#: entregan igual, porque son lo único que permite pedir el documento o el detalle, pero NO
#: cuentan para decidir si dos filas son la misma cosa.
#:
#: Medido: el mismo exhorto de C-1156-2026 llega con una referencia en el cuaderno principal y
#: otra en el de apremio. Deduplicar incluyéndolas informaba dos exhortos donde hay uno.
_VOLATILES = {"referencia", "documento_referencia"}


#: Competencias cuyas búsquedas están verificadas contra el sistema real. La tabla de cómo
#: leer sus resultados vive en `parser.COMPETENCIAS`; ésta dice cuáles se exponen.
#:
#: Están separadas a propósito: saber leer una competencia y haberla probado son cosas
#: distintas, y exponer la primera como si fuera la segunda es adivinar.
#: Verificado el 17 de agosto de 2026 buscando una causa real de cada una y comprobando que
#: las columnas del listado calzan con lo que `parser.COMPETENCIAS` declara.
#:
#: En `penal` el tipo de causa va como CÓDIGO NUMÉRICO y no como letra ni como palabra: con
#: `conTipoCausa="1"` aparece `Ordinaria-528-2017`, y con `"Ordinaria"`, `"O"` o vacío el
#: listado vuelve vacío. Además exige `radio-groupPenal` (1 por RIT, 2 por RUC) y el código de
#: tribunal, que se pide a `combosJSON/leeTrib.php` por POST y en la raíz, no bajo el prefijo.
#:
#: `suprema` y `apelaciones` entraron el 17 de agosto de 2026, y lo que las bloqueaba no era
#: ningún parámetro exótico: faltaba `radio-group`, el radio RIT/RUC del formulario. Las otras
#: cuatro competencias lo toleran ausente, así que el hueco no se veía. Se dan por verificadas
#: sus CUATRO búsquedas, medidas una por una, no sólo la de rol.
#:
#: Verificar la búsqueda no verifica el detalle: las dos tienen `historia=None` en
#: `parser.COMPETENCIAS`, así que pedirles actuaciones se rechaza en vez de adivinar el panel.
#: Es la misma separación que hizo falta en cobranza, donde la búsqueda andaba y las
#: actuaciones no vivían donde el código creía.
MODULOS: set[str] = {"civil", "laboral", "cobranza", "penal", "suprema", "apelaciones"}
#: Competencias cuyo parámetro de acotación ES el tribunal, o sea aquellas donde un listado de
#: tribunales sirve para algo. Sale de la tabla y no de una lista escrita a mano.
CON_TRIBUNAL = frozenset(n for n in MODULOS if COMPETENCIAS[n].acota_por == "tribunal")

#: Cuántas Cortes de Apelaciones devolvió `combosJSON/leeCorte.php` el 20 de agosto de 2026.
#: Vive acá y no en la prosa porque la referencia lo cita y un número escrito a mano en dos
#: lugares queda viejo en uno de los dos.
CORTES_MEDIDAS = 17


#: Con qué parámetro se pide cada documento, por competencia y por ruta.
#:
#: Sale de las respuestas guardadas y no de una lista escrita de memoria: cada formulario del
#: detalle trae su `action` y su único campo oculto, y `tests/test_client.py` vuelve a
#: derivarla de las fixtures para que el día que la plataforma renombre un parámetro esto se
#: entere en vez de pedir el documento con un nombre muerto y recibir una página de error.
#:
#: La tabla es además la LISTA BLANCA de rutas, y ésa es su otra mitad. `documento_ruta` llega
#: desde el modelo, o sea desde texto que este servidor no controla: interpolarla sin
#: verificarla convertiría la herramienta en un proxy capaz de pedir cualquier `.php` del
#: sitio, que es otra cosa que entregar un documento de una causa.
#:
#: Va por competencia y no por ruta a secas porque `docCertificadoEscrito.php` existe en tres
#: módulos, y una tabla plana dejaría pedir el de civil bajo el prefijo de cobranza.
#:
#: `penal` no aparece: su detalle no emite ningún formulario de documentos.
#: El modal de georreferencia de cada competencia. Sale del JavaScript de la plataforma, que
#: declara seis rutas: una por competencia más una unificada que este proyecto no usa, porque
#: la referencia viene de una fila que ya sabe de qué competencia es.
#:
#: Están las cinco que el sitio declara, incluida `penal`, porque esta tabla dice qué ruta usa
#: cada una y no cuáles se ofrecen. Qué se ofrece se deriva de la tabla de competencias, más
#: abajo: `suprema` no publica la columna en su Historia y `penal` no tiene Historia medida, así
#: que para las dos no puede existir una referencia que pedir. Escribirlo a mano acá dejaba a
#: `penal` anunciada como opción válida y siempre en error.
_RUTAS_GEORREFERENCIA: dict[str, str] = {
    "civil": "civil/modal/geoReferenciaCivil.php",
    "cobranza": "cobranza/modal/geoReferenciaCobranza.php",
    "laboral": "laboral/modal/geoReferenciaLaboral.php",
    "apelaciones": "apelaciones/modal/geoReferenciaApelaciones.php",
    "penal": "penal/modal/geoReferenciaPenal.php",
}

#: Las que de verdad pueden entregar una georreferencia: publican la columna en su tabla de
#: Historia Y tienen ruta declarada. Sale de las dos fuentes y no de una lista escrita a mano.
GEORREFERENCIA: dict[str, str] = {
    n: ruta
    for n, ruta in _RUTAS_GEORREFERENCIA.items()
    if (h := COMPETENCIAS[n].historia) is not None and "georref" in h.columnas
}

#: Dónde vive el listado de audios de audiencia, y con qué se pide. Medido el 22 de agosto de
#: 2026 sobre una causa laboral: 200, once archivos troceados por acto procesal.
#:
#: Cuelga de la RAÍZ y no del prefijo `ADIR_`, al revés que todos los demás modales. Construirla
#: por analogía con ellos devuelve 200 con la tabla vacía, o sea "esta causa no tiene audios".
AUDIO_RUTA = "audio/listadoAudio.php"
AUDIO_CAMPO = "dtaAudio"

#: Dónde vive el panel de anexos de cada competencia, con el parámetro que espera. Sólo
#: `laboral` está MEDIDA: el 22 de agosto de 2026, sobre T-196-2026, la ruta respondió 200 con
#: dos anexos y sus formularios de descarga.
#: Los paneles de anexo MEDIDOS, por competencia y ruta, con el parámetro que espera cada uno.
#: Misma forma que `DOCUMENTOS` y por la misma razón: una competencia tiene varios y no
#: comparten parámetro.
#:
#: Medidos el 22 de agosto de 2026, uno por uno, contra causas reales. El JavaScript del sitio
#: nombra dieciocho rutas de anexo repartidas en las seis competencias; acá van las que se
#: ejecutaron y respondieron con filas.
#:
#: Las que faltan no se arman por analogía. Cada una nombra su parámetro distinto
#: (`dtaAnexCau`, `dtaCausaAnex`, `dtaOficiese`, `dtaRequierase`...) y pedir la ruta
#: equivocada no da error: da otra página. Está medido en este mismo canal, con el listado de
#: audios, que por la ruta análoga respondió 200 con la tabla VACÍA, o sea con la forma exacta
#: de "esta causa no tiene nada".
ANEXOS: dict[str, dict[str, str]] = {
    "civil": {"anexoCausaSolicitudCivil.php": "dtaCausaAnex"},
    "laboral": {"anexoEscritoLaboral.php": "dtaAnex"},
    # El sitio la llama "Escrito" y no "Anexo", y su panel publica seis columnas que no se
    # parecen a las de nadie: tipo de documento, cantidad y si el ejemplar físico se exige. Es
    # el mismo canal igual, porque es lo que abre la columna `Anexo` de su Historia.
    "suprema": {"escritoSuprema.php": "dtEsc"},
}

#: Paneles de anexo MEDIDOS que todavía no se pueden pedir, porque la competencia que los usa
#: no tiene detalle mapeado. Los dos salieron 200 con filas el 22 de agosto de 2026, sobre una
#: causa penal de 2024: uno con cuatro anexos de la demanda (carnet, certificados) y otro con
#: tres del escrito.
#:
#: Están acá y no en `ANEXOS` porque no hay de dónde sacar su referencia: las causas penales se
#: abren por `unificado/modal/causaUnificado.php`, cuyo detalle no está mapeado. Ofrecerlos
#: sería una herramienta cuyo parámetro nadie puede conseguir.
ANEXOS_MEDIDOS_SIN_EXPONER: dict[str, str] = {
    "anexoDemandaUnificado.php": "dtaAnex",
    "anexoEscritoUnificado.php": "dtaAnex",
    # Éstos dos respondieron con filas y tampoco se exponen, por la misma razón y no por la
    # misma causa: su referencia NO vive en la celda de un folio, así que `anexo_ruta` nunca los
    # va a entregar.
    #
    # `anexoCausaCivil` cuelga de la cabecera, en "Anexos de la causa", o sea es del expediente
    # y no de un escrito. `anexoRecursoApelaciones` vive en el panel `recursoApe`, que es otro
    # panel del detalle y no está mapeado.
    #
    # Se midieron igual y la medición queda escrita: lo que falta para ofrecerlos no es la ruta
    # sino de dónde sacar la referencia.
    "anexoCausaCivil.php": "dtaAnexCau",
    "anexoRecursoApelaciones.php": "dtaAnexRec",
}

DOCUMENTOS: dict[str, dict[str, str]] = {
    "civil": {
        # La entrega el formulario de cada fila de los dos paneles de anexo de civil.
        "anexoDocCivil.php": "dtaDoc",
        "docu.php": "valorEncTxtDmda",
        "docuN.php": "dtaDoc",
        "docuS.php": "dtaDoc",
        "newebookcivil.php": "dtaEbook",
        "docCertificadoDemanda.php": "dtaCert",
        "docCertificadoEscrito.php": "dtaCert",
    },
    "cobranza": {
        "docuCobranza.php": "dtaDoc",
        "docDemandaCobranza.php": "valorDocDmda",
        "docLiquidacionCobranza.php": "valorLiq",
        "docOficioCobranza.php": "dtaDocOf",
        "newebookcobranza.php": "dtaEbook",
        "docCertificadoEscrito.php": "dtaCert",
    },
    "laboral": {
        # Medida el 22-08-2026: la entrega el formulario de cada fila del panel de anexos.
        "docAnexoLaboral.php": "dtaDoc",
        "docReformadoLaboral.php": "valorRef",
        "docReformadoEscritoLaboral.php": "valorRefEsc",
        "newebooklaboral.php": "dtaEbook",
        "docCertificadoDemanda.php": "dtaCert",
        "docCertificadoEscrito.php": "dtaCert",
    },
    "apelaciones": {
        "anexoDocRecursoApelaciones.php": "dtaDoc",
        "docCausaApelaciones.php": "valorDoc",
        "newebookapelaciones.php": "dtaEbook",
    },
    "suprema": {
        "docEscritosSuprema.php": "dtaDoc",
        "docCausaSuprema.php": "valorFile",
        "newebooksuprema.php": "dtaEbook",
    },
}

#: Cuántos caracteres puede gastar UNA respuesta de este servidor, y de dónde sale el número.
#:
#: No es una medición de PDF: este proyecto no ha pedido ninguno todavía, así que inventarle
#: un tamaño típico sería justo lo que las reglas prohíben. Es una DECISIÓN, y su magnitud
#: sale del precedente que el propio proyecto ya fijó por el mismo motivo: `JurisClient.texto`
#: se separó de la búsqueda porque una sentencia de trece páginas son unos veinticinco mil
#: caracteres, y devolver diez con cada búsqueda serían doscientos cincuenta mil. Ése es el
#: techo que este servidor ya acepta gastar de una vez en la conversación de quien consulta.
CARACTERES_DE_UNA_RESPUESTA = 25_000

#: Hasta qué tamaño un documento viaja DENTRO de la respuesta, en bytes.
#:
#: Lo único exacto acá es la aritmética: base64 son cuatro caracteres por cada tres bytes, así
#: que un documento de N bytes ocupa 4N/3 caracteres en la respuesta. El límite es el mayor N
#: que cabe en `CARACTERES_DE_UNA_RESPUESTA`.
#:
#: Deja el enlace como el caso normal y el contenido embebido como la excepción, y eso es
#: deliberado. Equivocarse hacia el enlace cuesta una lectura más (`resources/read`, que el
#: cliente hace sólo si de verdad lo necesita); equivocarse hacia el contenido gasta contexto
#: del abogado y eso no se devuelve.
LIMITE_EMBEBIDO = CARACTERES_DE_UNA_RESPUESTA * 3 // 4

#: Los cinco primeros bytes de todo PDF. Los seis endpoints de documentos que la plataforma
#: emite marcan sus enlaces con el icono de PDF, así que cualquier otra cosa que llegue por
#: ahí no es el documento: es una página de error, un aviso o una sesión vencida. Entregarla
#: en base64 como si fuera la resolución es el falso positivo que la regla 4 existe para
#: evitar, y encima uno que nadie nota, porque el cliente ve un archivo y no su contenido.
_MAGIA_PDF = b"%PDF-"


#: Lo que una lectura del detalle devuelve por fila. `_recorrer_cuadernos` sirve a dos
#: (actuaciones y notificaciones) y sin esto quedaba anotado con una sola: el chequeador de
#: tipos avisó al agregar la segunda, que es para lo que está.
_Fila = TypeVar("_Fila", Actuacion, Notificacion, Liquidacion)


class ResultadosTruncados(Exception):
    """La búsqueda excedió el tope de páginas.

    Se levanta en vez de devolver la lista parcial, porque una lista recortada en silencio
    se lee como "no hay más resultados", y en este proyecto un falso negativo es el error
    que se busca evitar.
    """


class PjudBloqueado(Exception):
    """El servidor rechazó la consulta, o el sitio dejó de ser reconocible.

    Una respuesta bloqueada llega como 403 o 429; si en cambio interponen un captcha o
    rediseñan el sitio, lo que falla es derivar el prefijo de rutas o parsear la tabla,
    y eso ya se detecta ahí. No se adivina "esto parece un captcha" sobre el cuerpo de
    la respuesta: un falso positivo detendría una consulta sana, y detenerse de más en
    esta herramienta significa un plazo que nadie revisó.

    No se reintenta, no se rota IP, no se evade. La respuesta correcta es detenerse y
    avisar: perder el acceso a la consulta mientras corren plazos en un litigio activo
    es peor que no obtener el dato.
    """


class Documento(BaseModel):
    """Un documento de la causa, con lo poco que se puede decir de él sin interpretarlo.

    El contenido viaja aparte, en `contenido`, y no se serializa: quien decide si el archivo
    entero cabe en la respuesta o si va como enlace es `server.py`, que es donde se conoce el
    presupuesto de la conversación.
    """

    competencia: str
    ruta: str = Field(description="Qué endpoint de la plataforma entregó el archivo.")
    tipo_mime: str = Field(description="El tipo declarado por la plataforma en la respuesta.")
    tamano_bytes: int
    paginas: int | None = Field(
        default=None, description="Cuántas páginas trae. NULO si el archivo no se pudo abrir."
    )
    paginas_con_texto: int | None = Field(
        default=None,
        description="De cuántas páginas se pudo extraer texto. Comparar con `paginas`: si es "
        "menor y mayor que cero, el documento es MIXTO, y las páginas que faltan son imágenes "
        "cuyo contenido no se puede citar. NULO si el archivo no se pudo abrir.",
    )
    capa_de_texto: bool | None = Field(
        default=None,
        description="Si de ALGUNA página se pudo extraer texto. FALSO significa que ninguna "
        "tiene, o sea es un escaneo: una imagen de un documento, sin texto detrás.\n\n"
        "Verdadero NO significa que todo el documento sea legible. Un expediente que mezcla "
        "resoluciones digitales con anexos escaneados es lo normal, y para eso está "
        "`paginas_con_texto`.\n\n"
        "NULO no es falso: significa que el archivo no se pudo abrir (viene cifrado, truncado "
        "o mal formado) y por lo tanto NO se sabe. Informarlo como escaneo sería afirmar algo "
        "que no se midió.",
    )
    problema_al_leer: str | None = Field(
        default=None,
        description="Por qué no se pudo abrir el archivo, cuando `capa_de_texto` es nulo. El "
        "documento se entrega igual: no poder describirlo no es no tenerlo.",
    )
    #: Los bytes tal cual llegaron. Se excluyen de la serialización porque este modelo se
    #: publica como metadato dentro de la respuesta, y un PDF en base64 ahí adentro es
    #: exactamente el gasto de contexto que `LIMITE_EMBEBIDO` existe para acotar.
    contenido: bytes = Field(default=b"", exclude=True, repr=False)


def _describir_pdf(contenido: bytes) -> tuple[int | None, int | None, str | None]:
    """Cuántas páginas trae y si hay texto que extraer. Nunca hace OCR.

    Detectar el escaneo es barato y transcribirlo es lo que no corresponde: una transcripción
    automática de una resolución se ve idéntica a la resolución y no lo es. Es peor que la
    lista vacía de la regla 4, porque la lista vacía se nota y un texto plausible con una
    palabra cambiada no.

    Corta en la primera página con texto: a un PDF con capa de texto le basta la primera, y a
    uno escaneado hay que recorrerlo entero para poder afirmar que no la tiene en ninguna.

    El `except` es ancho a propósito, y la razón es cuál es la respuesta segura. `pypdf`
    levanta media docena de excepciones distintas ante un archivo cifrado, truncado o mal
    formado, y acotar el catch dejaría escapar la que no se previó. Lo que importa es que
    ninguna termine en `False`: "no pude abrirlo" y "es un escaneo" son cosas distintas, y
    confundirlas hace que el servidor afirme sobre un documento algo que no midió.
    """
    try:
        lector = PdfReader(BytesIO(contenido))
        paginas = len(lector.pages)
        # Se cuentan las páginas CON texto en vez de cortar en la primera. Un expediente que
        # mezcla resoluciones digitales con anexos escaneados es lo normal, y cortar hacía que
        # una sola página con texto declarara todo el archivo digital: quien leyera eso daría
        # por transcribible un documento del que la mitad son imágenes.
        con_texto = sum(1 for pagina in lector.pages if pagina.extract_text().strip())
        return paginas, con_texto, None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


class Transporte:
    """Cadena HTTP compartida: ritmo, detención y bitácora.

    Los dos sistemas del Poder Judicial que este servidor consulta tienen sesiones muy
    distintas (la Oficina Judicial Virtual deriva un prefijo de rutas; el buscador de
    fallos usa un token CSRF de Laravel), pero le deben el mismo trato a la institución.
    Lo que se comparte es el trato, no la sesión.
    """

    def __init__(self, contacto: str, intervalo: float = INTERVALO_MINIMO) -> None:
        if intervalo < INTERVALO_MINIMO:
            raise ValueError(
                f"El intervalo mínimo entre consultas es {INTERVALO_MINIMO}s "
                "(cláusula CUARTA de las condiciones de uso). No se puede bajar."
            )
        self.intervalo = intervalo
        self._http = httpx.Client(
            headers={
                "User-Agent": f"mcp-pjud/{VERSION} (+contacto: {contacto})",
                "Accept-Language": "es-CL,es;q=0.9",
            },
            follow_redirects=True,
            timeout=ESPERA_MAXIMA,
        )
        self.bitacora: list[tuple[float, str, int]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self.cerrar()

    def cerrar(self) -> None:
        self._http.close()

    def _bloqueo_encubierto(self, r: httpx.Response) -> str | None:
        """Bloqueo que llega con HTTP 200 en el cuerpo. Cada sistema lo dice a su modo."""
        return None

    def _esperar(self) -> None:
        """Toma una ficha del balde, esperando si no hay.

        El balde se recarga a razón de una ficha por intervalo, y el reloj de recarga sólo
        corre entre peticiones: el tiempo que la plataforma tarda en responder no cuenta como
        espera. Así el régimen sostenido queda igual de conservador que el intervalo plano
        anterior, que medía desde el fin de una petición hasta el inicio de la siguiente.
        """
        global _FICHAS, _ULTIMA
        _FICHAS = min(RAFAGA_MAXIMA, _FICHAS + (time.monotonic() - _ULTIMA) / self.intervalo)
        if _FICHAS < 1.0:
            time.sleep((1.0 - _FICHAS) * self.intervalo)
            _FICHAS = 0.0
        else:
            _FICHAS -= 1.0

    def _req(self, metodo: str, url: str, **kw) -> httpx.Response:
        global _ULTIMA, _BLOQUEADO
        # El turno cubre la petición Y su clasificación, no sólo la espera. Dos llamadas
        # concurrentes leerían la misma marca y saldrían juntas; y si el turno se soltara
        # antes de clasificar, la segunda esperaría sus cinco segundos y consultaría igual
        # cuando la primera ya recibió el bloqueo. Eso es reintentar por el lado.
        with _TURNO:
            if _BLOQUEADO:
                raise PjudBloqueado(_BLOQUEADO)

            self._esperar()
            try:
                r = self._http.request(metodo, url, **kw)
            except httpx.HTTPError as e:
                # Una petición que no llegó a respuesta igual salió a la red, y la bitácora
                # existe para poder acreditar cuánto se consultó. Sin esto los timeouts no
                # quedaban registrados, o sea el registro subestimaba el tráfico generado
                # justo en las corridas donde la plataforma iba peor. Se anota con estado 0,
                # que ningún código HTTP usa.
                self.bitacora.append((time.time(), url, 0))
                if isinstance(e, _RECHAZO_DE_CONEXION):
                    _BLOQUEADO = (
                        f"La conexión con {url} se cortó: {type(e).__name__}. No se distingue "
                        "un corte de red local de un rechazo del cortafuegos, y un cortafuegos "
                        "que corta la conexión ya rechazó a esta IP. Detención total: no se "
                        "reintenta. Revisar la red y si el acceso quedó restringido, y "
                        "reiniciar el servidor sólo después de eso."
                    )
                    raise PjudBloqueado(_BLOQUEADO) from e
                raise
            finally:
                # El reloj de recarga arranca cuando la petición termina, no cuando empieza.
                # Un timeout que no lo moviera regalaría fichas por el tiempo que estuvo
                # colgado, justo cuando el portal está peor.
                _ULTIMA = time.monotonic()
            self.bitacora.append((time.time(), url, r.status_code))

            if r.status_code in (403, 429):
                _BLOQUEADO = (
                    f"El Poder Judicial respondió {r.status_code} a {url}. Detención total "
                    "del proceso, incluidas las consultas al otro sistema: los dos están "
                    "detrás del mismo cortafuegos. No se reintenta ni se evade. Revisar si "
                    "la IP quedó bloqueada, y reiniciar el servidor sólo después de eso."
                )
                raise PjudBloqueado(_BLOQUEADO)

            # El cortafuegos también rechaza con 200: un desafío de F5 BIG-IP APM, que es
            # JavaScript ofuscado en vez de la página. Tomarlo por bueno hace que el fallo
            # aparezca en la petición SIGUIENTE, un paso más allá de la causa real, que es el
            # diagnóstico equivocado que este proyecto ya pagó caro con los timeouts.
            #
            # Va acá y no en `_bloqueo_encubierto` porque es una propiedad del cortafuegos
            # compartido, no de ninguna de las dos aplicaciones. El corte del cuerpo es porque
            # esto corre en cada respuesta y las del detalle de causa son grandes; el desafío
            # trae la marca al principio.
            if _MARCA_APM in r.text[:4000]:
                _BLOQUEADO = (
                    f"El cortafuegos interpuso un desafío de F5 BIG-IP APM en {url} en vez de "
                    "la página, con HTTP 200. No es una caída de la plataforma. Resolverlo "
                    "exige ejecutar su JavaScript, o sea sortear un control "
                    "anti-automatización, y eso el proyecto no lo hace. Detención total."
                )
                raise PjudBloqueado(_BLOQUEADO)

            # Un bloqueo puede llegar como aviso dentro de una respuesta 200, no como un
            # código de error. Sin esto quedaría clasificado como "corrige los parámetros"
            # y el usuario reintentaría, que es justo lo que la detención total prohíbe.
            aviso = self._bloqueo_encubierto(r)
            if aviso:
                _BLOQUEADO = (
                    f"La plataforma interpuso una verificación en {url}: {aviso!r}. "
                    "Detención total: no se reintenta, no se evade. Esperar y revisar si el "
                    "acceso quedó restringido."
                )
                raise PjudBloqueado(_BLOQUEADO)

        r.raise_for_status()
        return r


class PjudClient(Transporte):
    """Consulta pública de causas de la Oficina Judicial Virtual."""

    def __init__(self, contacto: str, intervalo: float = INTERVALO_MINIMO) -> None:
        super().__init__(contacto, intervalo)
        self._adir: str | None = None
        self._token: str | None = None

    def __enter__(self) -> PjudClient:
        return self

    def _bloqueo_encubierto(self, r: httpx.Response) -> str | None:
        aviso = leer_aviso(r.text)
        return aviso if aviso and es_aviso_de_captcha(aviso) else None

    def _primera_pagina(
        self, ruta: str, data: dict[str, str], competencia: str
    ) -> list[CausaEncontrada]:
        """Una sola página, sin comprobar completitud.

        Para quien sólo necesita el primer resultado, como el flujo de actuaciones de
        receptor. Se separa del recorrido completo a propósito: acá una lista parcial es
        lo esperado, y confundir ese caso con una truncación silenciosa sería tan malo como
        no detectarla.
        """
        return parse_resultados(self._ajax(ruta, data), competencia)

    def _paginado(
        self, ruta: str, data: dict[str, str], paginas: int, competencia: str
    ) -> list[CausaEncontrada]:
        """Recorre las páginas de un listado hasta agotarlo o hasta el tope.

        La plataforma pagina con un identificador opaco, no con un número: el control de
        "siguiente" trae el token de la página que viene.

        Las tres comprobaciones de abajo existen porque la falla que importa acá no es
        romperse, es devolver menos de lo que hay sin decirlo.
        """
        if paginas < 1:
            # Con cero o menos, el bucle no corre y se devolvería una lista vacía
            # indistinguible de una búsqueda sin resultados. Un error de configuración no
            # debe disfrazarse de "no hay causas".
            raise ValueError(f"El tope de páginas debe ser 1 o más, se recibió {paginas}.")

        acumuladas: list[CausaEncontrada] = []
        vistos: set[str] = set()
        token: str | None = None
        total: int | None = None

        for numero in range(1, paginas + 1):
            html_ = self._ajax(ruta, data if token is None else {**data, "pagina": token})

            if es_sin_resultados(html_):
                # Esa respuesta viene sin navegación y sin total, así que hay que
                # reconocerla antes de exigir esos datos. Una búsqueda legítima sin
                # coincidencias no es un cambio de estructura.
                return acumuladas

            acumuladas.extend(parse_resultados(html_, competencia))

            if numero == 1:
                total = total_declarado(html_)
            if total is None:
                # Ambos listados que devuelve la plataforma traen este dato, así que su
                # ausencia es señal de que la estructura cambió. Antes se seguía sin
                # comprobar nada, o sea el guardia se apagaba solo.
                raise EstructuraInesperada(
                    "El listado no declara el total de registros. Sin ese dato no se "
                    "puede comprobar que el recorrido devolvió todo, y una lista "
                    "incompleta se leería como completa."
                )

            if len(acumuladas) > total:
                # Más de lo declarado sólo puede venir de páginas repetidas.
                raise EstructuraInesperada(
                    f"Se acumularon {len(acumuladas)} causas y la plataforma declara "
                    f"{total}. La paginación no está avanzando."
                )

            if len(acumuladas) == total:
                # El total declarado manda por sobre la navegación, y no es una optimización:
                # en suprema y en apelaciones el listado ofrece "siguiente" AUNQUE esté
                # completo. Medido sobre sus dos respuestas reales, de 1 de 1 y 3 de 3, las
                # dos con enlace. Seguirlo pide una página que no existe y termina en
                # `EstructuraInesperada` por acumular más de lo declarado o por no avanzar,
                # o sea una búsqueda completa fallando.
                #
                # Civil no lo hace, y por eso el hueco sobrevivió hasta que entraron esas dos
                # competencias.
                return acumuladas

            token = siguiente_pagina(html_)

            if token is None:
                if len(acumuladas) != total:
                    raise EstructuraInesperada(
                        f"La plataforma declaró {total} resultados y se recuperaron "
                        f"{len(acumuladas)}. El control de página siguiente desapareció "
                        "antes de tiempo: la respuesta puede venir truncada o su estructura "
                        "cambió. No se devuelve la lista parcial porque se leería como "
                        "completa."
                    )
                return acumuladas

            if token in vistos:
                # El mismo token dos veces significa que la página no avanza. Sin esto se
                # gastaban las diez páginas del tope acumulando duplicados, y el mensaje
                # final culpaba al usuario por hacer una búsqueda amplia.
                raise EstructuraInesperada(
                    f"La paginación devolvió el mismo identificador de página en la vuelta "
                    f"{numero}: no está avanzando."
                )
            vistos.add(token)

        raise ResultadosTruncados(
            f"La búsqueda tiene {total} resultados y se alcanzó el tope de {paginas} "
            f"páginas con {len(acumuladas)} recuperadas. Acota la búsqueda o sube el tope: "
            "un listado recortado en silencio se leería como si no hubiera más."
        )

    def _ajax(self, ruta: str, data: dict[str, str]) -> str:
        return self._req(
            "POST",
            f"{BASE}/{self._prefijo()}/{ruta}",
            data=data,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/consultaUnificada.php",
            },
        ).text

    def _combos(self, ruta: str, data: dict[str, str]) -> list[dict[str, str]]:
        """Lee uno de los combos que llenan los desplegables del formulario.

        Cuelgan de la RAÍZ del sitio y no del prefijo `ADIR_`, a diferencia de todo lo demás.
        Está medido: con el prefijo devuelven 404. Por eso no reusan `_ajax`.

        Devuelven JSON, así que se abre la sesión igual: sin ella no hay cookie y la respuesta
        no es la lista.
        """
        self._prefijo()
        r = self._req(
            "POST",
            f"{BASE}/{ruta}",
            data=data,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/consultaUnificada.php",
            },
        )
        cuerpo = r.json()
        if not isinstance(cuerpo, list):
            raise EstructuraInesperada(
                f"{ruta} devolvió {type(cuerpo).__name__} en vez de una lista. La estructura "
                "de la plataforma cambió."
            )
        return cuerpo

    def listar_cortes(self) -> list[Corte]:
        """Las Cortes de Apelaciones con el código que las búsquedas exigen.

        Sin esto el parámetro `corte` había que sabérselo de memoria: no aparecía en ninguna
        respuesta ni en la documentación, así que quien no lo supiera no podía buscar en
        apelaciones.
        """
        filas = self._combos("combosJSON/leeCorte.php", {"tipoBusqueda": "1"})
        cortes = [
            Corte(codigo=int(f["COD_CORTE"]), nombre=" ".join(f["GLS_CORTE"].split()))
            for f in filas
            if f.get("COD_CORTE")
        ]
        if not cortes:
            # Una lista vacía se leería como "no hay cortes", y siempre las hay. Es la regla 4.
            raise EstructuraInesperada(
                "El listado de cortes vino vacío. Siempre hay cortes, así que la respuesta "
                "viene truncada o la estructura cambió."
            )
        return cortes

    def listar_tribunales(self, competencia: str, corte: int) -> list[Tribunal]:
        """Los tribunales de una corte, con el código que las búsquedas exigen.

        Es el muro de entrada del proyecto: para buscar en primera instancia hay que pasar
        `tribunal=162`, y ese número no aparecía en ninguna parte.
        """
        nombre = competencia.lower()
        if nombre not in CON_TRIBUNAL:
            # Medido el 20 de agosto de 2026 sobre la corte 46, con las seis: suprema devuelve
            # `null` porque ES la corte y no tiene tribunales debajo, y apelaciones devuelve
            # 118 juzgados de PRIMERA instancia, que no son con qué se busca ahí. Las dos se
            # acotan por corte o por nada, así que pedir sus tribunales es una pregunta sin
            # sentido, y devolver esa lista invitaría a usarla como si fuera `tribunal`.
            raise EstructuraInesperada(
                f"{competencia!r} no se acota por tribunal, así que no tiene un listado que "
                f"sirva para buscar. Se acotan por tribunal: {', '.join(sorted(CON_TRIBUNAL))}."
            )
        spec = COMPETENCIAS[nombre]
        filas = self._combos(
            "combosJSON/leeTrib.php",
            {"codCompetencia": str(spec.codigo), "codCorte": str(corte), "tipoBusqueda": "1"},
        )
        tribunales = [
            Tribunal(codigo=int(f["COD_TRIBUNAL"]), nombre=" ".join(f["GLS_TRIBUNAL"].split()))
            for f in filas
            if f.get("COD_TRIBUNAL")
        ]
        if not tribunales:
            # Toda corte tiene tribunales debajo. Devolver la lista vacía se leería como que
            # esa corte no tiene ninguno, y quien la reciba concluiría que el tribunal que
            # busca no existe. Es la regla 4.
            raise EstructuraInesperada(
                f"El listado de tribunales de {competencia} en la corte {corte} vino vacío. "
                "Toda corte tiene tribunales, así que la respuesta viene truncada o cambió el "
                "nombre de los campos."
            )
        return tribunales

    def audios(self, referencia: str) -> list[AudioAudiencia]:
        """Qué audios de audiencia tiene la causa, y con qué enlace se bajan.

        NO trae los archivos. Devuelve el listado y el enlace de cada uno, para que quien los
        necesite los abra: son las voces de las partes, los testigos y el tribunal, y una
        transcripción automática no reemplaza oírlos.

        La referencia la entrega `detalle_causa` en `audio_referencia`. Cuesta UNA petición.

        La ruta cuelga de la RAÍZ del sitio y no del prefijo `ADIR_`, a diferencia de todos los
        demás modales. Está medido lo que pasa al construirla por analogía con ellos: la
        plataforma responde 200, con el modal correcto y su encabezado, y la tabla VACÍA. O sea
        con la forma exacta de "esta causa no tiene audios".
        """
        if not referencia:
            raise ValueError(
                "Falta la referencia del listado de audios. La entrega el detalle de la causa "
                "en `audio_referencia`, y cuando viene nula esa causa no ofrece grabación o su "
                "competencia no está medida."
            )
        self._prefijo()
        return parse_audios(
            self._req(
                "POST",
                f"{BASE}/{AUDIO_RUTA}",
                data={AUDIO_CAMPO: referencia},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE}/consultaUnificada.php",
                },
            ).text
        )

    def georreferencia(self, referencia: str, competencia: str = "civil") -> Georreferencia:
        """Dónde y cuándo el ministro de fe registró que practicó una diligencia.

        La referencia la entrega cada actuación en `georreferencia_referencia`. Cuesta UNA
        petición por actuación, con su intervalo, así que se pide de a una y nunca de barrido:
        para las seis georreferenciadas de una causa de dos cuadernos serían seis peticiones
        más sobre las seis que ya costó leerla.

        Tener referencia no garantiza que haya georreferencia: está medido que una de seis
        abre un panel que responde que no existe ninguna. Eso vuelve con `existe=False` y no
        como error, porque un error se leería como que no se pudo consultar.
        """
        nombre = competencia.lower()
        ruta = GEORREFERENCIA.get(nombre)
        if ruta is None:
            # Las dos razones para no ofrecerla se rechazan igual, pero no significan lo
            # mismo y no se pueden decir con la misma frase. En `suprema` está medido que su
            # Historia no trae la columna; en `penal` no está medida la Historia, así que
            # decir "no la publica" sería publicar un negativo que nadie verificó.
            medida = COMPETENCIAS.get(nombre) is not None and COMPETENCIAS[nombre].historia
            motivo = (
                f"{competencia!r} no publica la columna de georreferencia en su tabla de "
                "Historia, así que no hay referencia que pedir."
                if medida
                else f"La tabla de Historia de {competencia!r} no está medida, así que no se "
                "sabe si publica la columna de georreferencia ni de dónde saldría la "
                "referencia. Se rechaza por no verificada, NO porque esté comprobado que no "
                "la tenga."
            )
            raise ValueError(f"{motivo} Verificadas: {', '.join(sorted(GEORREFERENCIA))}.")
        if not referencia:
            raise ValueError(
                "Falta la referencia de la georreferencia. La entrega cada actuación en "
                "`georreferencia_referencia`, y cuando viene nula esa actuación no la ofrece."
            )
        return parse_georreferencia(
            self._req(
                "POST",
                f"{BASE}/{self._prefijo()}/{ruta}",
                data={"valGeoRef": referencia},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE}/consultaUnificada.php",
                },
            ).text
        )

    def anexos(self, ruta: str, referencia: str, competencia: str = "civil") -> list[Anexo]:
        """Los documentos que acompañan a un escrito, en el segundo canal del folio.

        La ruta y la referencia las entrega cada actuación en `anexo_ruta` y
        `anexo_referencia`, y hacen falta las dos: la competencia no alcanza para saber a qué
        panel se pide, porque civil tiene dos y con parámetros distintos.

        Cuesta UNA petición por folio, con su intervalo, así que se pide del folio concreto
        que importa y nunca de barrido.

        Cinco paneles medidos de los dieciocho que el sitio nombra. Los demás se rechazan por
        no verificados, no porque esté comprobado que no funcionen: armarlos por analogía
        devuelve una página que no es la que se pidió, y eso no se distingue de una causa sin
        anexos.
        """
        nombre = competencia.lower()
        rutas = ANEXOS.get(nombre)
        if rutas is None:
            raise ValueError(
                f"No hay ningún panel de anexos medido en {competencia!r}. Medidos: "
                f"{', '.join(sorted(ANEXOS))}. Se rechaza por no verificado, NO porque esté "
                "comprobado que esa competencia no los tenga."
            )
        campo = rutas.get(ruta)
        if campo is None:
            raise ValueError(
                f"La ruta {ruta!r} no es uno de los paneles de anexo medidos de "
                f"{competencia!r}: {', '.join(sorted(rutas))}. Si viene de una actuación, usar "
                "su `anexo_ruta` tal cual. Cuando esa viene en nulo, el folio abre un panel "
                "que no está medido y sus anexos todavía no se pueden pedir."
            )
        if not referencia:
            raise ValueError(
                "Falta la referencia del anexo. La entrega cada actuación en "
                "`anexo_referencia`, y cuando viene nula ese folio no ofrece anexos o su "
                "panel no está medido."
            )
        return parse_anexos(
            self._req(
                "POST",
                f"{BASE}/{self._prefijo()}/{nombre}/modal/{ruta}",
                data={campo: referencia},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE}/consultaUnificada.php",
                },
            ).text,
            ruta,
        )

    # -- sesión -----------------------------------------------------------------

    def _prefijo(self) -> str:
        if self._adir is None:
            self.abrir_sesion()
        if self._adir is None:
            # No es un assert a propósito: bajo `python -O` los assert desaparecen, y este
            # guardia protege justo el caso en que se consultarían rutas sin prefijo, que
            # devuelven vacío en vez de fallar.
            raise PjudBloqueado(
                "No se pudo derivar el prefijo de rutas tras abrir sesión. Detención: "
                "consultar sin prefijo devuelve respuestas vacías indistinguibles de "
                "'no hay causas'."
            )
        return self._adir

    def abrir_sesion(self) -> None:
        """Abre sesión pública y deriva las constantes versionadas del servidor.

        El prefijo de rutas y el token de los modales están interpolados en el HTML y
        cambian entre despliegues y entre sesiones. Hardcodearlos rompería las veinte
        rutas a la vez sin previo aviso, así que se leen en caliente.
        """
        self._req("GET", ENTRADA, headers={"Referer": PORTADA})
        pagina = self._req(
            "GET", f"{BASE}/consultaUnificada.php", headers={"Referer": f"{BASE}/indexN.php"}
        ).text

        adir = re.search(r"ADIR_\d+", pagina)
        token = re.search(r"token\s*:\s*'([0-9a-f]{32})'", pagina)
        if not adir or not token:
            raise PjudBloqueado(
                "No se pudo derivar el prefijo de rutas o el token desde "
                "consultaUnificada.php. La estructura del sitio cambió; el cliente se "
                "detiene en vez de consultar rutas que ya no existen."
            )
        self._adir, self._token = adir.group(0), token.group(1)

    # -- consultas --------------------------------------------------------------

    def _modulo(self, competencia: str) -> str:
        nombre = competencia.lower()
        if nombre not in COMPETENCIAS:
            raise ValueError(
                f"Competencia {competencia!r} no existe en la plataforma. Son: "
                f"{', '.join(sorted(COMPETENCIAS))}."
            )
        if nombre not in MODULOS:
            raise ValueError(
                f"Competencia {competencia!r} no verificada contra el sistema real. "
                f"Verificadas: {', '.join(sorted(MODULOS))}. Se rechaza en vez de adivinar "
                "sus parámetros, porque una consulta mal armada devuelve vacío y eso se lee "
                "como que la causa no existe."
            )
        return nombre

    def _acotacion(self, modulo: str, tribunal: int | None, corte: int | None) -> None:
        """Verifica que la búsqueda venga acotada como la plataforma lo exige.

        Comparte las tres búsquedas que lo exigen (nombre, RUT de persona jurídica y fecha),
        porque el requisito es de la competencia y no de la búsqueda: se midió el mismo aviso,
        "Por favor seleccione una Corte para la búsqueda", en las tres de apelaciones.

        `buscar_por_rit` NO llama acá, y es a propósito, no un olvido: la búsqueda por rol es
        la única que la plataforma acepta sin acotar en ninguna competencia. Medido con
        `conCorte=0`, suprema devolvió su causa y apelaciones devolvió 31. Agregar la llamada
        "por consistencia" rompería las dos: pasarían a exigir un dato que ahí no hace falta,
        y el rechazo saldría de este cliente sin que la plataforma se entere.
        """
        exige = COMPETENCIAS[modulo].acota_por
        if exige == "tribunal" and tribunal is None:
            raise ValueError(
                f"En {modulo} esta búsqueda exige tribunal. Es una limitación de la "
                "plataforma, no de este cliente: no permite buscar en todos los tribunales "
                "a la vez."
            )
        if exige == "corte" and corte is None:
            raise ValueError(
                f"En {modulo} esta búsqueda exige corte. La plataforma responde 'Por favor "
                "seleccione una Corte para la búsqueda' y no entrega resultados."
            )

    def buscar_por_rit(
        self,
        tipo: str,
        rol: int,
        anio: int,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
        paginas: int | None = PAGINAS_MAXIMAS,
    ) -> list[CausaEncontrada]:
        """Busca causas por rol. `tipo` es la letra del rol: C, V, E, A, F o I en civil.

        `corte` va sin valor por defecto a propósito: dejarla fijada produce falsos
        negativos, porque omite causas radicadas en otras jurisdicciones.
        """
        modulo = self._modulo(competencia)
        # Medido contra el sistema real: rol y año son los únicos obligatorios. El tipo,
        # la corte y el tribunal son opcionales, y omitir el tribunal AMPLÍA los
        # resultados: la misma consulta devolvió dos causas sin él y una con él.
        if not rol or not anio:
            raise ValueError("La búsqueda por rol exige número de rol y año.")
        ruta = f"{modulo}/consultaRit{modulo.capitalize()}.php"
        campos = {
            "conTipoCausa": tipo.upper(),
            "conRolCausa": str(rol),
            "conEraCausa": str(anio),
            "conCompetencia": str(COMPETENCIAS[competencia.lower()].codigo),
            "conCorte": str(corte or 0),
            "conTribunal": str(tribunal or 0),
            "conCaratulado": "",
            # El radio RIT/RUC del formulario, y el campo que faltaba para que suprema y
            # apelaciones respondieran. Su PHP se ramifica en él para saber por cuál de los dos
            # se está buscando, y sin el campo revienta: HTTP 200 con el cuerpo VACÍO, sin
            # aviso. Civil, laboral, cobranza y penal lo toleraban ausente, así que el hueco
            # quedó tapado hasta que se agregaron las dos competencias que no lo toleran.
            #
            # El 1 es "por RIT". El otro valor de este formulario es 2, "por RUC", que no se
            # usa acá. Ojo con `buscar_por_nombre`: manda un `radio-group` con "N", que es OTRO
            # formulario y otro dominio de valores, no una inconsistencia.
            "radio-group": "1",
            # Lo que esta competencia exige de más. Sale de la tabla y no de una rama acá:
            # tres de las seis lo necesitan y las tres estuvieron rotas por no tenerlo.
            **COMPETENCIAS[modulo].campos_rit,
        }
        if paginas is None:
            return self._primera_pagina(ruta, campos, competencia)
        return self._paginado(ruta, campos, paginas, competencia)

    # -- búsquedas ---------------------------------------------------------------
    #
    # Las reglas de obligatoriedad de abajo se mapearon contra el sistema real, probando
    # cada combinación de campos. La plataforma no responde con un código de error cuando
    # faltan campos: devuelve HTTP 200 con un aviso dentro de un <script>. Validar acá
    # evita gastar una petición y evita que ese aviso llegue disfrazado de resultado.

    def buscar_por_nombre(
        self,
        nombre: str = "",
        apellido_paterno: str = "",
        apellido_materno: str = "",
        anio: int | None = None,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
        paginas: int = PAGINAS_MAXIMAS,
    ) -> list[CausaEncontrada]:
        """Busca causas por nombre de litigante.

        La plataforma exige al menos dos de los tres campos de nombre. El año NO cuenta
        para ese mínimo: se comprobó que "apellido paterno + año" es rechazado mientras
        que "paterno + materno" es aceptado.

        Además hay que acotar la búsqueda, y con qué depende de la competencia: tribunal en
        las cuatro de primera instancia, corte en apelaciones, nada en suprema. Lo resuelve
        `_acotacion` con la tabla de `parser.COMPETENCIAS`.
        """
        modulo = self._modulo(competencia)
        if sum(1 for x in (nombre, apellido_paterno, apellido_materno) if x.strip()) < 2:
            raise ValueError(
                "La búsqueda por nombre exige al menos dos de estos tres campos: nombre, "
                "apellido paterno, apellido materno. El año no cuenta para ese mínimo."
            )
        self._acotacion(modulo, tribunal, corte)
        return self._paginado(
            f"{modulo}/consultaNombre{modulo.capitalize()}.php",
            {
                "radio-group": "N",
                "nomNombre": nombre,
                "nomApePaterno": apellido_paterno,
                "nomApeMaterno": apellido_materno,
                "nomEra": str(anio) if anio else "",
                "nomNombreJur": "",
                "nomEraJur": "",
                "nomCompetencia": str(COMPETENCIAS[competencia.lower()].codigo),
                "nomTribunal": str(tribunal),
                "corteNom": str(corte or 0),
            },
            paginas,
            competencia,
        )

    def buscar_por_rut_juridica(
        self,
        rut: int,
        digito_verificador: str,
        anio: int | None = None,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
        paginas: int = PAGINAS_MAXIMAS,
    ) -> list[CausaEncontrada]:
        """Busca causas de una persona jurídica por su RUT.

        Es la única vía para personas jurídicas, que no tienen Clave Única y por lo tanto
        no aparecen en "Mis Causas".
        """
        modulo = self._modulo(competencia)
        if not str(digito_verificador).strip():
            raise ValueError("Falta el dígito verificador del RUT.")
        self._acotacion(modulo, tribunal, corte)
        return self._paginado(
            f"{modulo}/consultaJuridica{modulo.capitalize()}.php",
            {
                "rutJur": str(rut),
                "dvJur": str(digito_verificador).upper(),
                "eraJur": str(anio) if anio else "",
                "jurCompetencia": str(COMPETENCIAS[competencia.lower()].codigo),
                "jurTribunal": str(tribunal),
                "corteJur": str(corte or 0),
            },
            paginas,
            competencia,
        )

    def buscar_por_fecha(
        self,
        desde: str,
        hasta: str,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
        paginas: int = PAGINAS_MAXIMAS,
    ) -> list[CausaEncontrada]:
        """Busca causas ingresadas en un rango de fechas, en formato DD/MM/AAAA.

        Un solo día en un solo tribunal puede devolver decenas de causas, así que conviene
        acotar el rango.
        """
        modulo = self._modulo(competencia)
        if not desde.strip() or not hasta.strip():
            raise ValueError("La búsqueda por fecha exige fecha inicial y fecha final.")
        self._acotacion(modulo, tribunal, corte)
        return self._paginado(
            f"{modulo}/consultaFecha{modulo.capitalize()}.php",
            {
                "fecDesde": desde,
                "fecHasta": hasta,
                "fecCompetencia": str(COMPETENCIAS[competencia.lower()].codigo),
                "fecTribunal": str(tribunal),
                "corteFec": str(corte or 0),
            },
            paginas,
            competencia,
        )

    def detalle(self, referencia: str, competencia: str = "civil") -> str:
        """Devuelve el HTML del detalle de una causa a partir de su referencia opaca."""
        modulo = self._modulo(competencia)
        self._prefijo()
        return self._ajax(
            f"{modulo}/modal/causa{modulo.capitalize()}.php",
            {"dtaCausa": referencia, "token": self._token or ""},
        )

    def documento(self, ruta: str, referencia: str, competencia: str = "civil") -> Documento:
        """Pide UN documento de la causa y lo devuelve tal cual llegó.

        Las dos primeras las entrega cada actuación en `documento_ruta` y
        `documento_referencia`, y hacen falta las dos: la ruta dice a qué endpoint se pide y
        con qué parámetro, y la referencia dice cuál documento.

        No hace falta el rol. El endpoint no direcciona por causa: la referencia ya identifica
        el documento, y la competencia sólo elige bajo qué módulo del sitio cuelga la ruta.
        Buscar la causa antes serían dos peticiones más contra la plataforma que no verifican
        nada, porque la referencia se emite al dibujar la página y no es la identidad estable
        del documento: la misma pieza llega con una distinta en cada cuaderno.

        Lo que sí hay que tener presente, y está medido: la referencia es un token firmado y
        NO un identificador de sesión. Sirve desde una sesión distinta de la que la emitió,
        así que el flujo normal, leer el detalle con una herramienta y pedir el documento con
        otra, funciona. Cuánto dura el token no se midió.

        Una referencia que la plataforma ya no acepte no devuelve "no existe": devuelve una
        página de error con HTTP 200, y por eso este método verifica que lo que llegó SEA un
        PDF antes de entregarlo.
        """
        modulo = self._modulo(competencia)
        rutas = DOCUMENTOS.get(modulo)
        if not rutas:
            raise ValueError(
                f"En {competencia!r} no está medida ninguna ruta de documentos: su detalle no "
                "emite formularios de descarga en la respuesta que este proyecto guardó. Se "
                "rechaza antes de consultar en vez de armar una ruta por analogía con otra "
                "competencia, que devolvería una página de error indistinguible de un archivo."
            )
        parametro = rutas.get(ruta)
        if parametro is None:
            raise ValueError(
                f"La ruta {ruta!r} no es una de las que el detalle de {competencia!r} emite: "
                f"{', '.join(sorted(rutas))}. Se rechaza en vez de pedirla igual, porque con "
                "una ruta libre esta herramienta deja de entregar documentos de una causa y "
                "pasa a ser un proxy contra cualquier página del sitio.\n\n"
                "Si viene de una actuación, usar su `documento_ruta` tal cual. Cuando esa "
                "viene en nulo, la fila abre el documento con un modal de JavaScript y a qué "
                "endpoint llama no está medido: ahí el documento todavía no se puede pedir."
            )
        if not referencia:
            raise ValueError(
                "Falta `documento_referencia`. Sin ella la plataforma no sabe qué documento "
                "se pide, y la respuesta a una consulta sin referencia no es el archivo."
            )

        r = self._req(
            "GET",
            f"{BASE}/{self._prefijo()}/{modulo}/documentos/{ruta}",
            params={parametro: referencia},
            headers={"Referer": f"{BASE}/consultaUnificada.php"},
        )
        contenido = r.content
        if not contenido.startswith(_MAGIA_PDF):
            # El aviso, cuando la respuesta es uno, es lo único que distingue "la referencia
            # caducó" de "la plataforma cambió". Sin él queda un error que no dice qué hacer.
            aviso = leer_aviso(r.text[:8000])
            declarado = r.headers.get("content-type") or "tipo no declarado"
            raise EstructuraInesperada(
                f"La ruta {ruta!r} no devolvió un PDF sino {len(contenido)} bytes de "
                f"{declarado!r}"
                + (f", con el aviso {aviso!r}. " if aviso else ". ")
                + "Los seis endpoints de documentos entregan PDF, así que esto no es el "
                "archivo. Lo más probable es que `documento_referencia` haya caducado: se "
                "emite al dibujar el detalle, así que conviene pedir el documento cerca de "
                "volver a pedir el detalle de la causa y usar la referencia nueva.\n\n"
                "No se entrega igual. Un archivo que en realidad es una página de error se "
                "ve como un documento y no lo es, y quien lo reciba no tiene cómo notarlo."
            )

        paginas, con_texto, problema = _describir_pdf(contenido)
        return Documento(
            competencia=modulo,
            ruta=ruta,
            tipo_mime=(r.headers.get("content-type") or "application/pdf").split(";")[0].strip(),
            tamano_bytes=len(contenido),
            paginas=paginas,
            paginas_con_texto=con_texto,
            capa_de_texto=None if con_texto is None else con_texto > 0,
            problema_al_leer=problema,
            contenido=contenido,
        )

    def actuaciones_receptor(
        self,
        tipo: str,
        rol: int,
        anio: int,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
    ) -> list[Actuacion]:
        """Actuaciones del ministro de fe, encadenando búsqueda y detalle.

        La Oficina Judicial Virtual no direcciona el detalle por rol, así que hay que
        buscar primero para obtener la referencia opaca de la causa.
        """
        # Antes de gastar una sola petición. `MODULOS` dice que la BÚSQUEDA está verificada,
        # que no es lo mismo que poder leer la historia: sin esto, pedir actuaciones de una
        # competencia buscable pero sin panel mapeado gastaba dos peticiones y diez segundos
        # contra la plataforma para terminar culpándola de un cambio que nunca hubo.
        spec = COMPETENCIAS[self._modulo(competencia)]
        if not spec.receptor:
            raise ValueError(
                f"La competencia {competencia!r} no expone actuaciones de ministro de fe: en "
                "todo el sitio sólo existen `receptorCivil` y `receptorCobranza`. La pregunta "
                "no tiene respuesta ahí, y devolver una lista vacía se leería como que no "
                "hubo actuaciones."
            )
        if spec.historia is None:
            raise ValueError(
                f"No está verificado cómo se lee la historia de {competencia!r}. Se rechaza "
                "antes de consultar en vez de leerla con el mapa de otra competencia, que "
                "devolvería filas mal alineadas o una lista vacía."
            )
        if not spec.receptor_en_historia:
            raise ValueError(
                f"En {competencia!r} las diligencias del ministro de fe viven en un panel "
                "propio (`diligenciaCob`) con otra estructura, que este proyecto todavía no "
                "lee.\n\n"
                "Su tabla de Historia SÍ nombra algunas: medido sobre una respuesta real, tres "
                "filas dicen 'Actuacion - Receptor', sin tilde y con guion, y ninguna trae "
                "fecha de diligencia.\n\n"
                "Si esas tres son todas las diligencias o sólo una parte NO está medido: haría "
                "falta compararlas contra `diligenciaCob`, que este proyecto todavía no lee. "
                "Entregarlas sería informar una lista de completitud desconocida como si fuera "
                "el total, y sin el dato que se busca.\n\n"
                "Se rechaza por eso, y no por falta de filas."
            )
        return self._recorrer_cuadernos(
            tipo, rol, anio, competencia, tribunal, corte, actuaciones_receptor
        )

    @staticmethod
    def _causa_pedida(causas: list[CausaEncontrada], tipo: str, rol: int, anio: int):
        """Elige de la lista la causa que se pidió, o se detiene.

        Tomar la primera parecía inofensivo mientras el número de rol identificara una causa.
        En Cortes de Apelaciones NO la identifica: el mismo número y año existen en varios
        libros a la vez, y una respuesta real trae `Exhorto-1504-2019`, `Civil-1504-2019` y
        `Protección-1504-2019`, cada una con su propia referencia y su propia historia.

        Devolver la primera entrega las actuaciones de OTRA causa como si fueran las pedidas.
        Es peor que el falso negativo que este proyecto existe para evitar: una lista vacía se
        nota, y una historia ajena viene con folios, fechas y trámites que se ven perfectamente
        bien. Alguien computaría un plazo contra una causa que no es la suya.

        Por eso, ante ambigüedad, se levanta y se dicen los roles encontrados en vez de elegir.
        """
        # Se compara SIEMPRE, incluso con un solo resultado. El atajo de devolver la única
        # coincidencia dejaba en pie exactamente el riesgo que este método existe para cerrar:
        # `buscar_por_rit` no filtra apelaciones por `tipo`, así que pedir `Protección-123-2026`
        # y recibir sólo `Civil-123-2026` abría la equivocada sin comparar nada.
        esperado = f"{tipo}-{rol}-{anio}".lstrip("-").lower()
        exactas = [c for c in causas if (c.rol or "").strip().lower() == esperado]
        if len(exactas) == 1:
            return exactas[0]

        encontrados = ", ".join(sorted((c.rol or "?") for c in causas))
        # Ojo al mapear penal: su búsqueda toma el tipo como CÓDIGO numérico (`1` es Ordinaria)
        # y el listado publica el nombre del libro, así que `esperado` no va a calzar nunca.
        # Hoy no llega acá porque penal no tiene historia mapeada ni receptor.
        raise ValueError(
            f"La búsqueda devolvió {len(causas)} causas y ninguna corresponde sin ambigüedad a "
            f"{esperado!r}: {encontrados}. En Cortes de Apelaciones el número de rol se repite "
            "entre libros, así que hay que indicar el libro en `tipo` (por ejemplo "
            "'Protección'). No se elige una: entregar la historia de otra causa se vería "
            "perfectamente bien y llevaría a computar un plazo ajeno."
        )

    def detalle_causa(
        self,
        tipo: str,
        rol: int,
        anio: int,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
    ) -> DetalleCausa:
        """Todo lo que la respuesta del detalle publica, con UNA sola cadena de peticiones.

        Las lecturas separadas pedían la misma respuesta HTML una vez cada una. Preguntar las
        cuatro cosas de una causa con dos cuadernos costaba dieciséis peticiones contra la
        plataforma para leer cuatro paneles que ya venían juntos en la primera. La hoja de ruta
        lo decía desde el principio: "ya vienen en la respuesta del detalle que el cliente
        pide", y la implementación había derivado de su propio plan.

        Un panel que la competencia no publica viaja en nulo y no en lista vacía: "acá no se
        informa" y "no ocurrió" son cosas distintas. Y `piezas_exhorto` agrega una tercera, que
        no depende de la competencia sino de la causa, así que la nombra `causa_es_exhorto`.
        """
        spec = COMPETENCIAS[self._modulo(competencia)]
        paneles = (
            spec.historia,
            spec.litigantes,
            spec.notificaciones,
            spec.liquidaciones,
            spec.materias,
        )
        if not any(paneles):
            raise ValueError(
                f"No está verificado cómo leer ningún panel del detalle de {competencia!r}. Se "
                "rechaza antes de consultar en vez de gastar dos peticiones para devolver todo "
                "en nulo, que además se leería como que la causa no tiene nada."
            )

        causas = self.buscar_por_rit(tipo, rol, anio, competencia, tribunal, corte, paginas=None)
        if not causas:
            return DetalleCausa(causa_encontrada=False)

        primera = self.detalle(self._causa_pedida(causas, tipo, rol, anio).referencia, competencia)
        cuadernos = parse_cuadernos(primera)

        # El detalle despliega un cuaderno a la vez, y el de apremio esconde el requerimiento
        # de pago y el embargo. Se recorren todos, igual que las lecturas separadas.
        paginas = [(primera, cuadernos[0].nombre if cuadernos else "")]
        if len(cuadernos) > 1:
            paginas = [
                (self.detalle(cuaderno.referencia, competencia), cuaderno.nombre)
                for cuaderno in cuadernos
            ]

        historia: list[Actuacion] | None = [] if spec.historia else None
        if historia is not None:
            for pagina, nombre in paginas:
                historia.extend(parse_historia(pagina, nombre, competencia))

        # Los demás paneles no llevan el cuaderno de ESTA causa en la fila, así que si el
        # sitio los repite en cada uno llegarían duplicados. Se deduplica por el contenido, que
        # es correcto tanto si el panel es global como si fuera por cuaderno: en el segundo
        # caso las filas difieren y se conservan todas.
        #
        # Las piezas del exhorto son la excepción aparente: traen una columna `Cuaderno`, pero
        # es el de la causa de ORIGEN, no el que se está recorriendo acá.
        #
        # Y las referencias quedan fuera de la comparación, que eso está medido: el MISMO
        # exhorto de C-1156-2026 trae una referencia distinta en el cuaderno principal y en el
        # de apremio. Son tokens de render, no identidades, así que incluirlas hacía que una
        # causa que despachó UN exhorto informara dos.
        def _juntar(leer, declarado):
            if declarado is None:
                return None
            vistos: dict[str, object] = {}
            for pagina, _ in paginas:
                filas = leer(pagina, competencia)
                # Sólo `parse_piezas_exhorto` devuelve nulo, y significa que la causa no es un
                # exhorto. Propagarlo es lo correcto: una lista vacía acá diría "es un exhorto
                # y el tribunal de origen no le mandó ninguna pieza".
                if filas is None:
                    return None
                for fila in filas:
                    vistos.setdefault(fila.model_dump_json(exclude=_VOLATILES), fila)
            return list(vistos.values())

        return DetalleCausa(
            historia=historia,
            # De la cabecera del PRIMER cuaderno: el enlace vive ahí, que es la misma en todos,
            # y no en la tabla que se recorre.
            audio_referencia=audio_de_la_causa(primera),
            litigantes=_juntar(parse_litigantes, spec.litigantes),
            notificaciones=_juntar(parse_notificaciones, spec.notificaciones),
            liquidaciones=_juntar(parse_liquidaciones, spec.liquidaciones),
            materias=_juntar(parse_materias, spec.materias),
            exhortos=_juntar(parse_exhortos, spec.exhortos),
            # De la cabecera y no de que el panel de piezas haya llegado: es lo único que
            # distingue "esta competencia no publica el panel" de "esta causa no es un
            # exhorto", y sin esa distinción `piezas_exhorto` en nulo diría las dos cosas.
            causa_es_exhorto=(
                causa_es_exhorto(primera, competencia) if spec.piezas_exhorto else None
            ),
            # No es una lista, así que no pasa por `_juntar`: no hay filas que deduplicar. Se
            # lee del PRIMER cuaderno por lo mismo que `causa_es_exhorto`, que la causa de la
            # que subió el recurso es de la causa entera y no de uno de sus cuadernos.
            causa_de_origen=parse_causa_de_origen(primera, competencia),
            piezas_exhorto=_juntar(parse_piezas_exhorto, spec.piezas_exhorto),
        )

    def _recorrer_cuadernos(
        self,
        tipo: str,
        rol: int,
        anio: int,
        competencia: str,
        tribunal: int | None,
        corte: int | None,
        leer: Callable[[str, str, str], list[_Fila]],
    ) -> list[_Fila]:
        """Busca la causa, abre su detalle y recorre TODOS sus cuadernos.

        Lo comparten `actuaciones_receptor` y `historia_causa`, que sólo difieren en qué filas
        se quedan: duplicar el recorrido para cambiar el filtro es la forma más segura de que
        uno de los dos se olvide de los cuadernos.
        """
        # `paginas=None` a propósito: de todo el listado sólo se usa la primera causa, así que
        # recorrer hasta el tope gastaría hasta nueve peticiones y cuarenta y cinco segundos
        # contra la plataforma para descartarlas. El ritmo de consulta no es un parámetro de
        # rendimiento acá.
        causas = self.buscar_por_rit(tipo, rol, anio, competencia, tribunal, corte, paginas=None)
        if not causas:
            return []

        html_ = self.detalle(self._causa_pedida(causas, tipo, rol, anio).referencia, competencia)
        cuadernos = parse_cuadernos(html_)

        # El detalle despliega la Historia de un solo cuaderno. Una causa con cuaderno
        # de apremio esconde ahí actuaciones que no están en el principal, así que se
        # recorren todos: devolver sólo el que vino por defecto daría una respuesta
        # aparentemente completa a la que le faltan justo las diligencias del apremio.
        if len(cuadernos) <= 1:
            nombre = cuadernos[0].nombre if cuadernos else ""
            return leer(html_, nombre, competencia)

        actuaciones = []
        for cuaderno in cuadernos:
            pagina = self.detalle(cuaderno.referencia, competencia)
            actuaciones.extend(leer(pagina, cuaderno.nombre, competencia))
        return actuaciones
