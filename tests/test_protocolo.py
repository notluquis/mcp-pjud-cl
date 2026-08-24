"""Tests del límite del protocolo MCP: lo que de verdad recibe el modelo.

Los demás tests llegan hasta el parser o hasta el cliente. Ninguno cruzaba el protocolo, así
que la garantía central del proyecto (regla 4: fallo ruidoso, nunca lista vacía) quedaba sin
verificar justo en el punto donde se consume. El parser levanta `EstructuraInesperada`, pero
quien lee la respuesta es un modelo al otro lado de una sesión MCP, y entre los dos hay una
capa del SDK que decide qué le llega.

Hoy esa capa propaga el mensaje: `mcp/server/mcpserver/tools/base.py` envuelve la excepción
en `ToolError` con el texto original, y `server.py` lo devuelve como `CallToolResult` con
`is_error`. Eso es un detalle interno del SDK, y `pyproject.toml` pide `mcp` sin techo de
versión. Si una versión futura enmascarara el mensaje, el modelo vería "error al ejecutar la
herramienta" sin explicación y se lo resumiría al abogado como "no encontré actuaciones": el
falso negativo que el parser evita, reaparecido una capa más arriba.

Sin red. El cliente HTTP va doblado con `httpx.MockTransport`, igual que en `test_client.py`,
y la sesión MCP corre en memoria dentro del mismo proceso.

Tres cosas medidas del SDK que conviene tener escritas, porque acotan lo que estos tests
cubren:

- El envoltorio del SDK va en inglés: el modelo recibe `"Error executing tool <nombre>: "` y
  después el mensaje del parser en español, entero.
- `MCPError` y sus subclases NO pasan por `is_error`: el SDK las re-lanza como error JSON-RPC
  de primer nivel. Sólo una excepción común se convierte en `CallToolResult(is_error=True)`.
  Si algún día este proyecto levantara algo que derive de `MCPError`, tomaría otro camino y
  estos tests no lo verían.
- El SDK ya valida el contenido estructurado contra el esquema, en dos lugares. La
  comprobación explícita de acá es redundante hoy a propósito: es la mitad que sobrevive si
  el SDK deja de hacerlo.
"""

import asyncio
import base64
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

import httpx
import jsonschema
import pytest
from mcp.client import Client
from mcp.server import MCPServer
from mcp.shared.dispatcher import ProgressFnT
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    SERVER_INFO_META_KEY,
    BlobResourceContents,
    CallToolResult,
    Completion,
    EmbeddedResource,
    Icon,
    ListToolsResult,
    Prompt,
    ResourceLink,
    ResourceTemplateReference,
    Tool,
)

from mcp_pjud import server as servidor
from mcp_pjud.client import (
    CARACTERES_DE_UNA_RESPUESTA,
    DOCUMENTOS,
    LIMITE_EMBEBIDO,
    MAXIMO_RANGOS,
    MODULOS,
    PjudClient,
)
from mcp_pjud.juris import BUSCADORES
from mcp_pjud.parser import SIN_RESULTADOS, EstructuraInesperada, parse_resultados

# Los PDF de prueba y su constructor viven en test_client.py, que es donde se prueba lo que
# hacen. Acá interesa otra cosa: en qué forma cruzan el protocolo.
from .test_client import (
    PDF_CON_TEXTO,
    PDF_ESCANEADO,
    _cliente_de_documentos,
    _con_marcadores,
    _pdf,
    _pdf_paginas,
)

FIXTURES = Path(__file__).parent / "fixtures"

#: Una respuesta real de la plataforma: un listado de búsqueda por rol en civil, con su fila
#: y su total declarado.
LISTADO = (FIXTURES / "busqueda_rit_civil.html").read_text(encoding="utf-8")

#: El mismo listado, con el control que abre el detalle renombrado. Es el cambio de estructura
#: que ocurriría de verdad si la plataforma renombrara esa función de JavaScript: la respuesta
#: sigue trayendo la causa, y el parser deja de poder leerla. Sin filas legibles y sin el
#: mensaje de "sin resultados", `parse_resultados` levanta `EstructuraInesperada`.
LISTADO_ROTO = LISTADO.replace("detalleCausaCivil", "verFichaDeLaCausa")

#: Lo que responde la plataforma cuando la búsqueda es legítima y no hay coincidencias. El
#: texto sale del parser y no se escribe acá: si cambiara en un lado y no en el otro, este
#: test estaría midiendo una respuesta que la plataforma ya no da.
LISTADO_VACIO = f"<div class='panel'><p>{SIN_RESULTADOS}</p></div>"

#: Lo mínimo que `abrir_sesion` necesita derivar de la portada: el prefijo de rutas y el token
#: de los modales, los dos interpolados en el HTML real y versionados por despliegue.
PORTADA = "<html><script>var adir = 'ADIR_1'; token: '" + "0" * 32 + "';</script></html>"

#: Las plantillas que el servidor tiene que anunciar. Van escritas y no derivadas de
#: `mcp._prompt_manager`: un guardia que saca de ahí la lista que después compara se pone
#: verde con las tres borradas, porque estaría comparando el registro consigo mismo.
PLANTILLAS = frozenset({"computar-plazo", "revisar-causa", "verificar-cita"})

HERRAMIENTA = "buscar_causa_por_rit"
ARGUMENTOS = {"tipo": "E", "rol": 468, "anio": 2026}


