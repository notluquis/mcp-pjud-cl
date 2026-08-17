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
import time

import httpx

from .parser import (
    Actuacion,
    CausaEncontrada,
    actuaciones_receptor,
    parse_cuadernos,
    parse_resultados,
)

BASE = "https://oficinajudicialvirtual.pjud.cl"
PORTADA = "https://www.pjud.cl/"

#: Enlace que la propia institución publica en la portada de www.pjud.cl como acceso
#: público a la consulta de causas. No requiere Clave Única.
ENTRADA = f"{BASE}/includes/sesion-consultaunificada.php"

INTERVALO_MINIMO = 5.0

COMPETENCIAS = {
    "suprema": 1,
    "apelaciones": 2,
    "civil": 3,
    "laboral": 4,
    "penal": 5,
    "cobranza": 6,
    "familia": 7,
}

#: Rutas verificadas. Las demás competencias existen en el sitio pero no están probadas
#: acá, así que se rechazan en vez de adivinar.
MODULOS = {"civil": "civil"}


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


class PjudClient:
    def __init__(self, contacto: str, intervalo: float = INTERVALO_MINIMO) -> None:
        if intervalo < INTERVALO_MINIMO:
            raise ValueError(
                f"El intervalo mínimo entre consultas es {INTERVALO_MINIMO}s "
                "(cláusula CUARTA de las condiciones de uso). No se puede bajar."
            )
        self.intervalo = intervalo
        self._http = httpx.Client(
            headers={
                "User-Agent": f"mcp-pjud/0.1 (+contacto: {contacto})",
                "Accept-Language": "es-CL,es;q=0.9",
            },
            follow_redirects=True,
            timeout=30.0,
        )
        self._ultima = 0.0
        self._adir: str | None = None
        self._token: str | None = None
        self.bitacora: list[tuple[float, str, int]] = []

    def __enter__(self) -> PjudClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cerrar()

    def cerrar(self) -> None:
        self._http.close()

    # -- transporte -------------------------------------------------------------

    def _esperar(self) -> None:
        pendiente = self.intervalo - (time.monotonic() - self._ultima)
        if pendiente > 0:
            time.sleep(pendiente)

    def _req(self, metodo: str, url: str, **kw) -> httpx.Response:
        self._esperar()
        r = self._http.request(metodo, url, **kw)
        self._ultima = time.monotonic()
        self.bitacora.append((time.time(), url, r.status_code))

        if r.status_code in (403, 429):
            raise PjudBloqueado(
                f"El Poder Judicial respondió {r.status_code} a {url}. "
                "Detención total: no se reintenta ni se evade. Revisar si la IP quedó "
                "bloqueada antes de volver a consultar."
            )
        r.raise_for_status()
        return r

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
        assert self._adir is not None
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
        try:
            return MODULOS[competencia.lower()]
        except KeyError:
            raise ValueError(
                f"Competencia {competencia!r} no implementada. Verificadas: "
                f"{', '.join(sorted(MODULOS))}."
            ) from None

    def buscar_por_rit(
        self,
        tipo: str,
        rol: int,
        anio: int,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
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
        html_ = self._ajax(
            f"{modulo}/consultaRit{modulo.capitalize()}.php",
            {
                "conTipoCausa": tipo.upper(),
                "conRolCausa": str(rol),
                "conEraCausa": str(anio),
                "conCompetencia": str(COMPETENCIAS[competencia.lower()]),
                "conCorte": str(corte or 0),
                "conTribunal": str(tribunal or 0),
                "conCaratulado": "",
            },
        )
        return parse_resultados(html_)

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
    ) -> list[CausaEncontrada]:
        """Busca causas por nombre de litigante.

        La plataforma exige al menos dos de los tres campos de nombre. El año NO cuenta
        para ese mínimo: se comprobó que "apellido paterno + año" es rechazado mientras
        que "paterno + materno" es aceptado.

        El tribunal es obligatorio acá, a diferencia de la búsqueda por rol. Es una
        limitación del sitio, no de este cliente: no se puede buscar a alguien sin saber
        en qué tribunal está su causa.
        """
        modulo = self._modulo(competencia)
        if sum(1 for x in (nombre, apellido_paterno, apellido_materno) if x.strip()) < 2:
            raise ValueError(
                "La búsqueda por nombre exige al menos dos de estos tres campos: nombre, "
                "apellido paterno, apellido materno. El año no cuenta para ese mínimo."
            )
        if tribunal is None:
            raise ValueError(
                "La búsqueda por nombre exige tribunal. La plataforma no permite buscar "
                "por nombre en todos los tribunales a la vez."
            )
        html_ = self._ajax(
            f"{modulo}/consultaNombre{modulo.capitalize()}.php",
            {
                "radio-group": "N",
                "nomNombre": nombre,
                "nomApePaterno": apellido_paterno,
                "nomApeMaterno": apellido_materno,
                "nomEra": str(anio) if anio else "",
                "nomNombreJur": "",
                "nomEraJur": "",
                "nomCompetencia": str(COMPETENCIAS[competencia.lower()]),
                "nomTribunal": str(tribunal),
                "corteNom": str(corte or 0),
            },
        )
        return parse_resultados(html_)

    def buscar_por_rut_juridica(
        self,
        rut: int,
        digito_verificador: str,
        anio: int | None = None,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
    ) -> list[CausaEncontrada]:
        """Busca causas de una persona jurídica por su RUT.

        Es la única vía para personas jurídicas, que no tienen Clave Única y por lo tanto
        no aparecen en "Mis Causas".
        """
        modulo = self._modulo(competencia)
        if not str(digito_verificador).strip():
            raise ValueError("Falta el dígito verificador del RUT.")
        if tribunal is None:
            raise ValueError("La búsqueda por RUT de persona jurídica exige tribunal.")
        html_ = self._ajax(
            f"{modulo}/consultaJuridica{modulo.capitalize()}.php",
            {
                "rutJur": str(rut),
                "dvJur": str(digito_verificador).upper(),
                "eraJur": str(anio) if anio else "",
                "jurCompetencia": str(COMPETENCIAS[competencia.lower()]),
                "jurTribunal": str(tribunal),
                "corteJur": str(corte or 0),
            },
        )
        return parse_resultados(html_)

    def buscar_por_fecha(
        self,
        desde: str,
        hasta: str,
        competencia: str = "civil",
        tribunal: int | None = None,
        corte: int | None = None,
    ) -> list[CausaEncontrada]:
        """Busca causas ingresadas en un rango de fechas, en formato DD/MM/AAAA.

        Un solo día en un solo tribunal puede devolver decenas de causas, así que conviene
        acotar el rango.
        """
        modulo = self._modulo(competencia)
        if not desde.strip() or not hasta.strip():
            raise ValueError("La búsqueda por fecha exige fecha inicial y fecha final.")
        if tribunal is None:
            raise ValueError("La búsqueda por fecha exige tribunal.")
        html_ = self._ajax(
            f"{modulo}/consultaFecha{modulo.capitalize()}.php",
            {
                "fecDesde": desde,
                "fecHasta": hasta,
                "fecCompetencia": str(COMPETENCIAS[competencia.lower()]),
                "fecTribunal": str(tribunal),
                "corteFec": str(corte or 0),
            },
        )
        return parse_resultados(html_)

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
        causas = self.buscar_por_rit(tipo, rol, anio, competencia, tribunal, corte)
        if not causas:
            return []

        html_ = self.detalle(causas[0].referencia, competencia)
        cuadernos = parse_cuadernos(html_)

        # El detalle despliega la Historia de un solo cuaderno. Una causa con cuaderno
        # de apremio esconde ahí actuaciones que no están en el principal, así que se
        # recorren todos: devolver sólo el que vino por defecto daría una respuesta
        # aparentemente completa a la que le faltan justo las diligencias del apremio.
        if len(cuadernos) <= 1:
            nombre = cuadernos[0].nombre if cuadernos else ""
            return actuaciones_receptor(html_, nombre)

        actuaciones = []
        for cuaderno in cuadernos:
            pagina = self.detalle(cuaderno.referencia, competencia)
            actuaciones.extend(actuaciones_receptor(pagina, cuaderno.nombre))
        return actuaciones
