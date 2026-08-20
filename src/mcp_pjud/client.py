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
from typing import TypeVar

import httpx

from .parser import (
    COMPETENCIAS,
    Actuacion,
    CausaEncontrada,
    DetalleCausa,
    EstructuraInesperada,
    Liquidacion,
    Notificacion,
    actuaciones_receptor,
    es_aviso_de_captcha,
    es_sin_resultados,
    leer_aviso,
    parse_cuadernos,
    parse_historia,
    parse_liquidaciones,
    parse_litigantes,
    parse_materias,
    parse_notificaciones,
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

BASE = "https://oficinajudicialvirtual.pjud.cl"
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


#: Cuántas páginas de resultados se recorren como máximo. La plataforma devuelve 100 por
#: página, así que el valor por defecto cubre mil causas: más que cualquier consulta
#: razonable, y bajo el intervalo de 5 segundos son unos 50 segundos.
#:
#: Existe para que una búsqueda demasiado amplia no se convierta en un barrido. Al
#: alcanzarlo se levanta `ResultadosTruncados` en vez de devolver una lista recortada en
#: silencio, que se leería como "no hay más".
PAGINAS_MAXIMAS = 10

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
            except httpx.HTTPError:
                # Una petición que no llegó a respuesta igual salió a la red, y la bitácora
                # existe para poder acreditar cuánto se consultó. Sin esto los timeouts no
                # quedaban registrados, o sea el registro subestimaba el tráfico generado
                # justo en las corridas donde la plataforma iba peor. Se anota con estado 0,
                # que ningún código HTTP usa.
                self.bitacora.append((time.time(), url, 0))
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
                f"En {competencia!r} las diligencias del ministro de fe NO están en la tabla "
                "de Historia: viven en un panel propio (`diligenciaCob`) con otra estructura, "
                "que este proyecto todavía no lee. Medido sobre una respuesta real: los "
                "trámites de Historia son 'Actuación', 'Resolución' y 'Escrito', nunca "
                "'Actuación Receptor'.\n\n"
                "Se rechaza en vez de devolver la lista vacía que la Historia produciría, "
                "porque esa lista se leería como 'no hubo actuaciones' cuando lo cierto es "
                "'no las estoy leyendo'."
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
        informa" y "no ocurrió" son cosas distintas.
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

        # Los demás paneles no llevan el cuaderno en la fila, así que si el sitio los repite en
        # cada uno llegarían duplicados. Se deduplica por el contenido, que es correcto tanto
        # si el panel es global como si fuera por cuaderno: en el segundo caso las filas
        # difieren y se conservan todas.
        def _juntar(leer, declarado):
            if declarado is None:
                return None
            vistos: dict[str, object] = {}
            for pagina, _ in paginas:
                for fila in leer(pagina, competencia):
                    vistos.setdefault(fila.model_dump_json(), fila)
            return list(vistos.values())

        return DetalleCausa(
            historia=historia,
            litigantes=_juntar(parse_litigantes, spec.litigantes),
            notificaciones=_juntar(parse_notificaciones, spec.notificaciones),
            liquidaciones=_juntar(parse_liquidaciones, spec.liquidaciones),
            materias=_juntar(parse_materias, spec.materias),
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