def _responder(
    cuerpo: str,
    detalle: str | None = None,
    estado_busqueda: int = 200,
    segundo_detalle: str | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Doble del sitio: la portada de la que se deriva la sesión, el listado y el detalle.

    `estado_busqueda` permite responder un 403 y llegar a la detención total, que es el otro
    mensaje que la directiva le promete al modelo.

    Cualquier otra ruta revienta en vez de responder algo plausible: un doble que contesta a
    una petición que el test no previó mide otra cosa que la que dice medir.
    """

    pedidos_de_detalle: list[str] = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        url = str(peticion.url)
        if url.endswith("sesion-consultaunificada.php"):
            return httpx.Response(200, text="")
        if url.endswith("consultaUnificada.php"):
            return httpx.Response(200, text=PORTADA)
        if url.endswith("/civil/consultaRitCivil.php"):
            return httpx.Response(estado_busqueda, text=cuerpo)
        if detalle is not None and url.endswith("/civil/modal/causaCivil.php"):
            # El segundo detalle es el cuaderno que no vino desplegado, y se sirve sólo desde
            # la segunda vuelta: si el recorrido pidiera de más, la cuenta lo nota.
            pedidos_de_detalle.append(url)
            if segundo_detalle is not None and len(pedidos_de_detalle) > 1:
                return httpx.Response(200, text=segundo_detalle)
            return httpx.Response(200, text=detalle)
        raise AssertionError(f"petición no prevista por el doble: {peticion.method} {url}")

    return responder


def _llamar(
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: str,
    *,
    herramienta: str = HERRAMIENTA,
    argumentos: dict | None = None,
    detalle: str | None = None,
    estado_busqueda: int = 200,
    segundo_detalle: str | None = None,
    servidor_mcp=None,
    progreso: ProgressFnT | None = None,
) -> CallToolResult:
    """Llama la herramienta a través de una sesión MCP real y devuelve lo que viaja por el cable.

    `Client(mcp)` es API pública del SDK y conecta el servidor en el mismo proceso, sin red y
    sin sockets.
    """
    # El contacto se lee del entorno UNA vez, al importar `server`, y para cuando corre este
    # test el módulo ya está importado por otros. `monkeypatch.setenv` no lo tocaría: hay que
    # reemplazar el valor ya leído.
    monkeypatch.setattr(servidor, "_CONTACTO", "test@example.cl")
    # El mismo idioma que usa el resto de la suite para no dormir de verdad. Anular `_esperar`
    # con una subclase sacaría el balde de fichas del camino ejercitado, y el ritmo es la
    # cláusula CUARTA implementada en código: conviene que siga corriendo aunque no se mida acá.
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)

    def fabricar(contacto: str) -> PjudClient:
        cliente = PjudClient(contacto)
        cliente._http = httpx.Client(
            transport=httpx.MockTransport(
                _responder(cuerpo, detalle, estado_busqueda, segundo_detalle)
            )
        )
        return cliente

    monkeypatch.setattr(servidor, "PjudClient", fabricar)

    async def ida_y_vuelta() -> CallToolResult:
        async with Client(servidor_mcp or servidor.mcp) as cliente:
            return await cliente.call_tool(
                herramienta, argumentos or ARGUMENTOS, progress_callback=progreso
            )

    return asyncio.run(ida_y_vuelta())


def _anunciada() -> Tool:
    """La herramienta tal como `list_tools` la anuncia.

    El esquema de salida sólo sirve como contrato si se lee de ahí y no del código. Va aparte
    de `_llamar` porque dos de las tres pruebas no lo necesitan, y pedirlo igual levantaba una
    sesión de más en cada llamada.
    """

    async def anunciar() -> Tool:
        async with Client(servidor.mcp) as cliente:
            anunciadas = await cliente.list_tools()
            herramienta = next((t for t in anunciadas.tools if t.name == HERRAMIENTA), None)
            assert herramienta is not None, (
                f"el servidor ya no anuncia {HERRAMIENTA!r}. Sin el default, `next` levanta "
                "`StopIteration` dentro de una corrutina y Python la convierte en un "
                "`RuntimeError` que no nombra ni la herramienta ni `list_tools`."
            )
            return herramienta

    return asyncio.run(anunciar())


def _texto(resultado: CallToolResult) -> str:
    """Todo el texto que el modelo alcanza a leer del resultado."""
    return "\n".join(bloque.text for bloque in resultado.content if bloque.type == "text")


def test_la_bitacora_sale_por_el_error_estandar_y_no_por_el_canal(monkeypatch) -> None:
    """Por stdio, la salida estándar ES el protocolo.

    Medido con un `print` de más dentro de una herramienta: el cliente levanta
    `ValidationError: Invalid JSON: expected value at line 1 column 1`. Este SDK sobrevive y
    sigue, pero eso depende del cliente y nadie lo garantiza, así que el manejador va clavado
    a `sys.stderr`.

    Y se comprueba que cuelgue del logger de ESTE paquete con la propagación apagada. El atajo
    sería `logging.basicConfig`, y está medido lo que cuesta: `httpx` registra la URL completa
    en INFO, y ahí viaja `documento_referencia`.
    """
    import logging
    import sys

    registro = logging.getLogger("mcp_pjud")
    antes = list(registro.handlers)
    monkeypatch.setattr(servidor.mcp, "run", lambda *a, **k: None)
    try:
        servidor.main()
        nuevos = [h for h in registro.handlers if h not in antes]
        assert nuevos, "`main` no dejó por dónde salga la bitácora"
        for manejador in nuevos:
            assert isinstance(manejador, logging.StreamHandler)
            assert manejador.stream is sys.stderr, (
                "la bitácora sale por la salida estándar, que por stdio es el canal del "
                "protocolo: cada línea le llega al cliente como JSON inválido"
            )
        assert registro.propagate is False, (
            "con la propagación encendida, encender la raíz para ver esto enciende también "
            "`httpx`, que registra la URL completa con la referencia del documento adentro"
        )
    finally:
        for manejador in [h for h in registro.handlers if h not in antes]:
            registro.removeHandler(manejador)
        registro.propagate = True


@pytest.mark.parametrize(
    ("pedido", "esperado"),
    [
        pytest.param(None, "INFO", id="por-defecto"),
        pytest.param("DEBUG", "DEBUG", id="pedido"),
        pytest.param("debug", "DEBUG", id="minuscula"),
        # Los dos que impedían arrancar: `setLevel` levanta `ValueError: Unknown level` y el
        # proceso muere antes de saludar, o sea una errata en una variable de entorno deja al
        # abogado sin la herramienta.
        pytest.param("", "INFO", id="vacio"),
        pytest.param("DEBUGG", "INFO", id="con-errata"),
    ],
)
def test_el_nivel_de_la_bitacora_nunca_impide_arrancar(pedido, esperado, monkeypatch) -> None:
    """Y el valor por defecto es el que la documentación promete.

    La guía dice que `MCP_PJUD_BITACORA` controla el nivel y que por defecto va en `INFO`. Sin
    esto, el código y esa promesa podían separarse, y encima un valor mal escrito tumbaba el
    servidor entero en vez de degradarse.
    """
    import importlib

    if pedido is None:
        monkeypatch.delenv("MCP_PJUD_BITACORA", raising=False)
    else:
        monkeypatch.setenv("MCP_PJUD_BITACORA", pedido)
    recargado = importlib.reload(servidor)
    try:
        quedo = recargado.NIVEL_BITACORA
        assert esperado == quedo, (
            f"con MCP_PJUD_BITACORA={pedido!r} el nivel quedó en {quedo!r} y tiene que ser "
            f"{esperado!r}"
        )
    finally:
        monkeypatch.delenv("MCP_PJUD_BITACORA", raising=False)
        importlib.reload(servidor)


def test_el_mensaje_del_parser_sobrevive_el_viaje(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un cambio de estructura tiene que llegar al modelo DICIENDO qué pasó.

    Sin esto, el SDK podría empezar a devolver un error genérico sin el mensaje, y ahí el
    modelo no tiene cómo distinguir "la plataforma cambió y no puedo leerla" de "no hay
    actuaciones". Lo segundo se le informa al abogado como que no corre ningún plazo.
    """
    # La frase se deriva del parser en vez de escribirse acá: es el mismo dato y tiene una
    # sola fuente. De paso comprueba que el parser sigue levantando, que es la mitad de abajo
    # de esta misma garantía.
    with pytest.raises(EstructuraInesperada) as levantada:
        parse_resultados(LISTADO_ROTO, "civil")
    frase = str(levantada.value).split(".")[0]
    assert len(frase) > 20, (
        "el mensaje del parser quedó demasiado corto para significar algo, y una frase vacía "
        "haría que este test pase sin verificar nada"
    )

    resultado = _llamar(monkeypatch, LISTADO_ROTO)

    assert resultado.is_error, (
        "un cambio de estructura llegó al modelo como resultado exitoso: lo va a leer como "
        "que la consulta se hizo y no encontró nada"
    )
    assert frase in _texto(resultado), (
        "el resultado viene marcado como error pero sin el mensaje del parser. El modelo sabe "
        f"que algo falló y no qué: esperaba encontrar {frase!r} en {_texto(resultado)!r}"
    )


def test_una_busqueda_sin_coincidencias_no_se_parece_a_un_parseo_roto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Las dos respuestas podrían viajar como el mismo arreglo vacío, y significan lo opuesto.

    "No hay causas con ese rol" es una respuesta. "No pude leer el listado" es un fallo, y si
    llegaran idénticos el modelo informaría el segundo como el primero.

    Lo que este test verifica, dicho con precisión porque la primera redacción prometía de
    más: que la DEFENSA EN CAPAS impide que un listado ilegible llegue como lista vacía, no
    que el parser sea la capa que lo impide. Se midió ablandando `parse_resultados` para que
    devolviera `[]` en vez de levantar, y el test siguió verde: `_paginado` corta antes, porque
    el listado declara un total de registros que no calza con las filas que se pudieron leer.

    Eso no lo invalida, lo describe: la garantía es real y la sostienen dos guardias, no uno.
    Y no es reemplazable por un caso donde sólo actúe el parser, porque para eso el listado
    tendría que declarar total cero, y la plataforma esa forma no la emite: cero resultados
    llegan con el aviso de "sin resultados", que es la otra pata de este mismo test.
    """
    vacio = _llamar(monkeypatch, LISTADO_VACIO)
    roto = _llamar(monkeypatch, LISTADO_ROTO)

    assert not vacio.is_error, (
        "una búsqueda legítima sin coincidencias llegó como error: eso empuja a reintentar o "
        "a informar una falla donde la plataforma respondió bien"
    )
    assert vacio.structured_content == {"result": []}, (
        f"la búsqueda sin coincidencias tiene que entregar la lista vacía, y entregó "
        f"{vacio.structured_content!r}"
    )
    # Se comparan los cuerpos y no `is_error`, que las dos afirmaciones de arriba ya fijan: un
    # `!=` sobre el par pasaría siempre y no cuidaría nada. Esto sí puede fallar, y falla justo
    # en lo que dice el título: que las dos viajen como el mismo arreglo vacío.
    assert roto.structured_content != vacio.structured_content, (
        "'sin resultados' y 'no pude leer el listado' llegan al modelo con el mismo cuerpo"
    )
    assert roto.is_error, "el listado ilegible tiene que llegar marcado como error"
    # Y que sea un error de ESTRUCTURA, no cualquiera. El doble levanta `AssertionError` ante
    # una ruta no prevista, y el SDK convierte cualquier excepción común en un resultado con
    # `is_error`: sin esto, un cambio de rutas dejaría el test verde midiendo un error de
    # plomería del propio doble en vez del que dice medir.
    assert "petición no prevista" not in _texto(roto), (
        f"el error no vino del parseo sino del doble: {_texto(roto)}"
    )


def test_el_contenido_estructurado_valida_contra_el_esquema_anunciado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El esquema que el servidor anuncia tiene que describir lo que el servidor devuelve.

    La especificación MCP lo exige con MUST, y acá el costo de incumplirlo es concreto: un
    cliente que valide descarta la respuesta, y el abogado se queda sin el dato. El SDK hoy
    valida por su cuenta dentro de `call_tool`, así que esta comprobación es redundante a
    propósito: es la mitad que no depende de que el SDK siga haciéndolo.
    """
    resultado = _llamar(monkeypatch, LISTADO)
    herramienta = _anunciada()

    esquema = herramienta.output_schema
    assert esquema, "la herramienta dejó de anunciar esquema de salida"
    # Control negativo. Un esquema que no rechaza nada convierte la validación de abajo en un
    # trámite que pasa siempre, y el test parecería estar cuidando algo.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"result": "esto no es una lista de causas"}, esquema)

    # Primero que no sea error, y con el texto del SDK adentro. Si el esquema y la salida
    # divergen, el SDK lo detecta ANTES y devuelve un resultado con `is_error` y sin contenido
    # estructurado: sin esta línea el test reventaría más abajo diciendo que el servidor no
    # devolvió nada, que culpa a la causa equivocada y además nunca llega a validar.
    assert not resultado.is_error, (
        f"la llamada con datos buenos llegó como error: {_texto(resultado)}"
    )
    assert resultado.structured_content is not None, (
        "la herramienta anuncia esquema de salida y no devolvió contenido estructurado"
    )
    jsonschema.validate(resultado.structured_content, esquema)


#: El detalle real de la misma causa del listado, con su único cuaderno.
DETALLE = (FIXTURES / "detalle_causa_civil.html").read_text(encoding="utf-8")

#: Los argumentos con que se pide ese detalle. El tribunal va porque en civil el rol se numera
#: por juzgado y sin él la causa es ambigua.
ARGUMENTOS_DEL_DETALLE = {"tipo": "E", "rol": 468, "anio": 2026, "tribunal": 162}


def test_el_detalle_dice_lo_mismo_aunque_ya_no_anuncie_esquema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soltar el esquema de salida del detalle no le quita una letra al texto que el modelo lee.

    Se soltó porque su esquema pesaba el 36% del catálogo, y el catálogo entero se difiere si
    pasa del 10% de la ventana del cliente: la herramienta que el modelo no ve no la puede
    pedir. La apuesta fue que el SDK arma el bloque de texto ANTES de la rama que valida contra
    el esquema, así que lo único que se pierde es `structuredContent`.

    Eso era una lectura de `func_metadata.py`, y una lectura no se cae cuando el SDK cambia.
    El gemelo declara el esquema sobre la MISMA función y se compara lo que viaja.
    """
    gemelo = MCPServer("gemelo")
    gemelo.tool(structured_output=True)(servidor.obtener_detalle_causa)

    sin_esquema = _llamar(
        monkeypatch,
        LISTADO,
        herramienta="obtener_detalle_causa",
        argumentos=ARGUMENTOS_DEL_DETALLE,
        detalle=DETALLE,
    )
    con_esquema = _llamar(
        monkeypatch,
        LISTADO,
        herramienta="obtener_detalle_causa",
        argumentos=ARGUMENTOS_DEL_DETALLE,
        detalle=DETALLE,
        servidor_mcp=gemelo,
    )

    assert not sin_esquema.is_error, _texto(sin_esquema)
    assert not con_esquema.is_error, _texto(con_esquema)
    # El control: si el gemelo tampoco trajera contenido estructurado, la comparación de abajo
    # sería entre dos respuestas iguales por la razón equivocada y pasaría siempre.
    assert con_esquema.structured_content is not None
    assert sin_esquema.structured_content is None, (
        "el detalle volvió a anunciar esquema; el catálogo crece 12.286 caracteres"
    )
    assert _texto(sin_esquema) == _texto(con_esquema), (
        "sin el esquema el SDK ya no arma el mismo texto: lo que se perdió no es sólo el "
        "contenido estructurado, y el detalle tiene que volver a declararlo"
    )


#: Un listado que declara más resultados de los que caben en una página, con el bloque de
#: navegación REAL de una página intermedia, que es el que ofrece la siguiente.
#:
#: Se arma así y no tocando el listado entero porque el real declara un total de 1 y no ofrece
#: página siguiente: con eso el recorrido corta al primer intento y nunca llega a truncar.
_NAV_INTERMEDIA = re.sub(
    r"<div[^>]*>\s*Total de registros:.*?</div>",
    "",
    (FIXTURES / "nav_pagina_intermedia.html").read_text(encoding="utf-8"),
    flags=re.S,
)
_FILAS = LISTADO[: LISTADO.rindex("<tr", 0, LISTADO.index("Total de registros"))]
LISTADO_LARGO = _FILAS + (
    f"<tr><td colspan='5'><div>Total de registros: <b>500</b></div>{_NAV_INTERMEDIA}</td></tr>"
)


def test_el_aviso_de_truncacion_llega_al_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    """La directiva le promete al modelo que este error NO significa "no hay resultados".

    Dice textual que si una búsqueda excede el tope de páginas la herramienta falla en vez de
    devolver una lista recortada, y que ese error significa "hay más resultados de los que
    caben". Esa instrucción sólo sirve si el texto cruza el protocolo entero: si llegara
    opaco, el modelo tendría la instrucción y ninguna forma de saber que aplica, y una lista
    recortada informada como completa es un plazo que nadie revisó.

    `ResultadosTruncados` sólo aparecía en tests del lado del cliente.
    """
    resultado = _llamar(
        monkeypatch,
        LISTADO_LARGO,
        argumentos={**ARGUMENTOS, "paginas": 1},
    )

    texto = _texto(resultado)
    assert resultado.is_error, f"la truncación tiene que llegar como error, y llegó: {texto}"
    assert "500" in texto, (
        f"el modelo tiene que saber CUÁNTOS resultados hay para decidir si acota o sube el "
        f"tope, y el mensaje no los trae: {texto}"
    )
    assert "Acota la búsqueda o sube el tope" in texto, (
        f"el mensaje tiene que decir qué HACER, no sólo que falló: con un error opaco el "
        f"modelo informa 'no se encontró nada', que es lo contrario. Llegó: {texto}"
    )


def test_el_aviso_de_detencion_total_llega_al_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Es lo único que le dice al modelo que NO reintente.

    Ante un 403 la regla 3 exige detención total, sin reintento ni rotación. El modelo no
    tiene forma de saberlo salvo por este texto: si llegara opaco leería "algo falló" y el
    reintento es exactamente lo que convierte un bloqueo temporal en una IP baneada.
    """
    resultado = _llamar(monkeypatch, "bloqueado", estado_busqueda=403)

    texto = _texto(resultado)
    assert resultado.is_error
    assert "403" in texto, f"el modelo tiene que ver el código que lo detuvo: {texto}"


def test_la_cadena_avisa_su_progreso_por_el_canal_del_protocolo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lo que le permite al cliente distinguir "no respondió" de "todavía estoy trabajando".

    Una consulta son varias peticiones encadenadas, cada una con el intervalo de la cláusula
    CUARTA, y desde afuera eso se ve igual que un cuelgue. La primera sesión que usó esto de
    verdad reportó dos de cuatro minutos y los tres murieron con "no result received". La
    especificación 2025-11-25 dice que el cliente PUEDE reiniciar su reloj al recibir un
    aviso de progreso: ése es todo el punto.

    Se mide del lado del cliente, con una sesión real, porque el aviso cruza tres fronteras
    que ningún test del cliente ve: el hilo en que el SDK corre una herramienta síncrona, la
    inyección del contexto, y el canal del protocolo. Cualquiera de las tres rota deja la
    lista vacía sin que nada más se ponga en rojo.
    """
    avisos: list[tuple[float, float | None, str | None]] = []

    async def anotar(progress: float, total: float | None, message: str | None) -> None:
        avisos.append((progress, total, message))

    resultado = _llamar(monkeypatch, LISTADO, progreso=anotar)

    assert not resultado.is_error, f"la llamada falló: {_texto(resultado)}"
    assert avisos, (
        "la herramienta terminó sin avisar nada: para el cliente es indistinguible de una "
        "que se colgó, que es el problema que esto existe para resolver"
    )
    numeros = [p for p, _, _ in avisos]
    assert numeros == sorted(numeros), (
        f"el progreso retrocedió, y la especificación exige que aumente: {numeros}"
    )
    assert all(m for _, _, m in avisos), (
        f"un aviso sin mensaje dice que algo pasa y no qué: {avisos}"
    )


@pytest.mark.parametrize(
    ("cuadernos", "peticiones"),
    [
        # Desde un cliente FRÍO, que es como `server.py` abre uno en cada llamada: dos por
        # abrir sesión, una por buscar y una por el detalle. Con un cuaderno la página en la
        # mano ES ése y no se pide de nuevo.
        pytest.param(1, 4, id="un-cuaderno"),
        # Con dos, una más por el que no vino desplegado.
        pytest.param(2, 5, id="dos-cuadernos"),
    ],
)
def test_el_total_anunciado_es_el_de_las_peticiones_que_salen(
    monkeypatch: pytest.MonkeyPatch, cuadernos: int, peticiones: int
) -> None:
    """Un total que miente es peor que no anunciar ninguno.

    Es el argumento por el que `_paginado` NO anuncia total: su tope no es un pronóstico. La
    cadena del detalle sí lo sabe, y por eso lo dice, pero nadie comprobaba que fuera cierto.
    El testing de mutación lo encontró: `<= 1` por `< 1`, `return 0` por `return 1`, y el
    sumando de la sesión por otro, los tres sobrevivían.

    Se comprueban las dos cosas juntas, porque separadas no dicen nada: cuántas peticiones
    salieron de verdad, y qué total se le prometió al cliente en el último aviso.
    """
    principal = (FIXTURES / "detalle_causa_civil.html").read_text(encoding="utf-8")
    if cuadernos == 2:
        principal = (FIXTURES / "c1156_principal.html").read_text(encoding="utf-8")
    apremio = (FIXTURES / "c1156_apremio.html").read_text(encoding="utf-8")
    avisos: list[tuple[float, float | None, str | None]] = []

    async def anotar(progress: float, total: float | None, message: str | None) -> None:
        avisos.append((progress, total, message))

    resultado = _llamar(
        monkeypatch,
        LISTADO,
        herramienta="obtener_detalle_causa",
        argumentos={"tipo": "E", "rol": 468, "anio": 2026, "tribunal": 162},
        detalle=principal,
        segundo_detalle=apremio,
        progreso=anotar,
    )

    assert not resultado.is_error, f"la llamada falló: {_texto(resultado)}"
    ultimo, total, _ = avisos[-1]
    assert ultimo == peticiones, (
        f"salieron {ultimo} avisos y la cadena de {cuadernos} cuaderno(s) son {peticiones} "
        "peticiones desde un cliente frío: dos de sesión, la búsqueda, el detalle y los "
        "cuadernos que no vinieron puestos"
    )
    assert total == peticiones, (
        f"se le prometió al cliente un total de {total} y salieron {peticiones}. Un total que "
        "no calza es peor que no anunciar ninguno: el cliente dibuja una barra que miente"
    )


def test_un_aviso_que_revienta_no_cuesta_la_respuesta(monkeypatch: pytest.MonkeyPatch) -> None:
    """La respuesta YA se pagó en peticiones contra la plataforma: no la tira un canal roto.

    Los avisos van al cliente, y del cliente no se sabe nada: puede reventar dibujando lo que le
    llega. Si eso se propagara, se habría consultado al Poder Judicial para botar el resultado,
    que es lo peor de los dos mundos: el tráfico se generó igual y quien preguntaba se queda sin
    el dato y con un error que no habla de su causa.

    Va contra el canal de verdad y no contra el adaptador a mano: lo que importa es de qué TIPO
    llega el fallo después de cruzar el hilo, y eso no se adivina leyendo.
    """

    async def fallar(progress: float, total: float | None, message: str | None) -> None:
        raise RuntimeError("el cliente se cayó dibujando el progreso")

    resultado = _llamar(monkeypatch, LISTADO, progreso=fallar)

    assert not resultado.is_error, f"un aviso que falló se llevó la respuesta: {_texto(resultado)}"
    assert resultado.structured_content, "la respuesta tiene que llegar entera igual"


def test_un_cliente_que_cancela_detiene_la_cadena(monkeypatch: pytest.MonkeyPatch) -> None:
    """Y una cancelación es lo contrario: se propaga, y tiene que hacerlo.

    Es la forma en que un cliente que se fue llega hasta acá. `_req` avisa antes de CADA
    petición, así que tragarla en el primer aviso deja la cadena entera saliendo al Poder
    Judicial para una respuesta que ya nadie puede recibir. Eso es la cláusula CUARTA al revés,
    y pesa más que terminar una lectura que nadie pidió.

    No hace falta nombrar la clase: `CancelledError` hereda de `BaseException` y no de
    `Exception`, así que sube sola. Nombrarla costaría un bucle corriendo que en el hilo
    trabajador no hay.
    """

    async def cancelar(progress: float, total: float | None, message: str | None) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _llamar(monkeypatch, LISTADO, progreso=cancelar)


def test_sin_cliente_que_pida_progreso_la_respuesta_es_la_misma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin token de progreso el aviso es un no-op del SDK, y eso no puede costar la respuesta.

    Es la mitad que no se ve: la mayoría de las llamadas no piden progreso, y ahí el camino
    nuevo corre igual hasta el final. Que el resultado sea idéntico al de antes es lo que
    permite afirmar que avisar no cambia lo que se consulta.
    """
    con = _llamar(monkeypatch, LISTADO, progreso=None)
    assert not con.is_error, f"la llamada falló: {_texto(con)}"
    assert con.structured_content, "sin progreso la respuesta tiene que llegar igual de entera"


def test_las_plantillas_normalizan_la_competencia_antes_de_avisar() -> None:
    """El cliente acepta cualquier capitalización y las plantillas comparaban el valor crudo.

    Con `competencia="Civil"` el aviso de resolver el `tribunal` no salía, y un rol de civil sin
    tribunal no falla: abre la causa de otra persona. Es el mismo defecto que ya costó un
    `KeyError` en `_causa_pedida`, en otra capa.
    """
    from mcp_pjud.server import _si_falta_el_codigo

    for escrito in ("civil", "Civil", "CIVIL", " civil "):
        assert "`tribunal`" in _si_falta_el_codigo(escrito, None, None), (
            f"con competencia={escrito!r} la plantilla no avisa que falta el tribunal"
        )


def test_las_plantillas_no_mandan_el_codigo_que_la_competencia_no_usa() -> None:
    """Un código de más convierte una causa que existe en un falso negativo.

    Fijar una corte fuera de apelaciones excluye las causas radicadas en otra jurisdicción: lo
    dice la descripción de `CorteQueDesambigua`, y una plantilla que arma la llamada no puede
    contradecir al esquema que la describe.
    """
    from mcp_pjud.server import _identificacion

    civil = _identificacion("E", 468, 2026, "civil", tribunal=162, corte=46)
    assert "tribunal=162" in civil, f"civil se acota por tribunal y no lo lleva: {civil}"
    assert "corte=" not in civil, (
        f"civil llevaba la corte igual, y fijarla fuera de apelaciones excluye causas: {civil}"
    )

    # Y lo que se emite va normalizado: `PjudClient._modulo` sólo baja a minúscula, así que una
    # competencia con espacios se reconoce para avisar y después la instrucción la copiaba tal
    # cual, dejando una llamada que el cliente rechaza.
    con_espacios = _identificacion("E", 468, 2026, " Civil ", tribunal=162, corte=None)
    assert "competencia='civil'" in con_espacios, (
        f"la instrucción emite la competencia como llegó y así no se puede llamar: {con_espacios}"
    )

    apelaciones = _identificacion("Protección", 9999, 2019, "apelaciones", tribunal=162, corte=46)
    assert "corte=46" in apelaciones, f"apelaciones se acota por corte y no la lleva: {apelaciones}"
    assert "tribunal=" not in apelaciones, (
        f"apelaciones llevaba el tribunal, que ahí la plataforma no usa: {apelaciones}"
    )


def test_una_causa_que_no_se_encontro_no_llega_como_cero_actuaciones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La otra mitad del mismo falso negativo, y la que no tenía guardia.

    El test de abajo cubre un detalle ilegible. Éste cubre lo anterior: que la BÚSQUEDA no
    encuentre la causa. Ahí `actuaciones_receptor` devolvía `[]`, exactamente el mismo valor que
    una causa encontrada sin actuaciones de receptor.

    O sea un rol mal escrito, un año equivocado o el tribunal que no era se presentaban como una
    causa revisada sin diligencias, y sobre eso se computa un plazo que no existe.
    `detalle_causa` puede decirlo con `causa_encontrada`; una lista no tiene dónde.
    """
    resultado = _llamar(
        monkeypatch,
        LISTADO_VACIO,
        herramienta="obtener_actuaciones_receptor",
        argumentos={"tipo": "E", "rol": 468, "anio": 2026},
    )

    assert resultado.is_error, (
        f"una causa que no se encontró llegó como respuesta: {resultado.structured_content!r}. "
        "Cero actuaciones y causa inexistente son lo mismo para quien lee"
    )
    texto = _texto(resultado)
    assert "no signific" in texto.lower(), (
        f"el error no dice que esto NO es que la causa no tenga actuaciones: {texto}"
    )


def test_las_actuaciones_de_receptor_no_llegan_como_lista_vacia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La herramienta que da sentido al proyecto, cruzando el protocolo por primera vez.

    Acá una lista vacía se lee como "no hubo actuaciones del ministro de fe", que es
    exactamente el falso negativo que cuesta un plazo. Se le da un listado legible y un
    detalle que no lo es: si el detalle roto llegara como `[]`, el modelo informaría que la
    causa no tiene actuaciones cuando lo cierto es que no se pudieron leer.
    """
    resultado = _llamar(
        monkeypatch,
        LISTADO,
        herramienta="obtener_actuaciones_receptor",
        argumentos={"tipo": "E", "rol": 468, "anio": 2026},
        detalle="<html><body><p>Sesión expirada</p></body></html>",
    )

    assert resultado.is_error, (
        f"un detalle ilegible llegó como respuesta y no como error: "
        f"{resultado.structured_content!r}"
    )
    assert resultado.structured_content != {"result": []}, (
        "la herramienta que existe para no perder plazos entregó una lista vacía ante un "
        "detalle que no se pudo leer"
    )
    # Y que el error venga del parseo del detalle y no del doble. Es el mismo hueco que el
    # caso del listado ilegible, y se coló otra vez acá: si cambiara la ruta del modal, el
    # doble levantaría `AssertionError`, el SDK la convertiría en un resultado con `is_error`
    # y sin contenido, y las dos aserciones de arriba pasarían sin haber tocado el parser.
    texto = _texto(resultado)
    assert "petición no prevista" not in texto, (
        f"el error no vino de leer el detalle sino del doble: {texto}"
    )
    assert "historiaCiv" in texto, (
        f"el modelo tiene que ver QUÉ no se pudo leer, y el mensaje no lo dice: {texto}"
    )


# -- documentos: qué forma cruza el protocolo ------------------------------------
#
# Acá lo que se mide no es el parseo sino el SOBRE. Un documento puede viajar de dos maneras
# que la especificación distingue, y elegir mal no produce un error: produce una respuesta
# correcta que gasta el contexto de la conversación en un expediente que nadie pidió leer.


def _documento(
    contenido: bytes | None = None,
    *,
    texto: str | None = None,
    tipo: str = "application/pdf",
) -> Callable[[httpx.Request], httpx.Response]:
    """Doble del sitio para el camino de documentos: la sesión y el endpoint del archivo."""

    def responder(peticion: httpx.Request) -> httpx.Response:
        url = str(peticion.url)
        if url.endswith("sesion-consultaunificada.php"):
            return httpx.Response(200, text="")
        if "consultaUnificada.php" in url and "/documentos/" not in url:
            return httpx.Response(200, text=PORTADA)
        if "/civil/documentos/docuN.php" in url:
            if texto is not None:
                return httpx.Response(200, text=texto, headers={"content-type": tipo})
            return httpx.Response(200, content=contenido, headers={"content-type": tipo})
        raise AssertionError(f"petición no prevista por el doble: {peticion.method} {url}")

    return responder


def _con_doble(
    monkeypatch: pytest.MonkeyPatch, responder: Callable[[httpx.Request], httpx.Response]
) -> None:
    monkeypatch.setattr(servidor, "_CONTACTO", "test@example.cl")
    monkeypatch.setattr("mcp_pjud.client.time.sleep", lambda _: None)

    def fabricar(contacto: str) -> PjudClient:
        cliente = PjudClient(contacto)
        cliente._http = httpx.Client(transport=httpx.MockTransport(responder))
        return cliente

    monkeypatch.setattr(servidor, "PjudClient", fabricar)


#: Con la forma que tienen de verdad. La plataforma emite estas referencias como JWT, y eso
#: importa acá y no en el cliente: el enlace que devuelve la herramienta las lleva dentro de
#: una dirección, así que tienen que sobrevivir ida y vuelta por la plantilla del recurso. Con
#: un `ref-123` de fantasía, que no trae un solo carácter que haya que codificar, este camino
#: quedaba verde sin haberse ejercitado nunca.
REFERENCIA = "eyJhbGciOiJIUzI1NiJ9.eyJkb2MiOiIxMi0zNCJ9.abc-_XYZ123"


def _pedir_documento(referencia: str = REFERENCIA) -> CallToolResult:
    async def ida_y_vuelta() -> CallToolResult:
        async with Client(servidor.mcp) as cliente:
            return await cliente.call_tool(
                "obtener_documento",
                {
                    "documento_ruta": "docuN.php",
                    "documento_referencia": referencia,
                    "competencia": "civil",
                },
            )

    return asyncio.run(ida_y_vuelta())


def test_un_documento_chico_viaja_completo_en_la_respuesta(monkeypatch: pytest.MonkeyPatch):
    """El caso en que embeber vale la pena: una resolución de una página que el modelo tiene
    que leer ahora, no un puntero que exige otra vuelta."""
    _con_doble(monkeypatch, _documento(PDF_CON_TEXTO))

    resultado = _pedir_documento()

    assert not resultado.is_error, f"la llamada con datos buenos falló: {_texto(resultado)}"
    embebidos = [b for b in resultado.content if isinstance(b, EmbeddedResource)]
    assert len(embebidos) == 1, (
        f"un documento de {len(PDF_CON_TEXTO)} bytes tiene que viajar embebido, y llegaron "
        f"{[b.type for b in resultado.content]}"
    )
    recurso = embebidos[0].resource
    assert isinstance(recurso, BlobResourceContents), (
        "un PDF es binario: va como blob y no como texto, que sería una versión de él"
    )
    assert base64.b64decode(recurso.blob) == PDF_CON_TEXTO, "el archivo llegó alterado"


def test_un_documento_largo_viaja_como_enlace_y_no_como_contenido(
    monkeypatch: pytest.MonkeyPatch,
):
    """El ebook es el expediente entero, y meterlo en la respuesta gasta el contexto del
    abogado en algo que casi nunca hace falta leer completo.

    `ResourceLink` trae el tamaño, así que quien lo recibe puede decidir ANTES de gastarlo.
    Eso es lo que lo separa de mandar el PDF y esperar que a nadie le explote la ventana.
    """
    grande = _pdf(b"BT /F1 12 Tf 20 100 Td (X) Tj ET\n" * 2000)
    assert len(grande) > LIMITE_EMBEBIDO, "el caso de prueba tiene que pasar el umbral"
    _con_doble(monkeypatch, _documento(grande))

    resultado = _pedir_documento()

    assert not resultado.is_error, f"la llamada con datos buenos falló: {_texto(resultado)}"
    enlaces = [b for b in resultado.content if isinstance(b, ResourceLink)]
    assert len(enlaces) == 1, (
        f"un documento de {len(grande)} bytes tiene que viajar como enlace, y llegaron "
        f"{[b.type for b in resultado.content]}"
    )
    assert enlaces[0].size == len(grande), (
        "el enlace sin tamaño no sirve para decidir: es lo único que el cliente tiene para "
        f"saber qué le va a costar leerlo, y llegó {enlaces[0].size!r}"
    )
    assert not [b for b in resultado.content if isinstance(b, EmbeddedResource)], (
        "el enlace viajó Y el contenido también, o sea el umbral no ahorró nada"
    )
    # Y que el base64 no se haya colado por ningún otro lado del sobre, que es la forma en que
    # este ahorro se pierde sin que ninguna aserción de arriba se entere.
    entero = resultado.model_dump_json()
    assert base64.b64encode(grande[:600]).decode() not in entero, (
        "el archivo viajó igual, en algún otro bloque de la respuesta"
    )


def test_el_enlace_se_puede_leer_y_vuelve_a_consultar_al_poder_judicial(
    monkeypatch: pytest.MonkeyPatch,
):
    """Un `ResourceLink` que nadie puede leer es un puntero a la nada.

    Y se lee volviendo a consultar, no de una copia: este servidor no persiste documentos de
    terceros. El guardia mira las dos cosas, porque una implementación que guardara el archivo
    devolvería exactamente el mismo blob y pasaría la primera mitad.
    """
    grande = _pdf(b"BT /F1 12 Tf 20 100 Td (X) Tj ET\n" * 2000)
    peticiones: list[str] = []
    base = _documento(grande)

    def contando(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(str(peticion.url))
        return base(peticion)

    _con_doble(monkeypatch, contando)

    resultado = _pedir_documento()
    enlace = next(b for b in resultado.content if isinstance(b, ResourceLink))
    del peticiones[:]

    async def leer():
        async with Client(servidor.mcp) as cliente:
            return await cliente.read_resource(enlace.uri)

    leido = asyncio.run(leer())

    assert leido.contents, f"leer el enlace no devolvió nada: {leido}"
    contenido = leido.contents[0]
    assert isinstance(contenido, BlobResourceContents), f"el PDF llegó como {type(contenido)}"
    assert base64.b64decode(contenido.blob) == grande
    pedida = [u for u in peticiones if "/documentos/docuN.php" in u]
    assert pedida, (
        "leer el enlace no volvió a consultar al Poder Judicial, así que el documento quedó "
        f"guardado en alguna parte: {peticiones}"
    )
    assert REFERENCIA in unquote(pedida[0]), (
        f"la referencia no sobrevivió el viaje por la dirección del enlace: {pedida[0]}"
    )


@pytest.mark.parametrize(
    "referencia",
    [
        REFERENCIA,
        # Lo que la plataforma emite hoy son JWT, y con ese alfabeto no hay nada que
        # codificar: la dirección se arma igual de bien concatenando a mano. La referencia es
        # OPACA, o sea el proyecto no tiene contrato sobre su formato, así que el día que
        # traiga un `&` la concatenación parte la dirección en dos parámetros y el documento
        # que se pide es otro. Este caso es lo que hace que codificarla no sea decoración.
        "a&referencia=otra&b=1",
        "con espacio y signo+igual=",
        "#fragmento/con/barras?y=cola",
    ],
)
def test_la_referencia_sobrevive_el_viaje_por_la_direccion_del_enlace(referencia: str):
    """La plantilla del recurso es la que tiene que volver a sacar los tres datos intactos.

    Se mide contra el mismo parser de plantillas que usa el servidor al atender la lectura, y
    no contra una expectativa escrita a mano: lo que importa es qué extrae ÉL, no qué creemos
    que dice la RFC.
    """
    from mcp.shared.uri_template import UriTemplate

    uri = servidor._uri_del_documento("civil", "docuN.php", referencia)
    extraidos = UriTemplate.parse("pjud://documento{?competencia,ruta,referencia}").match(uri)

    assert extraidos == {
        "competencia": "civil",
        "ruta": "docuN.php",
        "referencia": referencia,
    }, f"la dirección {uri!r} no vuelve a dar los mismos tres datos: {extraidos}"


def test_lo_que_no_es_un_pdf_llega_como_error_y_no_como_documento(
    monkeypatch: pytest.MonkeyPatch,
):
    """La referencia caduca con la sesión, y una vencida responde HTTP 200 con una página.

    Si eso llegara al modelo como un archivo, el abogado recibiría algo que se ve como la
    resolución y es un aviso de sesión expirada. Es el falso positivo de la regla 4 con otra
    cara: no una lista vacía, un documento que no lo es.
    """
    aviso = '<html><script>swal("Aviso", "La sesion ha expirado");</script></html>'
    _con_doble(monkeypatch, _documento(texto=aviso, tipo="text/html"))

    resultado = _pedir_documento("ref-vencida")

    texto = _texto(resultado)
    assert resultado.is_error, f"una página de error llegó como documento: {resultado.content}"
    assert not [b for b in resultado.content if isinstance(b, EmbeddedResource | ResourceLink)], (
        "vino marcado como error y con el archivo adentro igual"
    )
    assert "petición no prevista" not in texto, (
        f"el error salió del doble y no del cliente: {texto}"
    )
    assert "La sesion ha expirado" in texto, (
        f"el modelo tiene que ver el aviso para saber que hay que repetir el detalle: {texto}"
    )


def test_un_pdf_ilegible_no_se_describe_como_escaneo(monkeypatch: pytest.MonkeyPatch):
    """El mismo falso positivo que el cliente cuida, en el lugar donde el modelo lo lee.

    Lo que llega al modelo es el bloque de texto, no el campo: si el resumen dijera "es un
    escaneo" de un archivo cifrado o truncado, el abogado recibiría una afirmación sobre el
    documento que este servidor nunca midió, y no tendría cómo notarlo.
    """
    truncado = PDF_CON_TEXTO[:120]
    _con_doble(monkeypatch, _documento(truncado))

    resultado = _pedir_documento()

    texto = _texto(resultado)
    assert not resultado.is_error, f"no poder describirlo no es no tenerlo: {texto}"
    assert "ESCANEO" not in texto, (
        f"un archivo que no se pudo abrir se informó como escaneo: {texto}"
    )
    assert "no se sabe" in texto, f"el resumen tiene que decir que NO se sabe, no callarlo: {texto}"
    assert [b for b in resultado.content if isinstance(b, EmbeddedResource)], (
        "el documento se entrega igual: no poder describirlo no es no tenerlo"
    )


def test_un_escaneo_se_declara_en_palabras_y_no_se_transcribe(monkeypatch: pytest.MonkeyPatch):
    """Lo que el modelo lee del sobre es el bloque de texto, así que el veredicto tiene que
    estar ahí y no sólo en un campo.

    Y tiene que decir que NO se le pasa OCR: sin eso, el modelo con una herramienta de OCR a
    mano lo transcribe por su cuenta y presenta el resultado como el texto de la resolución.
    """
    _con_doble(monkeypatch, _documento(PDF_ESCANEADO))

    resultado = _pedir_documento()

    texto = _texto(resultado)
    assert not resultado.is_error, f"un escaneo se entrega igual: {texto}"
    assert "ESCANEO" in texto, f"el veredicto no llegó en palabras: {texto}"
    assert "OCR" in texto, f"el sobre no dice que no se transcribe: {texto}"
    assert [b for b in resultado.content if isinstance(b, EmbeddedResource)], (
        "declarar que es un escaneo no es negarse a entregarlo"
    )


def test_un_pdf_mixto_se_declara_mixto_y_no_digital(monkeypatch: pytest.MonkeyPatch):
    """Lo que el modelo lee del sobre es el bloque de texto, no el campo.

    Decir "trae capa de texto" a secas sobre un expediente que mezcla resoluciones digitales
    con anexos escaneados hace que dé por transcribible un documento del que una parte son
    imágenes, y lo que dicen esas páginas no se puede citar desde acá.
    """
    from tests.test_client import PDF_MIXTO

    _con_doble(monkeypatch, _documento(PDF_MIXTO))

    texto = _texto(_pedir_documento())
    assert "MIXTO" in texto, f"el veredicto no distingue el mixto: {texto}"
    assert "1 de 2" in texto, f"no dice cuántas páginas traen texto: {texto}"
    assert "no se puede citar" in texto.lower(), f"no advierte qué no se puede citar: {texto}"


def test_el_sobre_dice_cuales_paginas_traen_texto_y_no_solo_cuantas(
    monkeypatch: pytest.MonkeyPatch,
):
    """El recorrido página por página ya se pagaba, y su resultado no llegaba al modelo.

    "3 de 5 páginas traen texto" no deja pedir nada: no dice si lo legible está al principio,
    al final o repartido. Y lo que el modelo lee es este bloque de texto, así que un campo que
    el sobre no diga es un campo que nadie puede usar.
    """
    _con_doble(monkeypatch, _documento(_pdf_paginas([True, True, False, False, True])))

    texto = _texto(_pedir_documento())

    assert "1-2, 5" in texto, f"los tramos con texto no llegaron al modelo: {texto}"


def test_una_lista_de_tramos_cortada_dice_hasta_donde_llego_y_no_afirma_lo_demas(
    monkeypatch: pytest.MonkeyPatch,
):
    """Es la regla 4 repartida por página.

    Una lista que termina en la 39 se lee como "de la 40 en adelante son imágenes", y eso es
    una afirmación que nadie midió: lo que pasó es que la enumeración se cortó en el tope. El
    sobre tiene que decir dónde termina lo que se miró, no dejarlo a la vista como si fuera
    todo el documento.
    """
    paginas = 2 * (MAXIMO_RANGOS + 5)
    _con_doble(monkeypatch, _documento(_pdf_paginas([k % 2 == 0 for k in range(paginas)])))

    texto = _texto(_pedir_documento())

    assert "NO se enumeró" in texto, f"el corte de la lista no se declaró: {texto}"
    assert f"la página {2 * MAXIMO_RANGOS - 1}" in texto, (
        f"no se dijo hasta qué página alcanzó la enumeración: {texto}"
    )
    # Y el tramo que queda sin enumerar empieza en la SIGUIENTE y termina en la última. Un
    # desfase acá manda a mirar una página que sí se enumeró, o deja una fuera del aviso.
    assert f"de la {2 * MAXIMO_RANGOS} a la {paginas} NO se enumeró" in texto, (
        f"el tramo no enumerado no empieza donde terminó la lista: {texto}"
    )
    assert "NO significa que no traigan" in texto, (
        f"el sobre deja leer el corte como que el resto son imágenes: {texto}"
    )


def test_los_marcadores_llegan_declarados_como_contenido_de_un_tercero(
    monkeypatch: pytest.MonkeyPatch,
):
    """Los marcadores son el índice del expediente y los escribe quien armó el PDF.

    O sea entran por un canal que parece metadato del archivo y son texto de un tercero que
    puede ser la contraparte. Van delimitados y con la advertencia, porque sin eso un
    marcador que diga "ignora lo anterior" llega al modelo con la voz del servidor.
    """
    con_indice = _con_marcadores(
        _pdf_paginas([True, False]), [("Demanda", 0, 0), ("Anexo escaneado", 1, 0)]
    )
    _con_doble(monkeypatch, _documento(con_indice))

    texto = _texto(_pedir_documento())

    assert "Demanda (página 1)" in texto, f"el índice del archivo no llegó: {texto}"
    assert "Anexo escaneado (página 2)" in texto, f"falta un marcador o su página: {texto}"
    assert "TERCERO" in texto, f"no se declaró de quién es ese texto: {texto}"
    assert "NO como instrucciones" in texto, (
        f"no se dijo que no se obedecen, que es lo que hace de esto un canal seguro: {texto}"
    )
    assert "<<< fin de los marcadores >>>" in texto, (
        f"el bloque no está delimitado, así que no se ve dónde termina: {texto}"
    )


def test_el_tamano_de_la_pagina_llega_al_modelo(monkeypatch: pytest.MonkeyPatch):
    """Es lo que anticipa qué costaría mirar una página que no se puede leer.

    Para un escaneo, mirarlo es la única vía, y con qué resolución mirarlo lo decide quien
    abre el archivo: acá sólo se dice cuánto mide.
    """
    _con_doble(monkeypatch, _documento(_pdf_paginas([False], cajas=["0 0 612 792"])))

    texto = _texto(_pedir_documento())

    assert "21,6 x 27,9 cm" in texto, f"el tamaño de la página no llegó: {texto}"


def _sobre_de(contenido: bytes) -> str:
    """El sobre en palabras de ese archivo, por el mismo camino que arma la respuesta.

    Se pide `embebido=False` en los dos lados de la comparación de abajo porque esa frase
    cambia de largo según el umbral, y lo que se mide acá es el índice y no la entrega.
    """
    cliente, _ = _cliente_de_documentos(
        httpx.Response(200, content=contenido, headers={"content-type": "application/pdf"})
    )
    return servidor._resumen(cliente.documento("docuN.php", REFERENCIA), embebido=False)


def _archivo_patologico(paginas: int, marcadores: int) -> bytes:
    """El peor caso para el sobre: alterna página sí página no y trae títulos larguísimos."""
    base = _pdf_paginas([k % 2 == 0 for k in range(paginas)])
    return _con_marcadores(base, [("T" * 300 + f" {i}", 0, 0) for i in range(marcadores)])


def test_el_sobre_distingue_digital_de_mixto_y_cuenta_bien_lo_que_falta():
    """Tres frases del sobre que nadie comparaba, encontradas con testing de mutación.

    El límite entre "digital" y "MIXTO" es una desigualdad estricta: con `<=`, un PDF cuyas
    páginas traen todas texto se anunciaría como mixto, o sea se le diría a quien lo lea que
    parte del documento son imágenes que no puede citar. Y la resta que dice cuántas faltan
    puede sumar en vez de restar, y ahí el número sale mayor que el total de páginas.
    """
    digital = _sobre_de(_pdf_paginas([True, True, True]))
    assert "es un PDF digital" in digital
    assert "MIXTO" not in digital, "todas traen texto: llamarlo mixto inventa páginas escaneadas"
    # Y no se enumeran los tramos: el veredicto ya dijo que son todas, así que repetir los
    # números es ruido en el único bloque que se lee sin abrir el archivo.
    assert "Traen texto las páginas" not in digital, (
        f"el sobre enumera tramos cuando todas las páginas traen texto: {digital}"
    )

    mixto = _sobre_de(_pdf_paginas([True, False, False]))
    assert "Es MIXTO: 1 de 3 páginas traen texto y las otras 2 son imágenes" in mixto, (
        f"la cuenta de las que faltan no es la resta: {mixto}"
    )

    assert "3 página(s)" in digital, f"el total de páginas no llegó al sobre: {digital}"


def test_el_sobre_del_documento_no_crece_con_el_archivo():
    """Todo el punto de los tramos y de los topes es que el índice sea de tamaño CONSTANTE.

    Un expediente real son uno o dos tramos, pero un archivo que alterna produce uno por
    página, y un PDF puede traer mil marcadores de trescientos caracteres. Sin topes, el sobre
    que existe para NO gastar el contexto pasa a ser lo que lo gasta.

    Se comparan dos archivos con un orden de magnitud de diferencia: lo único que puede
    cambiar entre los dos sobres son los dígitos de las cifras, no la cantidad de entradas.
    Los DOS tienen que pasar los topes, si no la comparación mide otra cosa: el primer intento
    puso 40 páginas en el chico, ahí los tramos cabían enteros y lo que creció fue el aviso de
    corte que el chico no traía.
    """
    chico = _sobre_de(_archivo_patologico(60, 30))
    grande = _sobre_de(_archivo_patologico(600, 300))

    assert len(grande) - len(chico) <= 80, (
        f"el sobre creció {len(grande) - len(chico)} caracteres al multiplicar el archivo por "
        "diez, así que algún tope dejó de acotar"
    )
    assert len(grande) < CARACTERES_DE_UNA_RESPUESTA, (
        f"el sobre en palabras son {len(grande)} caracteres y el presupuesto de una respuesta "
        f"entera son {CARACTERES_DE_UNA_RESPUESTA}: lo que sobra tiene que quedar para el "
        "documento"
    )


def _listado(modo: str) -> ListToolsResult:
    """`tools/list` tal como sale por el carril que se le pida.

    UNA llamada por sesión: `Client.list_tools` pasa por su propia caché, y con la pista de
    frescura puesta una segunda llamada podría estar mirando la copia en vez de lo que el
    servidor volvió a decir.
    """

    async def pedir() -> ListToolsResult:
        async with Client(servidor.mcp, mode=modo) as cliente:
            return await cliente.list_tools()

    return asyncio.run(pedir())


def test_el_catalogo_viaja_con_pista_de_frescura_por_el_carril_moderno():
    """Sin pista, el catálogo entero se vuelve a traer en cada arranque.

    `ttlMs: 0` es lo que trae el protocolo por defecto y significa "inmediatamente rancio". El
    catálogo de este servidor cambia una vez por versión, así que ese cero es puro gasto: el
    cliente arrastra decenas de miles de caracteres que ya tenía iguales.

    Se mira el carril MODERNO porque es el único donde el campo existe. La revisión se fija a
    mano en vez de dejar que el modo automático elija, para que el test siga midiendo el carril
    que dice medir. Es el mismo `_serialize` del SDK que rellena la pista cuando el servidor se
    levanta por stdio: lo que agrega el cable es el enmarcado JSON-RPC, no de dónde sale este
    número.
    """
    moderno = _listado(LATEST_PROTOCOL_VERSION).model_dump(by_alias=True)

    assert moderno["ttlMs"] > 0, (
        "el catálogo viaja como inmediatamente rancio, así que el cliente lo vuelve a pedir "
        "entero en cada arranque"
    )
    assert moderno["ttlMs"] == servidor.CACHE_DEL_CATALOGO.ttl_ms, (
        f"lo que viaja ({moderno['ttlMs']}) no es lo que declara la constante "
        f"({servidor.CACHE_DEL_CATALOGO.ttl_ms})"
    )
    assert moderno["cacheScope"] == servidor.CACHE_DEL_CATALOGO.scope, (
        f"el alcance que viaja ({moderno['cacheScope']}) no es el declarado "
        f"({servidor.CACHE_DEL_CATALOGO.scope})"
    )


def test_la_pista_de_frescura_no_estorba_en_el_carril_viejo():
    """Que es el que negocian los clientes por stdio, y donde ese campo no existe.

    El SDK lo criba por revisión, así que la pista no llega y el catálogo llega igual. Sin este
    guardia, una pista puesta para el carril moderno podría estar rompiendo el único que hoy
    hablan Claude Desktop, Claude Code, Cursor, VS Code y Codex.
    """
    viejo = _listado("legacy").model_dump(by_alias=True)

    assert viejo["ttlMs"] == 0, (
        f"la pista se coló en una revisión donde ese campo no existe: {viejo['ttlMs']}"
    )
    assert len(viejo["tools"]) == len(_listado(LATEST_PROTOCOL_VERSION).tools), (
        "el carril viejo dejó de anunciar las mismas herramientas que el moderno"
    )


def test_el_servidor_se_presenta_con_un_icono_que_no_sale_a_la_red():
    """El icono viaja ENTERO, no como una dirección que haya que ir a buscar.

    Una URL con host lo haría depender de que un tercero responda, y de paso le contaría a ese
    tercero quién abrió el cliente y cuándo. Las únicas peticiones que este proyecto hace son al
    Poder Judicial.

    Se lee de lo que el cliente RECIBE y por los dos carriles, que son dos caminos distintos del
    SDK: en el viejo llega en el saludo, y en el moderno estampado en el `_meta` de cada
    resultado.
    """

    async def saludar() -> list[Icon] | None:
        async with Client(servidor.mcp, mode="legacy") as cliente:
            return cliente.server_info.icons if cliente.server_info else None

    iconos = asyncio.run(saludar())
    assert iconos, "el servidor se presenta sin icono"
    fuente = iconos[0].src
    assert fuente.startswith("data:"), (
        f"el icono se pide a un host ajeno en vez de viajar en el saludo: {fuente[:60]}"
    )
    dibujo = base64.b64decode(fuente.split(",", 1)[1]).decode("utf-8")
    assert dibujo.startswith("<svg"), f"lo que viaja como icono no es un SVG: {dibujo[:60]}"

    estampado = _listado(LATEST_PROTOCOL_VERSION).model_dump(by_alias=True)["_meta"]
    assert estampado[SERVER_INFO_META_KEY]["icons"][0]["src"] == fuente, (
        "el icono que llega por el carril moderno no es el mismo que el del saludo"
    )


def _completar(
    valor: str, *, argumento: str = "competencia", plantilla: str | None = None
) -> Completion:
    """Lo que el servidor ofrece para un argumento de una plantilla de recurso."""

    async def pedir() -> Completion:
        async with Client(servidor.mcp) as cliente:
            resultado = await cliente.complete(
                ref=ResourceTemplateReference(uri=plantilla or servidor.PLANTILLA_DOCUMENTO),
                argument={"name": argumento, "value": valor},
            )
            return resultado.completion

    return asyncio.run(pedir())


def test_las_completions_ofrecen_las_competencias_que_el_cliente_acepta():
    """Ni una de más: una que el cliente rechaza se intenta, falla, y el fallo se le atribuye a
    la plataforma.

    La lista esperada sale de la tabla del cliente, que es la que de verdad acepta o rechaza, y
    no de la derivada del servidor: si las dos se separan, este guardia lo ve.
    """
    sin_documentos = sorted(set(MODULOS) - set(DOCUMENTOS))
    assert sin_documentos, (
        "todas las competencias publican documentos, así que la mitad de abajo de este test no "
        "puede fallar y no está cuidando nada"
    )

    todas = _completar("")

    assert todas.values == sorted(DOCUMENTOS), (
        f"las competencias ofrecidas no son las que el cliente acepta: {todas.values} contra "
        f"{sorted(DOCUMENTOS)}"
    )
    assert not set(todas.values) & set(sin_documentos), (
        f"se ofrece una competencia sin documentos ({sin_documentos}), y elegirla termina en un "
        f"error que parece de la plataforma: {todas.values}"
    )
    assert todas.total == len(todas.values), (
        f"el total dice {todas.total} y viajan {len(todas.values)} valores"
    )
    assert todas.has_more is False, "la lista viaja como incompleta y son todas"


def test_las_completions_no_contestan_por_argumentos_ajenos():
    """Un completador que ignora QUÉ se le pregunta ofrece competencias donde va otra cosa.

    Vale para el otro argumento de la misma plantilla y para otra plantilla entera. Lo primero
    contestaría con competencias donde el cliente espera una ruta; lo segundo, en cuanto exista
    otra plantilla o un prompt con un argumento que se llame igual.
    """
    empezada = _completar("co")
    assert empezada.values == ["cobranza"], (
        f"el valor a medias no acota lo que se ofrece: {empezada.values}"
    )
    assert empezada.total == len(empezada.values), (
        f"el total quedó atado a la lista entera y no a la que viaja: {empezada.total}"
    )

    assert _completar("", argumento="ruta").values == [], (
        "se ofrecen competencias para `ruta`, que no es una competencia"
    )
    assert _completar("", plantilla="pjud://otra{?competencia}").values == [], (
        "se ofrecen competencias para una plantilla que no es la del documento"
    )


# -- las plantillas que la persona invoca ---------------------------------------
#
# Un prompt no es una herramienta: no lo llama el modelo, lo invoca la persona desde su
# cliente, y lo que devuelve es texto que entra a la conversación como si lo hubiera escrito
# ella. Por eso se prueban acá y no en `test_client`: no tocan la red, y lo único que importa
# de ellos es qué cruza el protocolo.


def _anunciados() -> dict[str, Prompt]:
    """Las plantillas tal como `prompts/list` las anuncia, por nombre."""

    async def anunciar() -> dict[str, Prompt]:
        async with Client(servidor.mcp) as cliente:
            listado = await cliente.list_prompts()
            return {p.name: p for p in listado.prompts}

    return asyncio.run(anunciar())


#: Con qué se rinde cada plantilla, por etiqueta, y con VARIOS juegos por plantilla: el texto
#: cambia según lo que llegue, y un solo juego deja ramas enteras sin rendirse nunca. Es el modo
#: de falla de un parámetro opcional con valor por defecto: la suite queda verde porque nadie
#: pasa el argumento que enciende la rama, y dentro de esa rama cabe cualquier cosa.
#:
#: Los argumentos viajan como TEXTO por el protocolo, así que acá van como texto: pasarlos ya
#: convertidos mediría una ruta que ningún cliente usa.
ARGUMENTOS_DE_LA_PLANTILLA: dict[str, tuple[str, dict[str, str]]] = {
    "computar-plazo": (
        "computar-plazo",
        {"tipo": "C", "rol": "1156", "anio": "2026", "competencia": "civil"},
    ),
    "computar-plazo con los códigos": (
        "computar-plazo",
        {
            "tipo": "C",
            "rol": "1156",
            "anio": "2026",
            "competencia": "civil",
            "tribunal": "1131",
            "corte": "46",
        },
    ),
    "revisar-causa": (
        "revisar-causa",
        {"tipo": "C", "rol": "1156", "anio": "2026", "competencia": "civil"},
    ),
    "revisar-causa con los códigos": (
        "revisar-causa",
        {
            "tipo": "C",
            "rol": "1156",
            "anio": "2026",
            "competencia": "civil",
            "tribunal": "1131",
            "corte": "46",
        },
    ),
    # Sin `corte` a propósito: es la competencia que la exige, así que acá se rinde el aviso que
    # manda a resolverla antes de abrir la causa.
    "revisar-causa en apelaciones": (
        "revisar-causa",
        {"tipo": "Protección", "rol": "1504", "anio": "2019", "competencia": "apelaciones"},
    ),
    # La que no se acota por ninguno de los dos, y donde el rol va sin nada adelante.
    "revisar-causa en suprema": (
        "revisar-causa",
        {"tipo": "", "rol": "999999", "anio": "2020", "competencia": "suprema"},
    ),
    "verificar-cita": ("verificar-cita", {"rol": "1234", "anio": "2020", "buscador": "suprema"}),
    "verificar-cita con una frase": (
        "verificar-cita",
        {"rol": "1234", "anio": "2020", "literal": "en cuanto a la prescripción alegada"},
    ),
}

#: Qué herramienta tiene que nombrar cada plantilla. Escrito y no sacado de la plantilla: leer
#: de ahí el nombre que después se compara sería comparar el texto consigo mismo.
HERRAMIENTA_DE_LA_PLANTILLA = {
    "computar-plazo": "obtener_actuaciones_receptor",
    "revisar-causa": "obtener_detalle_causa",
    "verificar-cita": "buscar_jurisprudencia",
}

#: Las frases que afirman que algo no está. `no hay que` queda fuera a propósito: es una
#: instrucción y no una afirmación sobre el mundo, y contarla pondría en rojo un texto correcto.
AFIRMA_AUSENCIA = re.compile(r"\bno (?:existe[ns]?|exista[ns]?|haya)\b|\bno hay\b(?! que)")

#: Cómo se dice una ausencia sin afirmarla. Cerca de cada una de las de arriba tiene que ir una
#: de estas: sin la salvedad, la plantilla le enseña al modelo a informar como probado algo que
#: la consulta pública no puede probar, que es el error que este proyecto existe para evitar.
SALVEDADES = ("no prueba", "no significa", "no es que", "tampoco", "no se puede")


def _rendidas() -> dict[str, str]:
    """El texto de cada juego, tal como `prompts/get` lo entrega y con los saltos juntados.

    Se normalizan los espacios porque el texto va envuelto a mano y las listas se interpolan
    al medio: atar un guardia al punto exacto donde cae el salto lo pone en rojo por un
    reajuste de línea que no cambia nada de lo que el modelo lee.
    """

    async def rendir() -> dict[str, str]:
        async with Client(servidor.mcp) as cliente:
            rendidas = {}
            for etiqueta, (nombre, argumentos) in ARGUMENTOS_DE_LA_PLANTILLA.items():
                resultado = await cliente.get_prompt(nombre, argumentos)
                rendidas[etiqueta] = " ".join(
                    "\n".join(
                        m.content.text for m in resultado.messages if m.content.type == "text"
                    ).split()
                )
            return rendidas

    return asyncio.run(rendir())


def test_las_tres_plantillas_se_anuncian() -> None:
    """El servidor anunciaba catorce herramientas y cero plantillas."""
    anunciados = _anunciados()
    faltan = sorted(PLANTILLAS - set(anunciados))
    assert not faltan, f"`prompts/list` no anuncia {faltan}: anuncia {sorted(anunciados)}"


def test_los_juegos_rinden_todo_argumento_que_las_plantillas_aceptan() -> None:
    """Un argumento opcional que ningún juego pasa es una rama que la suite no puede ver.

    Es el modo de falla que este archivo no atrapaba: los guardias de abajo recorren lo que
    `_rendidas` devuelve, así que un argumento con valor por defecto que apaga su rama los
    deja a todos verdes sin que ninguno mire el texto que esa rama produce. Acá se exige que
    los juegos cubran lo declarado, y no al revés.
    """
    for nombre, plantilla in _anunciados().items():
        pasados = {
            clave
            for etiqueta, argumentos in ARGUMENTOS_DE_LA_PLANTILLA.values()
            if etiqueta == nombre
            for clave in argumentos
        }
        declarados = {a.name for a in plantilla.arguments or []}
        assert pasados == declarados, (
            f"{nombre} acepta {sorted(declarados)} y los juegos pasan {sorted(pasados)}: lo "
            "que no se pasa nunca se rinde, y lo que no se rinde no lo mira ningún guardia"
        )


def test_cada_plantilla_nombra_la_herramienta_que_le_toca() -> None:
    """Una plantilla que no nombra su herramienta deja al modelo eligiendo cuál usar.

    Y la nombrada tiene que existir: mandar a llamar algo que el servidor no expone produce un
    error que el modelo le atribuye a la plataforma en vez de a la plantilla.
    """

    async def anunciar() -> set[str]:
        async with Client(servidor.mcp) as cliente:
            return {h.name for h in (await cliente.list_tools()).tools}

    expuestas = asyncio.run(anunciar())
    rendidas = _rendidas()
    for etiqueta, (plantilla, _) in ARGUMENTOS_DE_LA_PLANTILLA.items():
        herramienta = HERRAMIENTA_DE_LA_PLANTILLA[plantilla]
        assert herramienta in expuestas, (
            f"{plantilla} manda a llamar {herramienta!r} y el servidor no la expone"
        )
        assert f"`{herramienta}`" in rendidas[etiqueta], (
            f"{etiqueta} no nombra {herramienta!r}, así que no dice qué hay que pedir"
        )


def test_ninguna_plantilla_afirma_una_ausencia() -> None:
    """Ninguna puede decir que algo no existe sin la salvedad de que eso no se prueba.

    La consulta pública no ve las causas reservadas, y el buscador de fallos entrega un
    subconjunto. Una plantilla que enseñe a informar "no existe" convierte una lectura parcial
    en una afirmación, que es lo mismo que la regla 4 evita una capa más abajo.

    Se exige además que cada juego diga ALGO del asunto: sin eso, uno que no hablara nunca de
    ausencias pasaría este guardia sin que mirara nada.
    """
    for etiqueta, texto in _rendidas().items():
        plano = texto.lower()
        hallazgos = list(AFIRMA_AUSENCIA.finditer(plano))
        assert hallazgos, (
            f"{etiqueta} no dice qué significa que algo no aparezca, así que este guardia no lo "
            "está mirando"
        )
        for m in hallazgos:
            ventana = plano[max(0, m.start() - 160) : m.end() + 160]
            assert any(s in ventana for s in SALVEDADES), (
                f"{etiqueta} afirma una ausencia sin salvedad: ...{ventana}..."
            )


def test_revisar_causa_mira_si_la_causa_existe_antes_que_los_nulos() -> None:
    """Con `causa_encontrada` en falso TODOS los campos vienen en nulo, y por otra razón.

    La plantilla enseña a leer un nulo como "esta competencia no publica ese panel". Si la
    búsqueda no dio con la causa, esa lectura convierte una causa que no se encontró en una
    causa revisada cuyos paneles la competencia no publica, y el resumen no deja rastro de que
    se buscó mal.

    Va con el campo nombrado y no con una frase: lo que hay que hacer es MIRARLO.
    """
    texto = _rendidas()["revisar-causa"]
    assert "causa_encontrada" in texto, (
        "la plantilla no manda a mirar `causa_encontrada`, así que sus nulos se leen como "
        "paneles ausentes aunque la causa no se haya encontrado"
    )
    antes = texto.index("causa_encontrada")
    despues = texto.index("NULO")
    assert antes < despues, (
        "manda a mirar `causa_encontrada` DESPUÉS de clasificar los nulos, que es cuando ya se "
        "atribuyeron a la competencia"
    )


def test_las_plantillas_nombran_lo_que_el_codigo_acepta() -> None:
    """Las competencias y los buscadores que nombran salen del código, no de la prosa.

    Escritos a mano envejecen en silencio, y de la peor forma: la plantilla ofrecería una
    competencia que el cliente rechaza, el modelo la intentaría, y el error terminaría
    atribuido a la plataforma. Es la misma razón por la que las descripciones de las
    herramientas derivan sus listas de la tabla en vez de nombrarlas.
    """
    rendidas = _rendidas()
    listas = {
        "computar-plazo": (", ".join(servidor._CON_RECEPTOR), set(MODULOS)),
        "revisar-causa": (", ".join(servidor._CON_DETALLE), set(MODULOS)),
        "verificar-cita": (", ".join(sorted(BUSCADORES)), set(BUSCADORES)),
    }
    for etiqueta, (plantilla, _) in ARGUMENTOS_DE_LA_PLANTILLA.items():
        lista, universo = listas[plantilla]
        texto = rendidas[etiqueta]
        donde = texto.find(lista)
        assert donde != -1, f"{etiqueta} no nombra {lista!r}, que es lo que el código acepta"
        # Y que ahí TERMINE. Sin esto el guardia mira una subcadena: una lista escrita a mano
        # con un nombre de más la contiene entera, así que quitar ese nombre del código no la
        # pondría en rojo. Es la mitad que hace falta para que romper la constante se note.
        sigue = re.match(r", (\w+)", texto[donde + len(lista) :])
        de_mas = sigue.group(1) if sigue else ""
        assert de_mas not in universo, (
            f"{etiqueta} nombra {de_mas!r} después de {lista!r}, que es lo que el código "
            "acepta: la lista está escrita a mano"
        )
    # `ocultas` con número es la otra lista derivada, y la que más caro sale escribir a mano:
    # cada buscador nuevo llega con la bandera en falso, así que una lista vieja cuenta de menos
    # justo donde nulo no es cero.
    con_numero = ", ".join(servidor._CON_OCULTAS)
    assert f"Sólo {con_numero} la trae con número" in rendidas["verificar-cita"], (
        f"verificar-cita no dice que sólo {con_numero} trae `ocultas` con número"
    )
