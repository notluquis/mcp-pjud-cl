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
from collections.abc import Callable
from pathlib import Path

import httpx
import jsonschema
import pytest
from mcp.client import Client
from mcp.types import CallToolResult, Tool

from mcp_pjud import server as servidor
from mcp_pjud.client import PjudClient
from mcp_pjud.parser import SIN_RESULTADOS, EstructuraInesperada, parse_resultados

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

HERRAMIENTA = "buscar_causa_por_rit"
ARGUMENTOS = {"tipo": "E", "rol": 468, "anio": 2026}


def _responder(cuerpo: str) -> Callable[[httpx.Request], httpx.Response]:
    """Doble del sitio: la portada de la que se deriva la sesión y un cuerpo para la búsqueda.

    Cualquier otra ruta revienta en vez de responder algo plausible: un doble que contesta a
    una petición que el test no previó mide otra cosa que la que dice medir.
    """

    def responder(peticion: httpx.Request) -> httpx.Response:
        url = str(peticion.url)
        if url.endswith("sesion-consultaunificada.php"):
            return httpx.Response(200, text="")
        if url.endswith("consultaUnificada.php"):
            return httpx.Response(200, text=PORTADA)
        if url.endswith("/civil/consultaRitCivil.php"):
            return httpx.Response(200, text=cuerpo)
        raise AssertionError(f"petición no prevista por el doble: {peticion.method} {url}")

    return responder


def _llamar(monkeypatch: pytest.MonkeyPatch, cuerpo: str) -> CallToolResult:
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
        cliente._http = httpx.Client(transport=httpx.MockTransport(_responder(cuerpo)))
        return cliente

    monkeypatch.setattr(servidor, "PjudClient", fabricar)

    async def ida_y_vuelta() -> CallToolResult:
        async with Client(servidor.mcp) as cliente:
            return await cliente.call_tool(HERRAMIENTA, ARGUMENTOS)

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
