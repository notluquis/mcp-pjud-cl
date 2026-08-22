"""La documentación no puede divergir del código.

El proyecto reparte los mismos datos en muchos archivos: las herramientas y sus parámetros
están en `server.py` y descritos en `docs/herramientas.md`; el intervalo mínimo se cita en diez
archivos; las cifras medidas del buscador de fallos aparecen en cinco. Nada de eso se
actualiza solo.

Y una documentación desactualizada es peor que ninguna, porque se lee con la misma confianza.
Acá el riesgo es concreto: si la referencia sigue diciendo que una herramienta acepta un
parámetro que ya no existe, quien la lea escribirá una llamada que falla, y si sigue diciendo
que devuelve todo cuando pasó a devolver un subconjunto, dará por inexistente lo que no vio.

Estos tests no generan documentación: la prosa es lo valioso de esas páginas y se escribe a
mano. Lo que hacen es comparar cada dato repetido contra su única fuente, para que la
divergencia salga en CI y no en el uso.
"""

import ast
import asyncio
import base64
import contextlib
import re
import subprocess
import tomllib
import urllib.parse
from pathlib import Path

import pytest
import yaml

from mcp_pjud.client import (
    ANEXOS,
    AUDIO_CAMPO,
    AUDIO_RUTA,
    CORTES_MEDIDAS,
    DOCUMENTOS,
    INTERVALO_MINIMO,
    MODULOS,
    SEGUNDOS_BUSQUEDA_MEDIDOS,
    SEGUNDOS_BUSQUEDA_PEOR_MEDIDO,
    SEGUNDOS_PAGINA_MEDIDOS,
)
from mcp_pjud.juris import (
    BUSCADORES,
    FECHA_MEDICION,
    FILAS_MAXIMAS,
    INDEXADAS_MEDIDAS,
    VISIBLES_MEDIDAS,
    miles,
)
from mcp_pjud.parser import _ENCABEZADOS_ANEXO, COMPETENCIAS, parse_historia
from mcp_pjud.server import mcp

from .conftest import CARACTERES_DE_UNA_SENTENCIA

#: Para derivar la fecha corta de la larga en vez de escribir las dos al lado.
_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

RAIZ = Path(__file__).parents[1]
HERRAMIENTAS = (RAIZ / "docs" / "herramientas.md").read_text(encoding="utf-8")

#: Todo lo que un lector puede tomar por cierto. Se recorre entero en vez de mirar una página,
#: porque el dato viejo puede quedar en cualquiera.
PROSA = sorted(
    p
    for p in [*RAIZ.glob("*.md"), *(RAIZ / "docs").glob("*.md"), *(RAIZ / ".github").glob("*.md")]
    if "_build" not in p.parts
)


def _texto(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _trozos_de_ruta(url: str) -> list[str]:
    """Los trozos de una URL que pueden ser un nombre de archivo.

    Sin el esquema ni el host: `https://www.pjud.cl/ayuda` partido a lo bruto entrega
    `www.pjud.cl`, y de ahí `cl` se lee como una extensión ajena. Sería un rojo sobre un
    enlace externo perfectamente legítimo, o sea un guardia que estorba en vez de proteger.
    """
    from urllib.parse import urlsplit

    partes = urlsplit(url)
    # El `.` de una ruta relativa (`./audio/...`) no es un nombre de archivo, y colarse como
    # uno lo hacía figurar como documento enlazado con extensión vacía.
    return [
        t
        for t in re.split(r"[?&=/#]", f"{partes.path}?{partes.query}")
        if "." in t and t.rsplit(".", 1)[1] and t.strip(".")
    ]


def _registro() -> str:
    return _texto(RAIZ / "CHANGELOG.md")


def _versiones_del_registro(contenido: str | None = None) -> list[str]:
    """Las versiones publicadas, de la más nueva a la más vieja por semver.

    Vive acá porque la expresión estaba escrita cuatro veces en este archivo, y un cambio de
    formato del encabezado obligaba a acertarle a las cuatro: basta olvidar una para que un
    guardia deje de morder en silencio. Y el orden se decide por número y no por posición en
    el archivo, para que un encabezado insertado donde no va no cambie qué es "la última".
    """
    versiones = re.findall(
        r"^## \[(\d+\.\d+\.\d+)\]", _registro() if contenido is None else contenido, re.M
    )
    return sorted(versiones, key=lambda v: tuple(int(n) for n in v.split(".")), reverse=True)


# -- la referencia contra el servidor -------------------------------------------


@pytest.fixture(scope="module")
def expuestas():
    return {h.name: h for h in asyncio.run(mcp.list_tools())}


@pytest.fixture(scope="module")
def secciones():
    """Cada `## \\`nombre\\`` de la referencia con su cuerpo."""
    nombres = re.findall(r"^## `([a-z0-9_]+)`", HERRAMIENTAS, re.M)
    cuerpos = re.split(r"^## `[a-z0-9_]+`", HERRAMIENTAS, flags=re.M)[1:]
    return dict(zip(nombres, cuerpos, strict=True))


def test_toda_herramienta_del_servidor_esta_documentada(expuestas, secciones):
    faltantes = sorted(set(expuestas) - set(secciones))
    assert not faltantes, f"El servidor expone herramientas sin documentar: {faltantes}"


def test_no_se_documentan_herramientas_que_no_existen(expuestas, secciones):
    """El error contrario, más difícil de notar leyendo: una herramienta que se quitó del
    servidor pero quedó descrita, o que nunca existió."""
    inventadas = sorted(set(secciones) - set(expuestas))
    assert not inventadas, f"La referencia describe herramientas inexistentes: {inventadas}"


def test_todo_parametro_aparece_en_la_seccion_de_su_herramienta(expuestas, secciones):
    """Se busca dentro de la sección y no en la página entera: un nombre como `anio` aparece
    en varias, y encontrarlo en cualquier lado no probaría nada."""
    faltantes = [
        f"{nombre}.{parametro}"
        for nombre, h in expuestas.items()
        for parametro in (h.input_schema or {}).get("properties", {})
        if f"`{parametro}`" not in secciones.get(nombre, "")
    ]
    assert not faltantes, f"Parámetros sin documentar en su sección: {faltantes}"


def test_los_campos_de_completitud_estan_documentados(expuestas):
    """`ocultas` es la razón por la que la búsqueda de jurisprudencia devuelve un objeto y no
    una lista. Si sale del modelo o de la página, la herramienta se lee como si entregara
    todo, que es justo el defecto que motivó el proyecto."""
    salida = (expuestas["buscar_jurisprudencia"].output_schema or {}).get("properties", {})
    for campo in (
        "visibles",
        "coincidencias",
        "ocultas",
        "no_entregadas",
        "condiciones_de_publicacion",
    ):
        assert campo in salida, f"el modelo dejó de declarar `{campo}`"
        assert f"`{campo}`" in HERRAMIENTAS, f"`{campo}` no está en la referencia"


def test_los_canales_mapeados_y_no_ejecutados_siguen_declarados():
    """La lista de lo mapeado sin ejecutar es lo único que impide dar el detalle por completo.

    Nombrar los canales no basta: las cifras que los acompañan también son afirmaciones, y las
    tres se pueden derivar. Un guardia que sólo buscara los identificadores dejaba pasar que
    18 rutas se volvieran cualquier otro número.
    """
    seccion = _texto(RAIZ / "docs" / "verificacion.md").split("### Mapeado pero nunca ejecutado")
    assert len(seccion) == 2, "la sección de lo mapeado sin ejecutar desapareció"
    lista = seccion[1].split("\n\n")[2]

    # `listadoAudioLaboral` salió de esta lista el 22-08-2026: se midió, y tiene sección propia.
    for canal in ("tiene_anexo", "expedienteApe", "IncompetenciaApe"):
        assert canal in lista, f"`{canal}` dejó de estar declarado como mapeado sin ejecutar"

    # El JavaScript del sitio es la única fuente de cuántas rutas de anexo hay, y `ANEXOS` la
    # única de cuántas se midieron. Las dos derivadas: escribir la resta a mano deja el número
    # viejo cuando se mida la siguiente, y ahí la lista diría que sigue sin ejecutarse algo que
    # el servidor ya ofrece.
    js = _texto(RAIZ / "tests" / "fixtures" / "consultaUnificada.html")
    rutas = set(re.findall(r"/(?:\w+)/modal/(\w*[Aa]nexo\w*\.php)", js))
    assert f"**{len(rutas) - len(ANEXOS)} de las {len(rutas)} rutas de anexo**" in lista, (
        f"el sitio nombra {len(rutas)} rutas de anexo, {len(ANEXOS)} están medidas y la lista "
        "dice otra cosa"
    )

    # Y el detalle de apelaciones dice cuántos paneles publica.
    ape = _texto(RAIZ / "tests" / "fixtures" / "detalle_apelaciones.html")
    paneles = set(re.findall(r'id="(\w*[Aa]pe)"', ape))
    leidos = {
        p.panel
        for a in ("historia", "litigantes", "notificaciones", "liquidaciones", "materias")
        if (p := getattr(COMPETENCIAS["apelaciones"], a, None)) is not None
    }
    assert f"De los **{len(paneles)}** paneles que apelaciones publica se leen " in lista
    assert f"se leen **{len(paneles & leidos)}**" in lista, (
        f"apelaciones publica {sorted(paneles)} y se leen {sorted(paneles & leidos)}"
    )


def test_la_seccion_de_anexos_nombra_la_ruta_y_los_campos_que_el_codigo_usa():
    """Lo que la página afirma sobre el canal medido sale del código, no de la memoria.

    Son cuatro datos que se pueden derivar: la ruta del panel, el campo con que se pide, la
    ruta de descarga de cada fila y su campo. Escribirlos a mano acá los deja envejecer justo
    donde alguien va a buscarlos para repetir la medición cuando la plataforma cambie.
    """
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    seccion = pagina.split("## El segundo canal de documentos")
    assert len(seccion) == 2, "la sección del canal de anexos desapareció"
    seccion = seccion[1].split("\n## ")[0]

    ruta, campo = ANEXOS["laboral"]
    assert f"`{ruta}`" in seccion, f"la sección no nombra {ruta!r}, que es la ruta que se pide"
    assert f"`{campo}`" in seccion, f"la sección no nombra {campo!r}, el campo con que se pide"

    # La de descarga sale de `DOCUMENTOS` y no de una lista escrita al lado: es la misma tabla
    # que `obtener_documento` consulta, así que si una deja de estar la otra se entera.
    descargas = [r for r in DOCUMENTOS["laboral"] if "anexo" in r.lower()]
    assert len(descargas) == 1, f"laboral declara {descargas} rutas de descarga de anexo"
    assert f"`{descargas[0]}`" in seccion, "la sección no dice con qué ruta se descarga el anexo"
    assert f"`{DOCUMENTOS['laboral'][descargas[0]]}`" in seccion, (
        "la sección no dice con qué campo se pide la descarga"
    )

    for encabezado in _ENCABEZADOS_ANEXO:
        assert f"`{encabezado}`" in seccion.lower(), (
            f"la sección no nombra la columna {encabezado!r}, y el mapeo es posicional"
        )


def test_la_seccion_de_audio_nombra_la_ruta_y_el_campo_que_el_cliente_usa():
    """La página es lo que alguien va a leer para repetir la medición, y su hallazgo central es
    que la ruta NO cuelga del prefijo de sesión.

    Sale del cliente y no de la memoria: si la ruta cambia, la página tiene que enterarse.
    """
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    seccion = pagina.split("### Los audios de audiencia existen")
    assert len(seccion) == 2, "la sección del canal de audio desapareció"
    seccion = seccion[1].split("\n### ")[0]

    assert f"`POST /{AUDIO_RUTA}`" in seccion, (
        f"la sección no nombra {AUDIO_RUTA!r}, que es la ruta que el cliente pide"
    )
    assert f"`{AUDIO_CAMPO}`" in seccion, (
        f"la sección no nombra {AUDIO_CAMPO!r}, el campo con que se pide"
    )
    assert "fuera** del prefijo" in seccion or "fuera del prefijo" in seccion, (
        "la sección dejó de decir que la ruta no cuelga del prefijo de sesión, que es lo que "
        "distingue esta ruta de todos los demás modales"
    )


def test_la_referencia_no_afirma_que_ocultas_en_cero_sea_lista_completa():
    """`ocultas` cubre lo reservado, no lo que no se pidió. La referencia llegó a decir que
    la lista era un subconjunto sólo si `ocultas` era mayor que cero, y con eso una búsqueda
    de 400 visibles con `filas` en 10 se leía como completa."""
    seccion = HERRAMIENTAS.split("## `buscar_jurisprudencia`")[1].split("\n## ")[0]
    assert "`no_entregadas`" in seccion, "la referencia no nombra el recorte por `filas`"
    assert "`ocultas` en cero no significa que la lista esté completa" in seccion, (
        "la referencia dejó de desmentir que `ocultas` en cero implique completitud"
    )


def test_cada_hook_declarado_existe_y_es_ejecutable():
    """Un script de hook sin su `settings.json` es código muerto que parece vivo.

    Las dos mitades se pueden versionar por separado y una sola no hace nada: el script sin la
    declaración no corre nunca, y la declaración sin el script falla en cada llamada.

    Y `settings.local.json` NO rescata a un script de ser huérfano, aunque sí se le exige que
    lo que declare exista. Está en el `.gitignore`, así que un cableado que vive sólo ahí no
    viaja: darlo por bueno es el mismo modo de falla que este guardia persigue, entrando por la
    puerta de al lado.
    """
    import json
    import os
    import shlex

    def declarados_en(ajustes: Path) -> list[str]:
        if not ajustes.exists():
            return []
        return [
            h["command"]
            for grupo in json.loads(_texto(ajustes)).get("hooks", {}).values()
            for entrada in grupo
            for h in entrada.get("hooks", [])
            if h.get("type") == "command"
        ]

    versionado = RAIZ / ".claude" / "settings.json"
    local = RAIZ / ".claude" / "settings.local.json"
    if not versionado.exists() and not local.exists():
        pytest.skip("este repositorio no declara hooks de proyecto")

    del_repo = declarados_en(versionado)
    assert del_repo or not versionado.exists(), "`settings.json` existe y no declara ningún comando"

    # Lo que declare cualquiera de los dos tiene que existir, poder ejecutarse, y llevar la
    # variable ENTRECOMILLADA: sin comillas, un checkout cuya ruta tenga espacios parte la
    # expansión y no corre ningún hook. Se resuelve la cadena tal cual está declarada en vez
    # de armar la ruta con `Path`, que es lo que hacía que el guardia no viera el problema.
    for comando in [*del_repo, *declarados_en(local)]:
        assert '"$CLAUDE_PROJECT_DIR"' in comando or "$CLAUDE_PROJECT_DIR" not in comando, (
            f"{comando} usa `$CLAUDE_PROJECT_DIR` sin comillas: en una ruta con espacios el "
            "shell parte la expansión y el hook no corre"
        )
        partes = shlex.split(comando.replace("$CLAUDE_PROJECT_DIR", str(RAIZ)))
        ruta = Path(partes[0])
        assert ruta.exists(), f"un settings declara {comando} y ese archivo no existe"
        assert os.access(ruta, os.X_OK), f"{comando} no tiene permiso de ejecución"

    # Y si un hook trae su propia prueba, se corre. La parte más frágil de un hook suele ser
    # un patrón de texto, y probarlo desde otro archivo con una copia del patrón sólo prueba
    # que la copia funciona: los casos tienen que correr contra la función del hook.
    for comando in del_repo:
        ruta = Path(shlex.split(comando.replace("$CLAUDE_PROJECT_DIR", str(RAIZ)))[0])
        if "--probar" not in _texto(ruta):
            continue
        # `stdin` cerrado y con tope. Lo primero es lo que impide el cuelgue real: un hook que
        # declare la bandera sin implementarla cae en su `cat` y con la entrada cerrada recibe
        # EOF y sale en milisegundos (medido: 33 ms). Desde una terminal, en cambio, `cat`
        # espera para siempre, y ese cuelgue es de la shell y no del hook.
        #
        # El tope es por otra cosa: acá corre dentro de la suite, y un subproceso colgado por
        # cualquier motivo (una llamada de red que no vuelve) deja CI trabado sin decir nada.
        try:
            r = subprocess.run(  # noqa: S603
                [str(ruta), "--probar"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"{ruta.name} --probar no terminó en 30 s")
        assert r.returncode == 0, f"{ruta.name} --probar falló:\n{r.stdout}\n{r.stderr}"

    # Pero sólo el versionado rescata de ser huérfano.
    escritos = {p.name for p in (RAIZ / ".claude" / "hooks").glob("*.sh")}
    declarados_nombre = {
        Path(shlex.split(c.replace("$CLAUDE_PROJECT_DIR", str(RAIZ)))[0]).name for c in del_repo
    }
    huerfanos = sorted(escritos - declarados_nombre)
    assert not huerfanos, (
        f"{huerfanos} viven en `.claude/hooks/` y `.claude/settings.json` no los declara, así "
        "que no viajan cableados: en otra copia del repositorio no corren"
    )


def test_todo_trabajo_que_corre_la_suite_clona_la_historia_completa():
    """Un guardia de la suite lee un commit anterior, así que con clon superficial se cae.

    Ya pasó dos veces con el mismo modo de falla. La primera se arregló sólo en `tests.yml`,
    y `publicar.yml` quedó igual: al etiquetar 0.8.0 la publicación entera falló ahí. En
    `mutacion.yml` el fallo habría sido mudo, porque el paso termina en `|| true`.

    Se mira por TRABAJO y no por archivo, y por lo que el trabajo hace y no por su nombre:
    `tests.yml` tiene tres, y a dos de ellos (zizmor y el barrido de endpoints) la historia
    no les hace falta. Si mañana aparece otro que corra la suite, entra solo.
    """
    import yaml

    sin_historia = []
    for wf in sorted((RAIZ / ".github" / "workflows").glob("*.yml")):
        for nombre, trabajo in (yaml.safe_load(_texto(wf)).get("jobs") or {}).items():
            pasos = trabajo.get("steps") or []
            corre = any(re.search(r"\b(pytest|mutmut run)\b", p.get("run") or "") for p in pasos)
            if not corre:
                continue
            checkouts = [p for p in pasos if "actions/checkout" in (p.get("uses") or "")]
            assert checkouts, f"{wf.name}:{nombre} corre la suite y no hace checkout"
            if any((p.get("with") or {}).get("fetch-depth") != 0 for p in checkouts):
                sin_historia.append(f"{wf.name}:{nombre}")

    assert not sin_historia, (
        f"estos trabajos corren la suite con un clon superficial: {sin_historia}. El guardia "
        "de anclajes de la hoja de ruta lee un commit anterior y ahí falla. Hace falta "
        "`fetch-depth: 0`."
    )


#: Los conteos que la prosa escribe con letras, para poder derivarlos igual.
_EN_PALABRAS = {1: "una", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis"}

#: Los radios de precisión que devolvió la única causa donde se midió la georreferencia. No
#: salen de ninguna constante, porque son una medición y no una decisión: viven acá, y el
#: guardia exige que las tres copias de la documentación digan los mismos cinco.
PRECISIONES_MEDIDAS = ("6,0", "10,04", "26,68", "56,22", "103,13")


def test_la_referencia_dice_cuantas_herramientas_hay_de_verdad(expuestas):
    """La descripción de la página se quedó en once cuando entró la doce.

    Es el `<meta name="description">` de la página publicada y la línea que la ecosistema y
    `llms.txt` muestran como resumen, o sea lo primero que lee alguien que llega. Nada la
    comparaba contra el servidor: el guardia de secciones exige que cada herramienta tenga la
    suya, y eso sigue pasando con un conteo viejo al lado.
    """
    pagina = _texto(RAIZ / "docs" / "herramientas.md")
    assert f"las {len(expuestas)} herramientas MCP" in pagina.split("---")[1], (
        f"el servidor expone {len(expuestas)} herramientas y la descripción de la referencia "
        "dice otra cosa"
    )
    # Y el conteo del cuerpo, que es otra copia y quedó vieja aparte: decía "Las cinco" con
    # doce expuestas. Arreglar la descripción y dejar ésta es el mismo error una línea abajo.
    assert f"Las {len(expuestas)} están anotadas en el protocolo" in pagina, (
        f"la referencia dice que están anotadas otras que las {len(expuestas)} expuestas"
    )


def test_las_rutas_de_georreferencia_son_las_que_el_sitio_declara():
    """`verificacion` afirma cuántas hay, y sale del JavaScript del sitio.

    Son una por competencia más una unificada. El cliente ofrece menos, porque descarta las
    que no tienen tabla de Historia medida, y ésa es justamente la distinción que el conteo
    del sitio deja ver: lo que la plataforma publica no es lo que este servidor puede pedir.
    """
    js = _texto(RAIZ / "tests" / "fixtures" / "consultaUnificada.html")
    rutas = set(re.findall(r"(geoReferencia\w*\.php)", js))
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    assert f"Hay {_EN_PALABRAS[len(rutas)]} rutas, una por competencia más una unificada" in (
        pagina
    ), f"el sitio declara {len(rutas)} rutas de georreferencia: {sorted(rutas)}"


def test_la_pagina_de_uso_nombra_campos_que_existen():
    """Es la página que le enseña al abogado a leer la salida, y no la miraba nadie.

    Vaciarla entera no ponía ni un test en rojo. Nombra los campos de una actuación en su lista
    de definiciones, empezando por `fecha_diligencia`, que es el que corre los plazos: si uno se
    renombra, esa página queda enseñando a buscar algo que la respuesta ya no trae.
    """
    from mcp_pjud.parser import Actuacion

    pagina = _texto(RAIZ / "docs" / "uso.md")
    # Los términos de la lista de definiciones: una línea que es sólo un identificador entre
    # comillas invertidas, seguida de otra que empieza con dos puntos.
    lineas = pagina.splitlines()
    nombrados = {
        m.group(1)
        for i, linea in enumerate(lineas[:-1])
        if (m := re.fullmatch(r"`(\w+)`", linea.strip())) and lineas[i + 1].startswith(":")
    }
    assert nombrados, "la página de uso dejó de tener su lista de campos"

    faltan = sorted(n for n in nombrados if n not in Actuacion.model_fields)
    assert not faltan, (
        f"la página de uso enseña a leer {faltan}, y una actuación no trae esos campos"
    )
    assert "fecha_diligencia" in nombrados, (
        "la página de uso dejó de explicar `fecha_diligencia`, que es la que corre los plazos"
    )


def test_la_licencia_dice_lo_mismo_en_los_cuatro_lugares_donde_está():
    """La licencia está escrita en cuatro archivos y nada los comparaba.

    Vaciar `docs/licencia.md` entera no ponía ni un test en rojo, así que la página que explica
    qué se puede hacer con este software podía decir una licencia y el paquete distribuir otra.
    Es la afirmación con más consecuencias del repositorio después de las de plazos.
    """
    identificador = tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["license"]
    nombre = identificador.removeprefix("LicenseRef-").replace("-", " ").replace(" 1 0 0", " 1.0.0")

    assert identificador in _texto(RAIZ / "CITATION.cff"), (
        f"CITATION.cff declara una licencia distinta de {identificador}"
    )
    assert _texto(RAIZ / "LICENSE.md").startswith(
        f"# {nombre.replace('Strict', 'Strict License')}"
    ), f"LICENSE.md no es el texto de {nombre}"
    # Se barre la prosa entera en vez de enumerar dónde está declarada. Enumerar es lo que
    # falló dos veces: primero el guardia aceptaba cualquier mención (la insignia del README
    # rescataba una declaración cambiada), después miraba dos páginas y se le escapaban las de
    # `uso`, `index` e `instalacion`. Cualquier nombre de licencia que no sea el declarado es
    # una contradicción, esté donde esté.
    # Se buscan las DECLARACIONES sobre este software, no cualquier nombre de licencia. El
    # barrido por nombre fue una sobrecorrección: la investigación de documentos compara las
    # licencias de PyMuPDF, pypdf y pypdfium2 en prosa, y eso no es una declaración sobre
    # esto. Prohibir nombres ponía el guardia en rojo sobre una página correcta.
    #
    # Una declaración se reconoce por su frase, y son pocas y estables: "el proyecto usa X",
    # "se entrega bajo X", "[X] permite", "La licencia ([X])". Si alguna cambia de licencia,
    # la frase sigue estando y el nombre que trae adentro es el que se compara.
    DECLARACIONES = (
        r"[Ee]l proyecto usa \[([^\]]+)\]",
        r"[Ss]e entrega bajo \[([^\]]+)\]",
        r"[Ss]e distribuye bajo \[([^\]]+)\]",
        r"^\[([^\]]+)\]\([^)]*\)[.,]? [Pp]ermite",
        r"^\*\*([^*]+)\*\* permite",
        r"La licencia \(\[([^\]]+)\]",
    )
    ajenas = {}
    for pagina in PROSA:
        texto = _texto(pagina)
        halladas = {
            m.group(1) for patron in DECLARACIONES for m in re.finditer(patron, texto, re.M)
        }
        otras = sorted(h for h in halladas if h != nombre)
        if otras:
            ajenas[pagina.name] = otras
    assert not ajenas, (
        f"estas páginas declaran una licencia que no es la que el paquete distribuye: "
        f"{ajenas}. La declarada es {nombre}."
    )

    # Y que al menos una página la declare, para que borrarla no pase por silencio.
    assert any(nombre in _texto(p) for p in PROSA), (
        f"ninguna página nombra {nombre}, que es bajo lo que se distribuye"
    )


def test_las_precisiones_medidas_dicen_lo_mismo_en_las_cuatro_copias():
    """Cinco cifras escritas a mano en cuatro lugares, y ninguna las comparaba.

    `herramientas` las repite dos veces (tabla de campos y aviso), `verificacion` una, y la
    cuarta es la que de verdad lee el modelo: el esquema de salida que el servidor anuncia.
    Mirar sólo las de Markdown dejaba que la documentación y el protocolo dijeran cosas
    distintas, que es peor que dos páginas en desacuerdo.

    Se comparan los números completos y no por pertenencia: con `in`, cambiar `10,04` por
    `110,04` dejaba el guardia verde, porque la cadena vieja sigue adentro de la nueva. Es el
    mismo error que buscar `.doc` dentro de `_window.document.close()`.
    """
    from mcp_pjud.parser import Georreferencia

    ref = _texto(RAIZ / "docs" / "herramientas.md")
    copias = {
        "herramientas.md (tabla)": ref.split("`precision_metros`")[1][:200],
        "herramientas.md (aviso)": ref.split("Medidas en una sola causa:")[1][:200],
        "verificacion.md": _texto(RAIZ / "docs" / "verificacion.md").split(
            "Medidas en una sola causa:"
        )[1][:200],
        "el esquema que anuncia el servidor": (
            Georreferencia.model_fields["precision_metros"].description or ""
        ),
    }
    # Y el rango que el contrato de la herramienta publica, que es una quinta copia derivada:
    # actualizar las cuatro y dejarla conserva los extremos viejos en lo que lee el modelo.
    from mcp_pjud.server import obtener_georreferencia

    numeros = sorted(float(p.replace(",", ".")) for p in PRECISIONES_MEDIDAS)
    minimo, maximo = int(numeros[0]), int(numeros[-1])
    contrato = " ".join((obtener_georreferencia.__doc__ or "").split())
    assert f"varía entre {minimo} y {maximo} metros" in contrato, (
        f"`obtener_georreferencia` publica un rango que no es {minimo} a {maximo} metros, que "
        "es lo medido"
    )
    assert f"con {maximo} la coordenada dice el sector" in contrato, (
        f"el contrato razona sobre un radio que no es el máximo medido ({maximo})"
    )

    esperadas = sorted(PRECISIONES_MEDIDAS)
    mal = {
        donde: sorted(set(re.findall(r"\d+,\d+", texto)))
        for donde, texto in copias.items()
        if sorted(set(re.findall(r"\d+,\d+", texto))) != esperadas
    }
    assert not mal, (
        f"estas copias no citan exactamente las precisiones medidas: {mal}. Son "
        f"{' · '.join(PRECISIONES_MEDIDAS)} metros, y las cuatro tienen que decir lo mismo."
    )


def test_la_aritmetica_de_diez_sentencias_sale_de_la_sentencia_medida():
    """Las dos páginas razonan lo mismo con distinta precisión, y el producto es derivado.

    `roadmap` cita los 25.473 caracteres exactos y `herramientas` los redondea, pero las dos
    concluyen con el mismo "devolver diez serían 250.000". Si se vuelve a medir la sentencia,
    ese producto queda viejo en los dos lados sin que nadie lo mire.
    """
    redondeado = round(CARACTERES_DE_UNA_SENTENCIA, -3)
    # El piso que las dos páginas citan, redondeado hacia abajo al múltiplo de diez mil.
    piso = (CARACTERES_DE_UNA_SENTENCIA * 10) // 10_000 * 10_000

    hoja = _texto(RAIZ / "docs" / "roadmap.md")
    assert f"{miles(CARACTERES_DE_UNA_SENTENCIA)} caracteres" in hoja, (
        f"la hoja de ruta dejó de citar los {miles(CARACTERES_DE_UNA_SENTENCIA)} caracteres "
        "de la sentencia medida"
    )
    # Con la cifra exacta al lado, el producto NO puede escribirse como si fuera exacto: son
    # 254.730 y no 250.000. La hoja lo dice como piso, que es lo que sí es cierto.
    assert f"serían más de {miles(piso)}" in hoja, (
        f"la hoja de ruta cita la sentencia exacta y presenta el producto como {miles(piso)} "
        f"redondos. Diez son {miles(CARACTERES_DE_UNA_SENTENCIA * 10)}."
    )

    # La referencia redondea la entrada, así que su producto sí es exacto.
    ref = _texto(RAIZ / "docs" / "herramientas.md")
    assert f"unos {miles(redondeado)} caracteres" in ref, (
        f"la referencia redondea la sentencia medida a otra cosa que {miles(redondeado)}"
    )
    assert f"serían {miles(redondeado * 10)}" in ref, (
        f"la referencia parte de {miles(redondeado)} y no concluye {miles(redondeado * 10)}"
    )

    # Y las copias que anuncia el protocolo, que son las que el modelo lee de verdad: la
    # descripción de `obtener_texto_sentencia` y la del propio modelo de resultado. Escriben
    # la magnitud en palabras, así que se comparan contra la misma constante deletreada.
    from mcp_pjud.juris import TextoSentencia
    from mcp_pjud.server import obtener_texto_sentencia

    en_palabras = {25_000: "veinticinco mil", 30_000: "treinta mil", 20_000: "veinte mil"}
    esperado = en_palabras.get(redondeado)
    assert esperado, (
        f"no está escrita en palabras la magnitud {miles(redondeado)}, y las descripciones "
        "del protocolo la citan así"
    )
    for donde, texto in (
        ("obtener_texto_sentencia", obtener_texto_sentencia.__doc__ or ""),
        ("el modelo TextoSentencia", TextoSentencia.__doc__ or ""),
    ):
        assert f"unos {esperado} caracteres" in " ".join(texto.split()), (
            f"{donde} anuncia una magnitud distinta de {esperado} caracteres, así que el "
            "protocolo y la documentación dicen cosas distintas"
        )

    # Y el producto, que el modelo también escribe en palabras: actualizar sólo la magnitud
    # dejaba a `TextoSentencia` concluyendo diez veces la cifra vieja.
    productos = {250_000: "doscientos cincuenta mil", 300_000: "trescientos mil"}
    producto = productos.get(redondeado * 10)
    assert producto, (
        f"no está escrito en palabras el producto {miles(redondeado * 10)}, y la descripción "
        "del modelo lo cita así"
    )
    assert producto in " ".join((TextoSentencia.__doc__ or "").split()), (
        f"`TextoSentencia` dice que diez sentencias son otra cosa que {producto}"
    )


def test_lo_medido_del_canal_de_audio_no_se_pierde():
    """Lo caro de esa medición no son las cifras: es la trampa que destapó.

    Pedir la ruta construida por analogía con los otros modales devuelve 200 con la tabla
    VACÍA, o sea el error se lee como "esta causa no tiene audios". Si esa advertencia
    desaparece de la página, la próxima persona que mida repite el mismo falso negativo y
    esta vez puede darlo por bueno.
    """
    pagina = " ".join(_texto(RAIZ / "docs" / "verificacion.md").split())
    for afirmacion in (
        "POST /audio/listadoAudio.php",
        "fuera** del prefijo",
        "La ruta equivocada devuelve 200 con la tabla vacía",
        "`Fecha` | viene **vacía**",
    ):
        assert afirmacion in pagina, (
            f"`verificacion.md` dejó de decir {afirmacion!r} sobre el canal de audio"
        )


def test_las_anotaciones_de_solo_lectura_siguen_puestas(expuestas):
    """La referencia afirma que todas están anotadas como solo lectura. Es verificable, así
    que se verifica en vez de confiar en que siga siendo cierto."""
    for nombre, h in expuestas.items():
        assert h.annotations is not None, f"{nombre} perdió sus anotaciones"
        assert h.annotations.read_only_hint is True, f"{nombre} ya no se anuncia solo lectura"
        assert h.annotations.destructive_hint is False, f"{nombre} se anuncia destructiva"


# -- las cifras repetidas contra su única fuente ---------------------------------


def test_ninguna_pagina_cita_un_intervalo_distinto_del_real():
    """El intervalo se menciona en diez archivos. Es la cláusula CUARTA implementada en
    código: una página que prometa otro número describe un software que no existe."""
    correcto = f"{INTERVALO_MINIMO:.0f} segundos"
    malos = [
        f"{p.relative_to(RAIZ)}: {m}"
        for p in PROSA
        for m in re.findall(r"cada (\d+(?:[.,]\d+)?) segundos", _texto(p))
        if m != f"{INTERVALO_MINIMO:.0f}"
    ]
    assert not malos, f"Se cita un intervalo distinto de '{correcto}': {malos}"


#: Páginas que citan la medición del buscador. Es una lista explícita y no un barrido,
#: porque el barrido tiene un agujero: una página con las DOS cifras viejas no contiene
#: ninguna de las nuevas, así que "buscar quién las menciona" la deja fuera justo cuando está
#: mal. Si una página nueva cita la medición, se agrega acá.
#: Páginas que citan la medición del buscador de fallos y se escriben a mano.
#:
#: El registro de cambios NO está: es un histórico, y una entrada vieja que cita la medición de
#: su versión no está desactualizada, está fechada. Exigirle la cifra vigente obligaría a
#: reescribir el pasado cada vez que se vuelve a medir. Mismo criterio que con las cifras de
#: latencia.
PAGINAS_CON_LA_MEDICION = (
    "docs/herramientas.md",
    "docs/verificacion.md",
)


#: Las tres páginas entre las que se repartió la hoja de ruta al partirla. Los guardias que
#: antes miraban `roadmap.md` miran las dos, y eso es a propósito: anclarlos sólo a la página
#: nueva cubriría MENOS que antes, porque nada impediría reponer la afirmación vieja en la que
#: se quedó con el nombre. La regla del corte es que el dato medido vive en una sola, no que el
#: guardia mire una sola.
ESTADO_Y_PLAN = ("docs/verificacion.md", "docs/roadmap.md", "docs/ecosistema.md")


def _estado_y_plan() -> str:
    """El texto de las dos páginas juntas, para los guardias que las cruzan."""
    return "\n".join(_texto(RAIZ / p) for p in ESTADO_Y_PLAN)


def test_las_cifras_medidas_del_buscador_son_las_mismas_en_todas_partes():
    """La directiva del servidor las interpola desde el código; estas páginas se escriben a
    mano y son las que pueden quedar viejas."""
    visibles, universo = miles(VISIBLES_MEDIDAS), miles(INDEXADAS_MEDIDAS)

    viejas = [
        ruta
        for ruta in PAGINAS_CON_LA_MEDICION
        if not (visibles in _texto(RAIZ / ruta) and universo in _texto(RAIZ / ruta))
    ]
    assert not viejas, (
        f"Estas páginas no citan la medición vigente ({visibles} visibles de {universo} "
        f"coincidencias declaradas): {viejas}"
    )


def test_ninguna_otra_pagina_cita_la_medicion_a_medias():
    """Y si alguna otra la menciona, que la mencione entera: `300.005` sin su universo no
    dice nada, y quien lo lea entenderá que ése es el total."""
    visibles, universo = miles(VISIBLES_MEDIDAS), miles(INDEXADAS_MEDIDAS)
    a_medias = [
        str(p.relative_to(RAIZ))
        for p in PROSA
        if (visibles in _texto(p)) != (universo in _texto(p))
    ]
    assert not a_medias, f"Páginas que citan una cifra de la medición sin la otra: {a_medias}"


def test_la_fecha_de_la_medicion_acompana_a_las_cifras():
    """Una cifra medida sin fecha no se puede evaluar: quien la lea no sabe si sigue vigente.

    Sin alternativas, y ésa es la corrección: antes aceptaba también `"16-08-2026"` y
    `"16 de agosto"` escritos a mano, así que volver a medir movía `FECHA_MEDICION` y las
    páginas se quedaban con la fecha vieja en verde. Un `or` que nombra el valor de hoy no es
    una tolerancia de formato: es el guardia rescatando justo la copia que vino a atrapar.

    Lo que sí hace falta es normalizar los espacios, porque la fecha se parte entre líneas.
    """
    # Se barre la prosa Y el código: `juris.py` repite la fecha y las dos cifras en el
    # docstring de su módulo, y ahí es donde vive la constante, así que era la copia con más
    # posibilidades de quedar vieja sin que nadie la mirara.
    # `juris.py` va SIEMPRE, no sólo si ya trae la cifra vigente: al volver a medir, su
    # docstring puede conservar juntas las dos cifras y la fecha viejas, no contener el total
    # nuevo, caer en el `continue` y dejar la suite verde. Es la copia que vive junto a la
    # constante, o sea la que más fácil se queda atrás.
    obligatorias = {RAIZ / "src" / "mcp_pjud" / "juris.py"}
    for p in [*PROSA, *(RAIZ / "src" / "mcp_pjud").glob("*.py")]:
        # En un `.py` se mira SÓLO el docstring del módulo, no el archivo entero. Con el
        # archivo completo, la asignación de `FECHA_MEDICION` que está unas líneas más abajo
        # rescataba a su propia copia vieja del docstring: la constante contiene el valor que
        # el guardia venía a verificar contra ella.
        crudo = _texto(p)
        if p.suffix == ".py":
            m = ast.get_docstring(ast.parse(crudo))
            crudo = m or ""
        t = " ".join(crudo.split())
        if p in obligatorias:
            # Obligatoria significa que TIENE que traer las dos cifras vigentes, no sólo que
            # se la mire. Con el bypass anterior, una medición nueva que actualizara la fecha
            # y las visibles y dejara el total viejo pasaba: el `continue` se saltaba, pero
            # nada exigía el total, así que las aserciones de abajo daban verde.
            assert miles(INDEXADAS_MEDIDAS) in t, (
                f"{p.relative_to(RAIZ)} tiene que citar las {miles(INDEXADAS_MEDIDAS)} "
                "coincidencias declaradas, y quedó con otra cifra"
            )
        elif miles(INDEXADAS_MEDIDAS) not in t:
            continue
        # El código la escribe en formato corto, así que la corta se DERIVA de la larga y no
        # se escribe al lado: un `or` con la fecha de hoy es lo que dejaba pasar la copia vieja.
        m = re.fullmatch(r"(\d{1,2}) de (\w+) de (\d{4})", FECHA_MEDICION)
        assert m, "`FECHA_MEDICION` dejó de tener la forma que este guardia sabe derivar"
        corta = f"{int(m[1]):02d}-{_MESES.index(m[2].lower()) + 1:02d}-{m[3]}"
        assert FECHA_MEDICION in t or corta in t, (
            f"{p.relative_to(RAIZ)} cita la medición con una fecha que no es {FECHA_MEDICION!r} "
            f"ni {corta!r}"
        )
        assert miles(VISIBLES_MEDIDAS) in t, (
            f"{p.relative_to(RAIZ)} cita las coincidencias declaradas sin las visibles, que es "
            "la mitad que importa"
        )


def test_los_topes_declarados_coinciden_con_el_codigo():
    """El tope de filas se documenta como rango. Si cambia en el código y no en la página,
    quien lea pedirá un valor que la herramienta rechaza antes de consultar."""
    assert f"de 1 a {FILAS_MAXIMAS}" in HERRAMIENTAS, (
        f"la referencia no declara el tope real de filas ({FILAS_MAXIMAS})"
    )


#: Los bytes del único documento que este proyecto pidió: folio 9 de C-1156-2026, una página
#: escaneada. No sale de ninguna constante porque es una medición y no una decisión, así que
#: vive acá y el guardia exige que `verificacion.md` la siga declarando.
BYTES_DEL_DOCUMENTO_MEDIDO = 975_006


def test_los_documentos_de_trabajo_no_se_publican():
    """`orphan: true` no excluye nada: sólo calla el aviso de no colgar de un `toctree`.

    La página se genera igual y aparece en el buscador y en `llms.txt`, así que un documento
    que se declara de trabajo terminaba publicado en Read the Docs. Lo que sí lo excluye es
    `exclude_patterns`, y la convención de nombre es el `_` adelante.
    """
    import ast
    import fnmatch

    # Se lee la lista y se prueba cada documento contra ella, en vez de buscar el literal
    # `"_*.md"`: lo que importa es que el archivo quede excluido, no con qué patrón.
    m = re.search(r"^exclude_patterns = (\[[^\]]*\])", _texto(RAIZ / "docs" / "conf.py"), re.M)
    assert m, "`docs/conf.py` dejó de declarar `exclude_patterns`"
    patrones = ast.literal_eval(m.group(1))

    publicados = [
        f.name
        for f in sorted((RAIZ / "docs").glob("_*.md"))
        if not any(fnmatch.fnmatch(f.name, p) for p in patrones)
    ]
    assert not publicados, (
        f"estos documentos de trabajo se van a publicar: {publicados}. Ninguno de los patrones "
        f"de `exclude_patterns` ({patrones}) los excluye, y todos dicen 'no publicado'."
    )

    # No se exige `orphan: true`: con el archivo excluido Sphinx nunca lo descubre, así que no
    # puede emitir `toc.not_included`. Pedirlo pondría CI en rojo por algo que ya no falla.


def test_la_investigacion_afirma_solo_pdf_y_las_fixtures_lo_sostienen():
    """De esa afirmación cuelga `_MAGIA_PDF`, que rechaza en duro lo que no empiece en `%PDF-`.

    Si una fixture llega a traer evidencia de otro formato y nadie lo mira, el documento de
    trabajo sigue diciendo "sólo PDF" y la implementación que salga de él rechaza un documento
    real informando que la referencia caducó. Se deriva de las fixtures, que es donde la página
    dice haberlo buscado.
    """
    pagina = _texto(RAIZ / "docs" / "_investigacion-documentos.md")
    fixtures = "\n".join(_texto(f) for f in sorted((RAIZ / "tests" / "fixtures").glob("*.html")))

    # Sin enumerar formatos, igual que abajo: la lista cerrada dejaba entrar un `.pptx`, un
    # `.odt` o un `.txt` en cualquier fixture que no fuera de detalle, y ahí la afirmación de
    # que las demás páginas enlazan exclusivamente PDF ya sería falsa.
    #
    # Se leen los `src` y `href`, que es lo que significa "la página enlaza un archivo", y del
    # HTML crudo porque el sitio arma marcado dentro de su JavaScript. `Content-Disposition`
    # no se busca: es una cabecera HTTP y las fixtures guardan cuerpos, o sea era un guardia
    # que no podía fallar.
    # Y se separa lo que la página MUESTRA de lo que ENLAZA. La afirmación es que todos los
    # documentos enlazados son PDF: un `<img src="icono.png">` es un recurso de presentación y
    # no la contradice, pero un `<a href="resolucion.jpg">` sí, y aceptar las imágenes en
    # bloque dejaba pasar justo ése. Un documento se enlaza con `href`.
    NO_SON_ARCHIVOS = {"php", "js", "css", "html", "htm"}

    def enlazados_por(atributo: str) -> set[str]:
        return {
            trozo
            for valor in re.findall(rf"""{atributo}\s*=\s*['"]([^'"]+)['"]""", fixtures)
            for trozo in _trozos_de_ruta(valor)
            if trozo.rsplit(".", 1)[1].lower() not in NO_SON_ARCHIVOS
        }

    descargables = sorted(e for e in enlazados_por("href") if not e.lower().endswith(".pdf"))
    assert not descargables, (
        f"las fixtures enlazan {descargables} y la investigación afirma que todo documento "
        "enlazado es PDF. De esa afirmación cuelga `_MAGIA_PDF`."
    )

    # La excepción medida, que el arreglo del tokenizador de rutas dejó sin nadie que la
    # mirara: el canal de audio emite mp3. La evidencia no está en un `href` ni en un `src`
    # (el enlace apunta a un `.php`), sino en el `type` del `<source>` y en el nombre del
    # archivo dentro de una celda, o sea justo donde el barrido de arriba no llega.
    #
    # Va en las dos direcciones a propósito. Si aparece audio y la página no lo nombra, la
    # afirmación de "sólo PDF" quedó falsa; si la página lo nombra y no hay audio en ninguna
    # fixture, está declarando una excepción que nadie midió.
    hay_audio = bool(re.search(r"""type\s*=\s*['"]audio/""", fixtures) or ".mp3" in fixtures)
    lo_declara = "audio" in pagina.lower() and ".mp3" in pagina
    assert hay_audio == lo_declara, (
        f"las fixtures traen audio: {hay_audio}, y la investigación lo declara como excepción: "
        f"{lo_declara}. Las dos cosas van juntas o la página afirma de más en una dirección o "
        "en la otra."
    )

    # Lo que se muestra sí puede ser imagen, pero no cualquier cosa: un `.odt` en un `src`
    # tampoco tiene explicación.
    mostrados = sorted(
        e
        for e in enlazados_por("src")
        if not e.lower().endswith((".png", ".gif", ".jpg", ".jpeg", ".svg", ".ico", ".pdf"))
    )
    assert not mostrados, (
        f"las fixtures muestran {mostrados}, que no es un recurso de presentación ni un PDF"
    )

    # La afirmación es sobre lo que EL DETALLE nombra, así que se miran sólo las fixtures que
    # son un detalle: las que traen algún panel de historia. Reunir los `*.png` de todas hacía
    # que una fixture nueva con un logotipo pusiera el guardia en rojo sin contradecir nada.
    paneles = {c.historia.panel for c in COMPETENCIAS.values() if c.historia is not None}
    detalles = "\n".join(
        t
        for f in sorted((RAIZ / "tests" / "fixtures").glob("*.html"))
        if any(p in (t := _texto(f)) for p in paneles)
    )
    assert detalles, "no quedó ninguna fixture de detalle"
    # TODO archivo nombrado, no sólo los `.png`: la frase dice que el detalle no nombra ningún
    # documento, así que un `.pdf` colándose ahí la desmiente igual que otro icono. El prefijo
    # `ADIR_` cambia con la sesión, así que se comparan los nombres de archivo.
    # No se busca en el texto suelto sino en lo que apunta a un archivo, que es lo que
    # significa "la página nombra un archivo". Y se lee del HTML crudo y no del árbol, porque
    # el sitio arma marcado dentro de su JavaScript: `pagLoad.gif` viaja en un `src` que sólo
    # existe como cadena, y un enlace a un documento podría venir igual.
    #
    # Enumerar extensiones dejaba entrar un `.pptx` o un `.odt` sin que nada lo notara, y
    # buscar cualquier punto se llevaba puesta la prosa del sitio (`Gar.de`, `AB.DTE`,
    # `Pend.Art.52`). Exigir que venga de un `src` o un `href` distingue las dos cosas sin
    # tener que adivinar qué formatos existen.
    NO_SON_ARCHIVOS = {"php", "js", "css", "html", "htm"}
    nombrados = sorted(
        {
            trozo
            for valor in re.findall(r"""(?:src|href)\s*=\s*['"]([^'"]+)['"]""", detalles)
            for trozo in _trozos_de_ruta(valor)
            if trozo.rsplit(".", 1)[1].lower() not in NO_SON_ARCHIVOS
        }
    )
    assert nombrados == ["icono_PDF.png", "pagLoad.gif"], (
        f"el detalle nombra {nombrados}, y la página afirma que no nombra ningún documento: "
        "sólo el icono y el indicador de carga del propio sitio. El documento se pide por una "
        "referencia opaca, no por su nombre."
    )
    for archivo in nombrados:
        assert archivo in pagina, f"la página dejó de nombrar {archivo}"

    marcas = _texto(RAIZ / "tests" / "fixtures" / "c1156_principal.html").count("fa-file-pdf-o")
    assert f"**{marcas}** veces con el icono `fa-file-pdf-o`" in pagina, (
        f"el cuaderno principal de C-1156-2026 marca {marcas} enlaces con `fa-file-pdf-o` y la "
        "página dice otra cosa"
    )


def test_la_investigacion_de_documentos_deriva_sus_cifras_del_codigo():
    """Esa página razona sobre el presupuesto de una respuesta y sobre cuántas veces lo pasa un
    documento medido. Las dos cifras son derivadas, no copiadas, y por eso quedan viejas sin que
    nadie las toque: basta con mover `CARACTERES_DE_UNA_RESPUESTA` para que la página describa
    una aritmética que ya no es la del código.

    Se ancla también la medición de origen. Una página que deriva de una cifra que
    `verificacion.md` dejó de declarar está razonando sobre algo que el proyecto ya no afirma.
    """
    from mcp_pjud.client import CARACTERES_DE_UNA_RESPUESTA

    pagina = _texto(RAIZ / "docs" / "_investigacion-documentos.md")
    # Cuatro caracteres por cada tres bytes, redondeando hacia arriba: es la aritmética de
    # base64 que la propia página explica.
    en_base64 = -(-BYTES_DEL_DOCUMENTO_MEDIDO // 3) * 4
    veces = en_base64 // CARACTERES_DE_UNA_RESPUESTA

    # Cada MENCIÓN del tamaño, no que aparezca en algún lado: la página lo cita tres veces (el
    # párrafo de la cifra que decide, la fila de la tabla, y la sección de alcance), y buscarlo
    # en la página entera dejaba que una quedara vieja mientras otra la rescataba. Una misma
    # investigación publicando dos tamaños distintos es peor que una cifra vieja sola.
    # Acotado a las menciones que hablan DEL FOLIO: la página cita también los 81.566 bytes de
    # la hoja sintética rasterizada, que es otra medición y tiene que poder ser distinta.
    plana = " ".join(pagina.split())
    del_folio = {
        m.group(1)
        for m in re.finditer(r"(\d{1,3}(?:\.\d{3})+) bytes", plana)
        if re.search(r"(folio|El documento)", plana[max(0, m.start() - 90) : m.end() + 90])
    }
    assert del_folio == {miles(BYTES_DEL_DOCUMENTO_MEDIDO)}, (
        f"la investigación atribuye al folio medido {sorted(del_folio)} bytes y son "
        f"{miles(BYTES_DEL_DOCUMENTO_MEDIDO)}: todas las menciones tienen que decir lo mismo"
    )
    assert pagina.count(miles(BYTES_DEL_DOCUMENTO_MEDIDO)) >= 3, (
        "la página citaba el tamaño medido tres veces y ahora menos: si se quitó una mención "
        "a propósito, hay que bajar este número con ella"
    )

    faltan = [
        cifra
        for cifra in (
            miles(CARACTERES_DE_UNA_RESPUESTA),
            miles(en_base64),
            f"**{veces}**",
        )
        if cifra not in pagina
    ]
    assert not faltan, (
        f"la investigación de documentos no cita estas cifras vigentes: {faltan}. "
        f"{miles(BYTES_DEL_DOCUMENTO_MEDIDO)} bytes son {miles(en_base64)} caracteres en "
        f"base64, o sea {veces} veces los {miles(CARACTERES_DE_UNA_RESPUESTA)} de una respuesta."
    )

    # No sólo el tamaño: la recomendación cuelga igual de que el folio sea UNA página y NO
    # traiga capa de texto. Con esas dos corregidas y el tamaño intacto, la página seguiría
    # tratándolo como el peor caso de una hoja escaneada, que es lo que hace fuerte al
    # argumento. `verificacion` las declara en dos lugares y los dos tienen que decir lo mismo.
    verificacion = " ".join(_texto(RAIZ / "docs" / "verificacion.md").split())
    for afirmacion in (
        f"{miles(BYTES_DEL_DOCUMENTO_MEDIDO)} bytes, 1 página, sin capa de texto",
        f"{miles(BYTES_DEL_DOCUMENTO_MEDIDO)} bytes, un escaneo de una página",
    ):
        assert afirmacion in verificacion, (
            f"verificacion.md dejó de declarar que el folio medido es {afirmacion!r}, y la "
            "investigación deriva de que sea una hoja escaneada y no sólo de su tamaño"
        )
    # En la sección de alcance, no en cualquier parte de la página: "una página" aparece en
    # varios párrafos y rescataba la afirmación aunque el alcance dijera otra cosa.
    alcance = " ".join(pagina.split("## Lo que falta medir")[1].split("Falta, en este")[0].split())
    for afirmacion in ("tiene una página", "no trae capa de texto"):
        assert afirmacion in alcance, (
            f"el alcance de la investigación dejó de decir que el folio medido {afirmacion!r}"
        )

    # Y la relación entre los dos topes, que es la que obliga a que pedir texto reemplace el
    # archivo: el máximo embebido ocupa el presupuesto ENTERO, así que cualquier otra cosa lo
    # pasa. Si alguien afloja `LIMITE_EMBEBIDO`, la afirmación deja de ser cierta y hay que
    # reescribir la propuesta, no sólo la cifra.
    from mcp_pjud.client import LIMITE_EMBEBIDO

    assert -(-LIMITE_EMBEBIDO // 3) * 4 == CARACTERES_DE_UNA_RESPUESTA, (
        "el máximo embebido ya no ocupa el presupuesto entero, así que la propuesta no puede "
        "seguir justificando con aritmética que pedir texto reemplace el archivo"
    )
    assert "el mismo parámetro de rango del" in pagina, (
        "la propuesta dejó de decir cómo se continúa un índice truncado, y sin eso el corte "
        "no tiene salida: repetir la llamada regenera el mismo prefijo"
    )
    assert "reemplaza el archivo embebido por un `ResourceLink`" in pagina, (
        "la propuesta dejó de decir que pedir texto reemplaza el archivo, y sin eso los dos "
        "topes se cumplen por separado y suman uno que no se cumple"
    )

    # La misma aritmética sobre la hoja rasterizada. Los bytes salen de un experimento
    # sintético que no se reproduce acá, pero lo que se hace CON ellos es aritmética contra el
    # presupuesto, o sea la mitad que sí queda vieja si alguien mueve la constante o edita la
    # cifra sin recalcular las otras dos.
    m = re.search(r"\*\*([\d.]+) bytes\*\*, o sea \*\*([\d.]+) caracteres\*\*", pagina)
    assert m, "la página dejó de decir cuánto pesa la hoja rasterizada y cuánto ocupa en base64"
    bytes_raster = int(m.group(1).replace(".", ""))
    en_base64_raster = -(-bytes_raster // 3) * 4
    assert m.group(2).replace(".", "") == str(en_base64_raster), (
        f"{m.group(1)} bytes son {miles(en_base64_raster)} caracteres en base64, no {m.group(2)}"
    )
    veces_raster = en_base64_raster // CARACTERES_DE_UNA_RESPUESTA
    assert f"**más de {veces_raster} veces**" in pagina, (
        f"la hoja rasterizada pasa {veces_raster} veces el presupuesto de una respuesta y la "
        "página dice otra cosa"
    )


# -- lo que la documentación promete que está verificado -------------------------


def test_la_referencia_nombra_exactamente_las_competencias_verificadas():
    """`MODULOS` es la lista de lo verificado, y la referencia tiene que decir esa lista.

    Se compara contra el código en vez de contra un literal, porque un literal obliga a
    acordarse de dos lugares y de eso se olvida cualquiera. Anunciar una competencia que el
    cliente rechaza haría que alguien planifique con una función que no existe; callar una
    que sí funciona es más barato pero igual de falso.
    """
    seccion = next(
        (c for n, c in _secciones_de_herramientas().items() if n == "buscar_causa_por_rit"), ""
    )
    for verificada in MODULOS:
        assert f"`{verificada}`" in seccion, (
            f"La competencia {verificada!r} está verificada y la referencia no la nombra"
        )
    for otra in set(COMPETENCIAS) - set(MODULOS):
        assert f"`{otra}`" not in seccion, (
            f"La referencia nombra {otra!r} como disponible y el cliente la rechaza"
        )


def test_el_esquema_de_las_herramientas_anuncia_solo_lo_verificado(expuestas):
    """La página no es lo único que el modelo lee: el esquema del protocolo también.

    Anunciarle ahí una competencia que el cliente rechaza hace que la intente, reciba un
    error y se lo atribuya a la plataforma. La primera versión de este guardia cubría la
    documentación y dejaba el esquema fuera, que es el que el modelo lee primero.
    """
    # Dos herramientas quedan fuera y tienen su propio guardia, porque ofrecen menos que las
    # buscables y eso es correcto: `obtener_actuaciones_receptor` sólo las que publican
    # actuaciones en la Historia, y `obtener_historia_causa` sólo aquellas cuyo panel está
    # medido. Exigirles la lista completa las haría anunciar opciones que siempre fallan.
    sin_todas_las_competencias = {
        "obtener_actuaciones_receptor",
        # Ofrece las que tienen al menos un panel del detalle medido. `penal` no lo tiene, y
        # anunciarla haría que el modelo intente una llamada que siempre se rechaza.
        "obtener_detalle_causa",
        # Ofrece sólo las que se acotan POR tribunal. Medido: suprema no tiene tribunales
        # debajo y apelaciones devuelve juzgados de primera instancia que no sirven para
        # buscar ahí, así que ofrecerlas invita a usar esa lista como si fuera `tribunal`.
        "listar_tribunales",
        # Ofrece las que emiten formularios de descarga. `penal` no emite ninguno, así que no
        # hay ruta que ofrecerle: la llamada se rechaza siempre. Guardia propio abajo.
        "obtener_documento",
        # Ofrece las que publican la columna de georreferencia en su Historia. Suprema no la
        # publica, así que para ella nunca va a haber una referencia que pedir.
        "obtener_georreferencia",
        # Ofrece aquellas cuya ruta de anexos está MEDIDA, y es la única de esta lista donde
        # el recorte no sale de lo que la plataforma publica: las cinco publican la columna
        # `Anexo`. Ofrecer las otras cuatro sería anunciar como disponible algo que nadie
        # ejecutó contra el sitio, que es la clase de negativo sin medir que este proyecto
        # rechaza a propósito.
        "obtener_anexos_escrito",
    }
    descripciones = [
        p.get("description", "")
        for nombre_h, h in expuestas.items()
        if nombre_h not in sin_todas_las_competencias
        for nombre, p in (h.input_schema or {}).get("properties", {}).items()
        if nombre == "competencia"
    ]
    assert descripciones, "ninguna herramienta declara el parámetro `competencia`"
    for d in descripciones:
        for otra in set(COMPETENCIAS) - set(MODULOS):
            assert otra not in d, f"el esquema le ofrece {otra!r} al modelo y el cliente lo rechaza"
        for verificada in MODULOS:
            assert verificada in d, f"el esquema no le ofrece {verificada!r}, que sí funciona"


def test_ninguna_herramienta_exige_un_campo_que_su_competencia_no_usa(expuestas):
    """El esquema es el contrato: si declara `tribunal` obligatorio, el modelo NO puede llamar
    la herramienta sin inventarlo.

    Pasó exactamente eso: al verificar suprema y apelaciones se actualizó la validación del
    cliente y no el esquema, y `buscar_causa_por_fecha` quedó exigiendo un tribunal que esas
    dos competencias no usan. La herramienta se anunciaba para seis competencias y sólo se
    podía llamar para cuatro, sin que ningún test se enterara: los guardias miraban la
    documentación y la lista de competencias, no cuáles parámetros eran obligatorios.

    Que alguna competencia no lo exija basta para que no pueda ser obligatorio en el esquema:
    quién lo exige se dice en la descripción, no en la firma.
    """
    sin_acotar = {n for n in MODULOS if COMPETENCIAS[n].acota_por != "tribunal"}
    assert sin_acotar, "si todas exigieran tribunal, este guardia habría que retirarlo"

    # `listar_tribunales` sí puede exigir `corte`, y tiene que hacerlo: ahí no acota una
    # búsqueda de causas, dice DE QUÉ corte se quieren los tribunales. Con un valor por defecto
    # una consulta destinada a otra jurisdicción devolvía en silencio los de Concepción, que es
    # una lista plausible y equivocada.
    puede_exigir_corte = {"listar_tribunales"}

    culpables = {}
    for nombre_h, h in expuestas.items():
        if nombre_h in puede_exigir_corte:
            continue
        obligatorios = set((h.input_schema or {}).get("required", []))
        for campo in ("tribunal", "corte"):
            if campo in obligatorios:
                culpables.setdefault(nombre_h, set()).add(campo)
    assert not culpables, (
        f"Herramientas que declaran obligatorio un campo que no todas las competencias usan: "
        f"{culpables}. Con {sorted(sin_acotar)} expuestas, el modelo no puede llamarlas."
    )


def test_el_esquema_dice_que_competencia_exige_que_acotacion(expuestas):
    """Y no puede decirlo a mano: se deriva de `parser.COMPETENCIAS`.

    Sin esto, quitar `tribunal` de la firma dejaría al modelo sin saber cuándo hace falta, y
    la llamada fallaría en el cliente con un error que el modelo atribuye a la plataforma.
    """
    from mcp_pjud.server import ACOTACION, DIRECTIVA

    for nombre in MODULOS:
        assert nombre in ACOTACION, f"la regla de acotación no nombra a {nombre!r}"
    assert ACOTACION in DIRECTIVA, (
        "la regla tiene que viajar en la directiva del servidor: es lo que el modelo lee "
        "antes de llamar cualquier herramienta"
    )

    # `listar_tribunales` recibe `corte` con otro sentido: no acota una búsqueda de causas,
    # dice de qué corte se quieren los tribunales. Exigirle la frase de la acotación le pondría
    # al modelo una explicación que no aplica al parámetro que está leyendo.
    no_acotan = {"listar_tribunales"}

    for nombre_h, h in expuestas.items():
        if nombre_h in no_acotan:
            continue
        propiedades = (h.input_schema or {}).get("properties", {})
        for campo, exigen in (
            ("tribunal", [n for n in MODULOS if COMPETENCIAS[n].acota_por == "tribunal"]),
            ("corte", [n for n in MODULOS if COMPETENCIAS[n].acota_por == "corte"]),
        ):
            if campo not in propiedades:
                continue
            descripcion = propiedades[campo].get("description", "")
            for competencia in exigen:
                assert competencia in descripcion, (
                    f"{nombre_h}: la descripción de {campo!r} no nombra a {competencia!r}, "
                    f"que es una de las que lo exigen"
                )


def _secciones_de_herramientas() -> dict[str, str]:
    nombres = re.findall(r"^## `([a-z0-9_]+)`", HERRAMIENTAS, re.M)
    cuerpos = re.split(r"^## `[a-z0-9_]+`", HERRAMIENTAS, flags=re.M)[1:]
    return dict(zip(nombres, cuerpos, strict=True))


def test_la_documentacion_no_anuncia_buscadores_que_el_codigo_rechaza():
    for verificado in BUSCADORES:
        assert verificado in HERRAMIENTAS.lower(), (
            f"El buscador {verificado!r} está verificado y la referencia no lo nombra"
        )


def test_el_ejecutable_que_documentan_las_guias_es_el_que_declara_el_paquete():
    """Las guías de instalación traen un comando para copiar y pegar. Si el punto de entrada
    se renombra, ese comando queda roto y el error que produce no dice por qué."""
    with (RAIZ / "pyproject.toml").open("rb") as f:
        scripts = tomllib.load(f)["project"]["scripts"]
    (ejecutable,) = scripts
    # Con `in` a secas, renombrarlo a `mcp-pjud-otro` pasaría el test: la subcadena sigue
    # estando. El sufijo negativo es lo que vuelve al guardia capaz de fallar.
    exacto = re.compile(rf"\b{re.escape(ejecutable)}(?![-\w])")
    for pagina in (RAIZ / "README.md", RAIZ / "docs" / "instalacion.md"):
        assert exacto.search(_texto(pagina)), (
            f"{pagina.name} no menciona '{ejecutable}', que es el ejecutable que instala"
        )


# -- datos personales en la documentación ----------------------------------------


#: RUT de personas jurídicas que sí pueden aparecer: la Ley 21.719 protege datos de personas
#: naturales, y una empresa no lo es. Se usan a propósito en los ejemplos, porque un ejemplo
#: que corre de verdad vale más que uno inventado.
RUT_DE_EMPRESAS = {
    "97004000-5",  # Banco de Chile, que ya aparece como litigante en las fixtures
}

#: Un RUT se escribe con puntos casi siempre, y ésa es justamente la forma que aparecería en
#: la documentación. La primera versión de este guardia sólo reconocía la forma sin puntos, o
#: sea no habría detectado nada de lo que venía a impedir.
_RUT_EN_PROSA = re.compile(r"\b(\d{1,3}(?:\.\d{3}){1,2}|\d{7,8})-([\dkK])\b")


def _versionados() -> list[Path]:
    """Todo lo que el repositorio publica, según git.

    Se le pregunta a git en vez de recorrer el disco: así no se revisan artefactos de
    construcción ni el entorno virtual, y sobre todo no se pasa por alto un archivo nuevo
    sólo porque su extensión no estaba en una lista escrita a mano.
    """
    salida = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout
    return [RAIZ / n for n in salida.split("\0") if n]


def test_el_repositorio_no_publica_rut_de_personas_naturales():
    """`tests/test_fixtures.py` sólo revisa las fixtures. Todo lo demás es igual de público,
    y un RUT ahí es un identificador vivo: quien lo copie saca las causas de esa persona, que
    es el uso que `ACCEPTABLE_USE.md` rechaza.

    Ser figura pública no lo cambia. La excepción de la Ley 21.719 alcanza a los datos del
    ejercicio de funciones públicas, no a la cédula de identidad.

    La primera versión de este guardia sólo recorría las páginas de documentación, y por ese
    hueco entró un RUT real a un archivo de test, escrito mientras se redactaba el guardia
    mismo. Ahora mira todo lo que git publica.
    """
    #: Los ficticios son dígitos repetidos, igual que en las fixtures.
    ficticio = re.compile(r"^(\d)\1{6,7}$")

    encontrados = []
    for p in _versionados():
        try:
            texto = _texto(p)
        except UnicodeDecodeError:
            continue  # binarios: no llevan RUT en texto plano
        for cuerpo, dv in _RUT_EN_PROSA.findall(texto):
            plano = cuerpo.replace(".", "")
            if ficticio.match(plano) or f"{plano}-{dv}" in RUT_DE_EMPRESAS:
                continue
            encontrados.append(f"{p.relative_to(RAIZ)}: {cuerpo}-{dv}")
    assert not encontrados, (
        f"RUT que no son ni ficticios ni de empresa: {encontrados}. "
        "Para personas naturales se usa un RUT sintético; para empresas, uno real "
        "declarado en RUT_DE_EMPRESAS."
    )


@pytest.mark.parametrize(
    "escrito",
    # Cuerpos de dígitos repetidos, que es la convención de ficticio del proyecto. La primera
    # versión de este test usaba un RUT con dígito verificador válido tomado del ejemplo
    # público de un tercero: era el dato de una persona natural, quedaba versionado, y este
    # mismo guardia no lo veía porque sólo recorre la documentación.
    ["11111111-1", "11.111.111-1", "2.222.222-K"],
)
def test_el_guardia_de_rut_reconoce_las_dos_formas_de_escribirlo(escrito):
    """Un RUT casi siempre se escribe con puntos, y ésa es la forma que aparecería en la
    documentación. La primera versión del guardia sólo miraba la forma sin puntos: pasaba
    exactamente lo que venía a impedir."""
    cuerpo, dv = _RUT_EN_PROSA.findall(escrito)[0]
    assert cuerpo.replace(".", "") + "-" + dv == escrito.replace(".", "")


# -- citas legales ----------------------------------------------------------------


#: Fila de la tabla de normas: número de ley, enlace a la Biblioteca del Congreso Nacional,
#: y el resto de la fila. Se exige la forma completa y no la sola mención, porque la primera
#: versión de este guardia daba por conocida cualquier aparición del número antes de cierto
#: encabezado: un número suelto ahí bastaba para colar una cita sin fuente.
_FILA_DE_NORMA = re.compile(
    r"^\|\s*\[Ley\s+(\d{1,2}\.\d{3})\]\((https://www\.bcn\.cl/[^)]+)\)\s*\|.*\|.*\|\s*$",
    re.M,
)


def _tabla_de_normas() -> dict[str, str]:
    texto = _texto(RAIZ / "docs" / "cumplimiento.md")
    seccion = texto.split("## Normas que este proyecto cita")[1].split("\n## ")[0]
    return dict(_FILA_DE_NORMA.findall(seccion))


def test_la_tabla_de_normas_trae_enlace_y_fecha():
    """Lo que el guardia promete tiene que ser lo que comprueba.

    Su primera versión decía exigir enlace y fecha y no miraba ninguno de los dos: quitarlos
    dejaba la suite verde. Acá se exige la fila completa, con el enlace a la Biblioteca del
    Congreso Nacional, y que la sección declare cuándo se revisó.
    """
    tabla = _tabla_de_normas()
    assert tabla, "La tabla de normas de cumplimiento.md no tiene ninguna fila con enlace"

    seccion = (
        _texto(RAIZ / "docs" / "cumplimiento.md")
        .split("## Normas que este proyecto cita")[1]
        .split("\n## ")[0]
    )
    assert re.search(r"[Vv]erificado el \d{1,2} de \w+ de \d{4}", seccion), (
        "La tabla de normas no dice cuándo se revisó, que es lo único que permite a quien "
        "lea juzgar si sigue vigente"
    )


def test_toda_ley_citada_esta_en_la_tabla_de_normas():
    """La suite no consulta la red por diseño, así que una cita legal no se puede verificar
    en CI. Lo que sí se puede exigir es que exista una sola entrada con su enlace y su fecha,
    y que nadie cite una ley que no pasó por ahí.

    Sin esto, un número de ley equivocado se propaga por once archivos sin que nada lo note, y
    una cita jurídica errada en un proyecto que decide plazos es del mismo orden de error que
    un dato mal parseado.
    """
    ley = re.compile(r"Ley\s+(?:N°\s*)?(\d{1,2}\.\d{3})")
    conocidas = set(_tabla_de_normas())
    assert conocidas, "La tabla de normas de cumplimiento.md quedó vacía"

    huerfanas = sorted(
        {
            f"{p.relative_to(RAIZ)}: Ley {n}"
            for p in PROSA
            for n in ley.findall(_texto(p))
            if n not in conocidas
        }
    )
    assert not huerfanas, (
        f"Leyes citadas que no están en la tabla de docs/cumplimiento.md: {huerfanas}. "
        "Se agrega ahí, con enlace a la Biblioteca del Congreso Nacional y fecha de revisión."
    )


def test_ninguna_pagina_declara_un_numero_de_leyes_distinto_del_real():
    """Decir "las seis leyes que este proyecto cita" junto a una tabla de cinco es una
    contradicción que un lector encuentra y un test de números de ley no ve. Se evita
    exigiendo que nadie escriba la cuenta a mano: si hay que decirla, se dice el número.
    """
    escritos = {
        "una": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
    }
    real = len(_tabla_de_normas())
    alternativas = "|".join(escritos)
    patron = re.compile(rf"\b(?:las\s+)?({alternativas}|\d+)\s+leyes\b", re.I)

    malos = [
        f"{p.relative_to(RAIZ)}: '{m}' pero la tabla tiene {real}"
        for p in PROSA
        for m in patron.findall(_texto(p))
        if escritos.get(m.lower(), int(m) if m.isdigit() else -1) != real
    ]
    assert not malos, f"Cuentas de leyes que no coinciden con la tabla: {malos}"


#: Cómo se escribe el intervalo en prosa. Se incluye la forma con palabras porque la primera
#: versión de este guardia sólo reconocía el número, y por ese hueco quedaron dos afirmaciones
#: falsas en el roadmap: una prometía "una petición cada cinco segundos" sin la ráfaga y otra
#: calculaba cinco minutos con el límite plano anterior.
_EN_PALABRAS = {
    1: "un",
    2: "dos",
    3: "tres",
    4: "cuatro",
    5: "cinco",
    6: "seis",
    7: "siete",
    8: "ocho",
    9: "nueve",
    10: "diez",
}


def _menciona_el_intervalo(texto: str) -> bool:
    n = int(INTERVALO_MINIMO)
    formas = [rf"cada {n} segundos"]
    if n in _EN_PALABRAS:
        formas.append(rf"cada {_EN_PALABRAS[n]} segundos")
    return any(re.search(f, texto, re.I) for f in formas)


def test_toda_pagina_que_da_el_intervalo_menciona_la_rafaga():
    """El control tiene dos números y describir sólo uno lo cuenta mal.

    Una página que diga "una cada 5 segundos" y calle la ráfaga describe un límite plano que
    no existe: quien la lea calculará mal cuánto tarda una consulta, y quien audite el
    proyecto creerá que el control es más estricto de lo que es.

    Se reconocen las dos formas de escribirlo, con número y con palabra. La primera versión
    miraba sólo la numérica y dejó pasar dos afirmaciones falsas.
    """
    incompletas = [
        str(p.relative_to(RAIZ))
        for p in PROSA
        if _menciona_el_intervalo(_texto(p)) and not re.search(r"ráfaga", _texto(p), re.I)
    ]
    assert not incompletas, (
        f"Páginas que dan el intervalo sostenido y callan la ráfaga: {incompletas}"
    )


# -- la garantía de que CI no consulta al Poder Judicial ---------------------------


def _workflows() -> list[Path]:
    return sorted((RAIZ / ".github" / "workflows").glob("*.yml"))


def test_todo_workflow_que_corre_la_suite_bloquea_el_trafico_saliente():
    """La promesa es que CI nunca consulta al Poder Judicial. Con `audit` eso es un registro
    que hay que ir a mirar; con `block` es una imposibilidad.

    Se comprueba en todos los workflows que corren la suite y no sólo en uno, que es
    exactamente el hueco que tenía: `tests.yml` bloqueaba y los de mutación y publicación
    seguían en `audit`, así que una prueba que abriera un cliente real quedaba detenida en el
    primero y salía por los otros.
    """
    incumplen = []
    for w in _workflows():
        texto = _texto(w)
        if not re.search(r"\b(pytest|mutmut)\b", texto):
            continue
        if "egress-policy: block" not in texto:
            incumplen.append(str(w.relative_to(RAIZ)))

    assert not incumplen, (
        f"Workflows que corren la suite sin bloquear el tráfico saliente: {incumplen}"
    )


def test_ningun_workflow_permite_salir_al_poder_judicial():
    """El complemento del anterior: bloquear no sirve si el destino está en la lista.

    Se lee el valor de `allowed-endpoints` y no el archivo entero, porque los comentarios que
    explican esta misma garantía nombran el dominio. La primera versión los contaba y fallaba
    sobre un repositorio correcto, que es la otra forma de tener un guardia inútil.
    """
    con_pjud = []
    for w in _workflows():
        for job in (yaml.safe_load(_texto(w)) or {}).get("jobs", {}).values():
            for paso in job.get("steps") or []:
                if "pjud.cl" in str((paso.get("with") or {}).get("allowed-endpoints", "")):
                    con_pjud.append(str(w.relative_to(RAIZ)))
    assert not con_pjud, (
        f"Workflows que declaran un destino del Poder Judicial como permitido: {con_pjud}"
    )


def test_las_cifras_de_latencia_medidas_son_las_mismas_en_todas_partes():
    """Justifican `ESPERA_MAXIMA` y se citan en tres archivos.

    Mismo criterio que las cifras del buscador: si una queda vieja, la prosa describe una
    medición que ya no es la que sostiene la constante, y quien la lea calculará mal cuánto
    tolerar antes de dar una consulta por perdida.
    """

    def coma(x: float) -> str:
        return f"{x:g}".replace(".", ",")

    busqueda, pagina = coma(SEGUNDOS_BUSQUEDA_MEDIDOS), coma(SEGUNDOS_PAGINA_MEDIDOS)
    citan = [p for p in PROSA if busqueda in _texto(p) or pagina in _texto(p)]
    assert citan, f"ninguna página cita la latencia medida ({busqueda} s / {pagina} s)"

    a_medias = [
        str(p.relative_to(RAIZ))
        for p in citan
        if not (busqueda in _texto(p) and pagina in _texto(p))
    ]
    assert not a_medias, (
        f"Páginas que citan una de las dos latencias sin la otra: {a_medias}. "
        f"Las vigentes son {busqueda} s la búsqueda y {pagina} s la página del mismo host."
    )

    # La cifra típica sola es la que hizo daño: se tomó por techo y el timeout quedó en 90 s,
    # con lo que tres consultas que respondían en 81, 102 y 39 segundos se dieron por
    # imposibles. Donde se cite la típica tiene que estar el peor caso al lado, porque es el
    # que justifica cuánto esperar antes de dar una consulta por perdida.
    peor = coma(SEGUNDOS_BUSQUEDA_PEOR_MEDIDO)

    # El changelog queda fuera a propósito: registra lo que era cierto en cada versión, así que
    # una entrada vieja que cita los 47,8 s no está desactualizada, está fechada. Actualizarla
    # para que pase este guardia sería falsear el registro.
    #
    # Su sección SIN PUBLICAR es otra cosa y sí se mira: todavía no fechó nada, así que una
    # cifra a medias entrando ahí es una cifra a medias que se va a publicar. Excluir el
    # archivo entero la dejaba pasar.
    # Y publicar vaciaba ese tramo: la operación consiste en insertar `## [x.y.z]` justo
    # debajo, así que la sección sin publicar quedaba vacía y la excepción volvía a cubrir el
    # archivo entero, justo cuando esas viñetas pasan a ser lo publicado. Se mira el tramo sin
    # publicar MÁS el de la versión más nueva, que es lo que este pull request está escribiendo.
    def _tramos_vivos(contenido: str) -> str:
        tramos = re.split(r"^## (?=\[)", contenido, flags=re.M)[1:]
        return "".join(tramos[:2])

    def fechada(p) -> bool:
        if p.name != "CHANGELOG.md":
            return False
        return peor in _texto(p) or busqueda not in _tramos_vivos(_texto(p))

    sin_el_peor = [
        str(p.relative_to(RAIZ)) for p in citan if peor not in _texto(p) and not fechada(p)
    ]
    # El diagrama de la detención total cita el peor caso para justificar por qué un timeout
    # NO detiene el proceso. Es un dato repetido más, y si el techo se vuelve a medir hay que
    # redibujarlo: sin esto, el diagrama seguiría diciendo un número que ya no es.
    assert peor in _texto(RAIZ / "docs" / "cumplimiento.md"), (
        f"el diagrama de la detención total ya no cita el peor caso medido ({peor} s), que es "
        "lo que justifica que un timeout no detenga el proceso"
    )

    assert not sin_el_peor, (
        f"Páginas que citan la latencia típica sin el peor caso medido: {sin_el_peor}. "
        f"Sola, la de {busqueda} s invita a repetir el error de tomar una muestra por techo; "
        f"el peor medido es {peor} s."
    )


# -- lo que el cliente sabe hacer contra lo que el servidor expone -----------------


#: Métodos públicos del cliente que a propósito NO son herramientas MCP, con la razón.
NO_SON_HERRAMIENTAS = {
    # `detalle` devuelve HTML crudo: quien lo necesite usa `obtener_actuaciones_receptor`,
    # que lo interpreta. Exponerlo entregaría al modelo una página para reinterpretar, que es
    # exactamente lo que este proyecto existe para no hacer.
    "detalle",
    # `abrir_sesion` y `cerrar` son ciclo de vida, no consulta.
    "abrir_sesion",
    "cerrar",
    # `buscar` y `texto` del buscador de fallos se exponen con otro nombre.
    "buscar",
    "texto",
}


def test_toda_busqueda_del_cliente_esta_expuesta_o_excluida_a_proposito(expuestas):
    """`buscar_por_fecha` existió en el cliente y no estaba expuesta durante toda una versión.

    Es la cuarta búsqueda que la plataforma ofrece, y sin ella no había forma de responder
    "qué ingresó contra esta empresa esta semana" sabiendo el tribunal pero no el rol. Nadie
    lo notó porque nada comparaba las dos listas.
    """
    import inspect

    from mcp_pjud.client import PjudClient
    from mcp_pjud.juris import JurisClient

    metodos = {
        nombre
        for cliente in (PjudClient, JurisClient)
        for nombre, _ in inspect.getmembers(cliente, inspect.isfunction)
        if not nombre.startswith("_") and nombre not in NO_SON_HERRAMIENTAS
    }
    # Los nombres no calzan uno a uno: `buscar_por_rit` se expone como `buscar_causa_por_rit`.
    cubiertos = {
        m
        for m in metodos
        if any(
            m.replace("buscar_por_", "").replace("_", "") in h.replace("_", "") for h in expuestas
        )
    }
    sin_exponer = sorted(metodos - cubiertos)
    assert not sin_exponer, (
        f"El cliente sabe hacer esto y ninguna herramienta lo ofrece: {sin_exponer}. "
        "Si es deliberado, va a NO_SON_HERRAMIENTAS con la razón escrita."
    )


def test_la_herramienta_de_actuaciones_solo_ofrece_lo_que_funciona(expuestas):
    """El alias general de competencia ofrecía las cuatro buscables, y tres siempre fallan acá.

    Ofrecerle al modelo una opción que termina siempre en error lo hace intentarla y
    atribuirle el fallo a la plataforma. La fuente es la tabla: `receptor` dice si el sitio las
    expone y `receptor_en_historia` si se leen desde ahí.
    """
    sirven = {
        n for n in MODULOS if COMPETENCIAS[n].receptor and COMPETENCIAS[n].receptor_en_historia
    }
    assert sirven, "si ninguna competencia entrega actuaciones, la herramienta no debería existir"

    descripcion = (
        (expuestas["obtener_actuaciones_receptor"].input_schema or {})
        .get("properties", {})
        .get("competencia", {})
        .get("description", "")
    )
    for buena in sirven:
        assert buena in descripcion, f"{buena!r} entrega actuaciones y el esquema no la ofrece"
    ofrecidas = descripcion.split("Una de: ", 1)[-1].split(".", 1)[0]
    for otra in set(MODULOS) - sirven:
        assert otra not in ofrecidas, (
            f"el esquema ofrece {otra!r} como opción y la llamada siempre falla"
        )


def test_la_herramienta_de_documentos_solo_ofrece_lo_que_la_plataforma_emite(expuestas):
    """Misma trampa que en actuaciones, con otra tabla: `DOCUMENTOS`.

    Ofrecerle `penal` al modelo lo haría pedir un documento de una competencia cuyo detalle no
    emite ni un formulario de descarga, y el rechazo saldría de este servidor sin que la
    plataforma se entere. Y en la otra dirección: si mañana se mide una competencia nueva y el
    esquema no la nombra, el modelo no va a intentarla nunca.

    La ruta se verifica igual de estricto, y ése es el otro motivo del guardia: `documento_ruta`
    llega desde el modelo, así que la descripción tiene que nombrar las rutas aceptadas. Sin
    esa lista el modelo inventa una, la herramienta la rechaza, y parece una falla del sitio.
    """
    from mcp_pjud.client import DOCUMENTOS

    assert DOCUMENTOS, "si ninguna competencia emitiera documentos, la herramienta sobraría"

    propiedades = (expuestas["obtener_documento"].input_schema or {}).get("properties", {})
    competencia = propiedades["competencia"].get("description", "")
    for nombre in DOCUMENTOS:
        assert nombre in competencia, (
            f"{nombre!r} emite documentos y el esquema no la ofrece: el modelo no la va a usar"
        )
    for nombre in set(MODULOS) - set(DOCUMENTOS):
        assert nombre not in competencia, (
            f"el esquema ofrece {nombre!r} y su detalle no emite ningún formulario de "
            "descarga, así que esa llamada termina siempre en error"
        )

    ruta = propiedades["documento_ruta"].get("description", "")
    for rutas in DOCUMENTOS.values():
        for nombre in rutas:
            assert nombre in ruta, (
                f"la plataforma entrega documentos por {nombre!r} y el esquema no la nombra"
            )


def test_la_lectura_combinada_solo_ofrece_competencias_con_algun_panel(expuestas):
    """`obtener_detalle_causa` está en `sin_todas_las_competencias`, así que el guardia general
    no la mira, y sin este quedaría sin ninguno.

    Ofrecerle `penal` al modelo, que no tiene un solo panel medido, lo hace intentar una
    llamada que el cliente rechaza siempre y atribuirle el fallo a la plataforma.
    """
    sirven = {
        n
        for n in MODULOS
        if any(
            (
                COMPETENCIAS[n].historia,
                COMPETENCIAS[n].litigantes,
                COMPETENCIAS[n].notificaciones,
                COMPETENCIAS[n].liquidaciones,
                COMPETENCIAS[n].materias,
                COMPETENCIAS[n].exhortos,
            )
        )
    }
    assert sirven, "si ninguna competencia tuviera paneles, la herramienta no debería existir"
    assert set(MODULOS) - sirven, (
        "si todas tuvieran algún panel, este alias sobra y hay que usar el general"
    )

    descripcion = (
        (expuestas["obtener_detalle_causa"].input_schema or {})
        .get("properties", {})
        .get("competencia", {})
        .get("description", "")
    )
    ofrecidas = descripcion.split("Una de: ", 1)[-1].split(".", 1)[0]
    for buena in sirven:
        assert buena in ofrecidas, f"{buena!r} tiene paneles medidos y el esquema no la ofrece"
    for otra in set(MODULOS) - sirven:
        assert otra not in ofrecidas, (
            f"el esquema ofrece {otra!r} y la lectura combinada la rechaza siempre"
        )


def test_la_referencia_dice_cuales_competencias_entregan_actuaciones(expuestas):
    """La afirmación se repite en la referencia, el registro de cambios y el roadmap, y su
    fuente es `receptor_en_historia`. Sin guardia, implementar cobranza dejaría la referencia
    diciendo que se rechaza."""
    seccion = _secciones_de_herramientas()["obtener_actuaciones_receptor"]
    sirven = {
        n for n in MODULOS if COMPETENCIAS[n].receptor and COMPETENCIAS[n].receptor_en_historia
    }
    for buena in sirven:
        nombrada = f"**{buena}**" in seccion or f"`{buena}`" in seccion
        assert nombrada, f"la referencia no dice que {buena!r} entrega actuaciones"
    # Y las que no, tienen que estar nombradas como excluidas y no en silencio.
    for otra in set(COMPETENCIAS) - sirven:
        if COMPETENCIAS[otra].receptor:
            assert otra in seccion, (
                f"{otra!r} expone actuaciones que este servidor no lee, y la referencia lo calla"
            )


def test_la_hoja_de_ruta_no_declara_sin_ejecutar_lo_que_ya_se_verifico():
    """La misma página decía que las cuatro búsquedas de suprema y apelaciones se verificaron
    en vivo y, treinta líneas más abajo, que nada de esas competencias se había ejecutado.

    Una hoja de ruta que se contradice sobre el estado de verificación es peor que no tenerla:
    su único trabajo es distinguir lo medido de lo supuesto. La sección se quedó atrás porque
    nada la ataba a `MODULOS`, que es donde ese estado vive de verdad.
    """
    texto = _estado_y_plan()
    marca = "### Mapeado pero nunca ejecutado"
    assert marca in texto, "cambió el título de la sección; hay que reapuntar este guardia"

    seccion = texto.split(marca, 1)[1].split("###", 1)[0]
    # El detalle de varias competencias sí sigue sin ejecutarse, y nombrarlas ahí es correcto.
    # Lo que no puede aparecer es la afirmación de que sus BÚSQUEDAS no se probaron.
    verificadas = ", ".join(sorted(MODULOS))
    for busqueda in ("consultaNombre", "consultaJuridica", "consultaFecha", "consultaRit"):
        declarada = f"{busqueda}*.php`, `" in seccion or f"- `{busqueda}" in seccion
        assert not declarada, (
            f"la hoja de ruta declara {busqueda} sin ejecutar, y está verificada en {verificadas}"
        )


def test_la_hoja_de_ruta_no_publica_el_diagnostico_que_resulto_falso():
    """La hoja de ruta llegó a publicar una tabla de "por qué falla cada competencia" con dos
    causas que la medición desmintió.

    Decía que suprema y apelaciones fallaban porque sobraban los campos que el sitio
    deshabilita, y que la corrección era omitirlos. Las dos cosas son falsas: la búsqueda anda
    igual con o sin esos campos, y lo que faltaba era `radio-group`. Una hipótesis equivocada
    publicada como diagnóstico es peor que no publicar nada, porque el próximo lector la sigue
    en vez de medir.

    El guardia es sobre la explicación, no sobre el estado: si mañana alguna de las dos vuelve
    a fallar, hay que escribir por qué falla de verdad, y esa explicación tiene que nombrar el
    campo medido.
    """
    texto = _estado_y_plan()
    for frase in (
        "El sitio deja `conTipoCausa` **deshabilitado**",
        "jQuery no serializa campos deshabilitados",
    ):
        assert frase not in texto, (
            f"la hoja de ruta publica {frase!r} como causa, y la medición la desmintió: la "
            "búsqueda anda con y sin esos campos"
        )
    assert "radio-group" in texto, (
        "la hoja de ruta tiene que nombrar el campo que de verdad bloqueaba a suprema y "
        "apelaciones, o el diagnóstico se pierde"
    )


# -- las cifras de los ejemplos medidos -----------------------------------------
#
# La página de ejemplos afirma cantidades que se pueden contradecir entre sí con una edición
# parcial: el total de citas contra el desglose, "tres causas" contra las filas de su tabla,
# "cinco citas" contra las de la suya. Nada las ataba, y `AGENTS.md` exige que toda afirmación
# verificable de la documentación traiga su test.
#
# El guardia es de consistencia interna y no contra una constante inventada. Estas cifras no
# las usa el código: son el resultado de una verificación puntual, y darles una fuente única en
# `src/` sería agregar una constante muerta para que un test la lea. Lo que sí protege es que
# el desglose siga sumando y que cada cuadro tenga las filas que su prosa anuncia.

EJEMPLOS = RAIZ / "docs" / "ejemplos.md"


def _filas_de_tabla(texto: str, encabezado: str) -> list[str]:
    """Las filas de datos de la tabla que sigue a `encabezado`, sin la fila separadora."""
    resto = texto.split(encabezado, 1)[1]
    filas = []
    for linea in resto.splitlines():
        recortada = linea.strip()
        if not recortada.startswith("|"):
            if filas:
                break
            continue
        if set(recortada) <= set("|-: "):
            continue
        filas.append(recortada)
    return filas


def test_el_desglose_de_citas_verificadas_suma_el_total():
    """Verificadas más no encontradas tiene que dar el conjunto completo.

    El desglose ya cambió una vez: tres citas pasaron de "sin respuesta de la plataforma" a
    verificadas al descubrir que el tope de espera era nuestro. Esa fila desapareció y el total
    se movió. Sin este guardia, la próxima corrección deja la página diciendo dos cosas
    distintas sobre el mismo conjunto.
    """
    texto = _texto(EJEMPLOS)
    total = re.search(r"conjunto real de (\d+) citas", texto)
    assert total, "la página ya no declara el tamaño del conjunto de citas"

    filas = _filas_de_tabla(texto, "| Resultado | Cuántas |")
    cifras = [int(m.group(1)) for f in filas if (m := re.search(r"\|\s*(\d+)\s*\|?\s*$", f))]
    assert cifras, f"no se pudieron leer las cantidades del desglose: {filas}"
    assert sum(cifras) == int(total.group(1)), (
        f"el desglose suma {sum(cifras)} y el conjunto declara {total.group(1)} citas"
    )


def test_cada_cuadro_de_ejemplos_trae_las_filas_que_su_prosa_anuncia():
    """Una tabla y la frase que la introduce se editan por separado, y ahí se separan.

    Son las dos afirmaciones contables de la página: las causas donde se midió la brecha entre
    diligencia y registro, y las citas de la contraparte que se auditaron.
    """
    texto = _texto(EJEMPLOS)
    numeros = {"tres": 3, "cuatro": 4, "cinco": 5, "seis": 6}

    causas = re.search(r"sobre (\w+) causas distintas", texto)
    assert causas, "la página ya no dice sobre cuántas causas se midió la brecha de fechas"
    esperadas = numeros[causas.group(1)]
    filas = _filas_de_tabla(texto, "| Causa | Diligencia | Registro | Diferencia |")
    assert len(filas) == esperadas, (
        f"la prosa dice {causas.group(1)} causas y el cuadro trae {len(filas)} filas"
    )

    citas = re.search(r"(\w+) citas de un mismo informe", texto)
    assert citas, "la página ya no dice cuántas citas de la contraparte se auditaron"
    filas = _filas_de_tabla(texto, "| Rol | De qué es realmente |")
    assert len(filas) == numeros[citas.group(1)], (
        f"la prosa dice {citas.group(1)} citas y el cuadro trae {len(filas)} filas"
    )


def test_todo_lo_que_declara_una_version_dice_la_misma():
    """La versión se copiaba a mano en cuatro lugares y se quedó atrás en los cuatro.

    Al publicar la 0.2.0 seguían diciendo 0.1: el User-Agent identificaba cada petición ante el
    Poder Judicial como una versión que no era, la instalación fijada del README y de la guía
    apuntaba a una etiqueta inexistente, y `CITATION.cff` atribuía una fecha a una publicación
    que nunca ocurrió.

    El agente es el caso que no es cosmético: la regla 2 exige que sea identificable, y esa
    cadena es lo único que tiene la institución para saber qué software la consulta. Ahora sale
    del paquete instalado; los demás siguen escritos a mano y este guardia es lo que los ata.
    """
    version = tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["version"]

    # Se lee el header que un cliente MANDA, no la constante. La primera versión de este
    # guardia comparaba `client.VERSION` contra `pyproject.toml`, y con eso no podía fallar:
    # volver a escribir la versión a mano dentro del User-Agent lo dejaba verde, que es
    # exactamente el bug que este test existe para atrapar.
    from mcp_pjud.client import PjudClient

    agente = PjudClient("test@example.cl")._http.headers["User-Agent"]
    assert agente.startswith(f"mcp-pjud/{version} "), (
        f"el servidor se identifica ante el Poder Judicial como {agente!r} y el paquete es "
        f"la versión {version}"
    )

    # El ejemplo vivo del agente, que lleva el prefijo `User-Agent: `. La tabla de la medición
    # de user agents queda fuera a propósito: es el registro de lo que se envió aquella vez, y
    # actualizarla para que pase este guardia falsearía la medición.
    guia = _texto(RAIZ / "docs" / "instalacion.md")
    assert f"User-Agent: mcp-pjud/{version} " in guia, (
        f"la guía muestra un User-Agent que no es el que el servidor envía (mcp-pjud/{version})"
    )

    # Se miran TODAS las menciones y no si la buena está presente. `instalacion.md` trae dos, y
    # con "está presente" bastaba actualizar una: la otra seguía ofreciendo un bloque para pegar
    # que instala la versión anterior, o sea sin las correcciones que esa misma release anuncia.
    for archivo in ("README.md", "docs/instalacion.md"):
        ajenas = {
            v for v in re.findall(r"@v(\d+\.\d+\.\d+)", _texto(RAIZ / archivo)) if v != version
        }
        assert not ajenas, (
            f"{archivo} recomienda fijar {sorted(ajenas)} y la versión publicada es {version}. "
            "Quien pegue ese bloque instala una versión sin las correcciones de ésta."
        )

    # Lo que el servidor publica en `server/discover`, que la especificación de MCP exige
    # desde la revisión 2026-07-28. Estaba en su valor por defecto, o sea vacío: el servidor se
    # presentaba ante los clientes sin decir qué versión era.
    from mcp_pjud.server import mcp

    assert mcp.version == version, (
        f"el servidor MCP se presenta como versión {mcp.version!r} y el paquete es {version!r}"
    )

    # La descripción que el servidor publica sale de la misma metadata del paquete, así que
    # no puede quedar como una segunda copia del texto.
    proyecto = tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]
    assert mcp.description == proyecto["description"], (
        "el servidor MCP publica una descripción distinta de la que declara el paquete"
    )

    citation = _texto(RAIZ / "CITATION.cff")
    assert f"version: {version}" in citation, (
        f"CITATION.cff atribuye una versión distinta de {version}"
    )
    # La fecha es el otro dato repetido, y el que ya falló una vez: sin esto `CITATION.cff`
    # puede atribuir la publicación a un día en que no ocurrió, y es lo que se cita.
    fecha = re.search(
        rf"^## \[{re.escape(version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})", _registro(), re.M
    )
    assert fecha, f"el registro no fecha la versión {version}"
    assert f"date-released: '{fecha.group(1)}'" in citation, (
        f"el registro fecha {version} el {fecha.group(1)} y CITATION.cff dice otra cosa"
    )


def test_la_version_del_paquete_es_la_ultima_del_registro_de_cambios():
    """El registro de cambios y `pyproject.toml` se editan por separado, y ahí se separan.

    Ya pasó: la versión `0.1.0` quedó escrita en el registro con su enlace a
    `releases/tag/v0.1.0`, y esa etiqueta nunca se creó. El enlace estuvo muerto desde que se
    escribió y nada lo notó, porque nada comparaba una cosa con la otra.

    Subir la versión sin anotarla, o anotarla sin subirla, deja el paquete diciendo que es una
    versión y su registro diciendo que es otra. Quien instale desde el índice ve la primera.
    """
    version = tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["version"]
    publicadas = _versiones_del_registro()
    assert publicadas, "el registro de cambios no declara ninguna versión publicada"
    assert publicadas[0] == version, (
        f"`pyproject.toml` dice {version} y la última anotada en el registro es "
        f"{publicadas[0]}. Las versiones se anotan al publicarlas, no después."
    )


#: El modal de detalle por competencia, tal como lo nombra la plataforma.
_MODAL_DETALLE = {
    "laboral": "causaLaboral.php",
    "suprema": "causaSuprema.php",
    "apelaciones": "causaApelaciones.php",
    "penal": "causaPenal.php",
}


def test_el_detalle_mapeado_no_sigue_figurando_entre_las_rutas_sin_ejecutar():
    """Las dos afirmaciones ya se separaron una vez, y en el mismo commit.

    Al registrar que el detalle de `laboral` estaba medido, la hoja de ruta siguió listando
    `causaLaboral.php` entre las rutas mapeadas y nunca ejecutadas: dos estados incompatibles
    sobre la misma verificación, en la misma página.

    El guardia se ata al código y no a una lista escrita a mano: una competencia cuyo panel de
    historia está declarado en `parser.COMPETENCIAS` fue medida por definición, así que no
    puede seguir apareciendo como ruta sin ejecutar.

    `penal` es el caso que obliga a separar dos cosas que se parecen: su modal SÍ se ejecutó,
    y no quedó mapeado porque la respuesta trajo cero filas. Ejecutar no es mapear, y la hoja
    de ruta tiene que decir por qué.
    """
    texto = _estado_y_plan()
    sin_ejecutar = texto.split("### Mapeado pero nunca ejecutado", 1)[1].split("###", 1)[0]

    for competencia, modal in _MODAL_DETALLE.items():
        if COMPETENCIAS[competencia].historia is None:
            continue
        assert modal not in sin_ejecutar, (
            f"el detalle de {competencia} está mapeado en el código y {modal} sigue entre las "
            "rutas sin ejecutar"
        )

    sin_mapear = [c for c in _MODAL_DETALLE if COMPETENCIAS[c].historia is None]
    for competencia in sin_mapear:
        assert f"`{competencia}`" in texto, (
            f"{competencia} no está mapeada y la hoja de ruta no dice nada de ella"
        )


def test_el_contrato_no_llama_sin_medir_a_un_panel_que_ya_entrega(expuestas):
    """La advertencia de que el detalle no es el expediente completo enumera los paneles que
    faltan, y esa lista se escribe a mano.

    Al exponer `exhortos` quedó contradiciéndose a ocho líneas de distancia: el título
    prometía el campo y el aviso seguía diciendo que no estaba medido. Un modelo que lee eso
    ignora una lista vacía legítima, o presenta el campo como incompleto.

    El guardia se ata al modelo: cualquier campo que alguna competencia declare es un panel
    que se entrega, y no puede aparecer en la frase de lo que falta.
    """
    from mcp_pjud.parser import DetalleCausa

    contrato = (expuestas["obtener_detalle_causa"].description or "").lower()
    aviso = contrato.split("no es el expediente completo", 1)[1].split("\n\n", 1)[0]

    entregados = {
        campo
        for campo in DetalleCausa.model_fields
        if campo != "causa_encontrada"
        and any(getattr(COMPETENCIAS[n], campo, None) is not None for n in MODULOS)
    }
    assert entregados, "si ningún panel estuviera medido, la herramienta no debería existir"

    for campo in entregados:
        assert campo not in aviso, (
            f"el contrato entrega {campo!r} y el aviso lo nombra entre los paneles sin medir"
        )


def test_el_diagrama_de_la_detencion_nombra_todo_lo_que_la_detiene():
    """El diagrama nombraba `ReadError` y `ConnectError`, que son dos subclases, y la constante
    son dos clases BASE que cubren más: también la escritura cortada y el protocolo roto.

    Quien diagnostique por qué quedó bloqueado el proceso lee esta página, y un diagrama que
    enumera de menos manda a buscar la causa donde no está. La fuente es la constante.
    """
    from mcp_pjud.client import _RECHAZO_DE_CONEXION

    pagina = _texto(RAIZ / "docs" / "cumplimiento.md")
    # Acotado al bloque del diagrama y no a la página entera: la prosa de al lado nombra las
    # mismas clases, así que mirar todo dejaba pasar un diagrama que enumeraba de menos. Se vio
    # rompiéndolo: la primera versión de este guardia seguía verde con el error puesto.
    diagrama = pagina.split("```mermaid", 1)[1].split("```", 1)[0]
    for clase in _RECHAZO_DE_CONEXION:
        assert clase.__name__ in diagrama, (
            f"{clase.__name__} activa la detención total y el diagrama no lo nombra"
        )

    import httpx

    assert httpx.TimeoutException not in _RECHAZO_DE_CONEXION, (
        "si los timeouts pasaran a detener, el diagrama diría lo contrario de lo que hace el "
        "código: una consulta lenta y normal dejaría el servidor detenido"
    )
    assert "NO detiene" in pagina, "el diagrama dejó de decir que un timeout no detiene"


def test_toda_pagina_publicada_lleva_el_enlace_al_repositorio():
    """`source_repository` pone "Ver código fuente" arriba a la derecha y sólo en las páginas
    de contenido: la portada queda sin ninguna forma de llegar al repositorio.

    Quien evalúa si este software le sirve necesita ver el código, la licencia y quién lo
    mantiene, y si no encuentra el enlace en la primera página asume que no lo hay. `Furo`
    ofrece `footer_icons` justo para eso, así que no hay que inventarlo.

    El guardia mira la configuración del tema y no el HTML construido, porque construir la
    documentación entera dentro de un test la haría lenta sin decir nada más.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_conf_tema", RAIZ / "docs" / "conf.py")
    assert spec is not None
    assert spec.loader is not None
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)

    iconos = conf.html_theme_options.get("footer_icons", [])
    assert iconos, (
        "sin `footer_icons` la portada publicada no tiene ninguna forma de llegar al "
        "repositorio: `source_repository` sólo aparece en las páginas de contenido"
    )
    repos = tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["urls"]["Repositorio"]
    assert any(i.get("url", "").rstrip("/") == repos.rstrip("/") for i in iconos), (
        f"el icono del pie apunta a otra parte y el paquete declara {repos!r}"
    )


def test_la_referencia_publica_nombra_todos_los_campos_de_una_actuacion():
    """La tabla de campos y los ejemplos se escriben a mano, así que un campo nuevo entra al
    modelo y no a la página: quien consulte la referencia no descubre justo el dato nuevo.

    Pasó con `documento_referencia`, que es lo único que permite pedir un documento.
    """
    from mcp_pjud.parser import Actuacion

    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    faltan = [c for c in Actuacion.model_fields if f"`{c}`" not in referencia]
    assert not faltan, (
        f"campos de una actuación que el modelo entrega y la referencia no nombra: {faltan}"
    )


def test_el_listado_de_tribunales_exige_la_corte(expuestas):
    """Con un valor por defecto, una consulta destinada a otra jurisdicción devolvía en
    silencio los tribunales de esa corte: una lista plausible y equivocada, y el modelo no
    tiene cómo notar que no preguntó por ésa.

    Es la única herramienta que puede exigir `corte`, porque ahí no acota una búsqueda de
    causas: dice DE QUÉ corte se quieren los tribunales. Por eso el guardia general la exime,
    y por eso hace falta éste: sin él, la exención permite volver al valor por defecto.
    """
    esquema = expuestas["listar_tribunales"].input_schema or {}
    assert "corte" in set(esquema.get("required", [])), (
        "`corte` volvió a ser opcional, y con eso una consulta a otra jurisdicción devuelve "
        "los tribunales de la corte por defecto sin decirlo"
    )


def _parrafos_de_reglas(texto: str) -> dict[str, str]:
    """El texto de cada regla numerada, por separado.

    Los dos archivos las enumeran distinto, `**1. ...**` en uno y `1. **...**` en el otro, así
    que se reconoce el número y no el formato. Cada regla llega hasta que empieza la
    siguiente.
    """
    plano = " ".join(texto.split())
    tramos: dict[str, str] = {}
    marcas = [
        (m.group(1), m.start())
        for m in re.finditer(r"(?:\*\*)?([1-5])\.\s\*?\*?[A-ZÁÉÍÓÚN]", plano)
    ]
    for (numero, inicio), siguiente in zip(marcas, [*marcas[1:], (None, len(plano))], strict=True):
        tramos.setdefault(numero, plano[inicio : siguiente[1]])
    return tramos


def test_las_cinco_reglas_dicen_lo_mismo_donde_sea_que_se_escriban():
    """Las reglas que no se negocian están escritas en tres archivos, y ya divergieron.

    `CONTRIBUTING.md` decía "sin persistencia **por defecto**", que insinúa una configuración
    que la enciende, mientras `AGENTS.md` y el README dicen que no hay ninguna. En un
    documento de reglas, un matiz así no es una redacción distinta: es otra regla.

    Se comprueba que cada regla esté presente por su idea y no por su párrafo: cada archivo la
    desarrolla para su lector, y exigirles el mismo texto obligaría a escribir tres veces lo
    mismo, que es el problema del que se viene.

    La primera versión de este guardia recorría un diccionario que nunca consumía y terminaba
    en `assert titulos`, que sólo comprobaba que un literal no estuviera vacío: las reglas 1 a
    4 podían divergir enteras y seguía verde. Es exactamente el error que este proyecto
    persigue, cometido en el guardia que venía a evitarlo.
    """
    #: Cada regla, por las palabras sin las que deja de ser esa regla. No es el párrafo: es lo
    #: que no puede faltar.
    REGLAS = {
        "1. no escribir": ("ingreso", "modificaci"),
        "2. el ritmo": ("cada 5 segundos", "cláusula CUARTA"),
        "3. detención total": ("403", "429", "detención total"),
        "4. fallo ruidoso": ("lista vacía", "plazos"),
        "5. sin persistencia": ("Sin persistencia de datos de terceros",),
    }
    archivos = {
        "AGENTS.md": _texto(RAIZ / "AGENTS.md"),
        ".github/CONTRIBUTING.md": _texto(RAIZ / ".github" / "CONTRIBUTING.md"),
    }
    # El README es para quien la usa, no para quien contribuye: enumera menos y está bien.

    faltantes = {}
    for nombre, texto in archivos.items():
        # Cada regla se busca en SU párrafo, no en el documento entero. Con el documento
        # entero el guardia era parcialmente vacuo, y se comprobó: quitarle el 403 al
        # enunciado de la regla 3 seguía verde, porque `AGENTS.md` menciona un 403 en otro
        # párrafo que habla del cortafuegos. La regla vive donde se enuncia.
        parrafos = _parrafos_de_reglas(texto)
        for regla, señas in REGLAS.items():
            numero = regla.split(".", 1)[0]
            propio = parrafos.get(numero, "")
            assert propio, f"{nombre} no enuncia la regla {numero} con su número"
            ausentes = [x for x in señas if x.lower() not in propio.lower()]
            if ausentes:
                faltantes[f"{nombre} / {regla}"] = ausentes
    assert not faltantes, (
        f"Reglas que un documento enuncia sin lo que las define: {faltantes}. En un documento "
        "de reglas eso no es estilo, es otra regla."
    )

    for nombre, texto in archivos.items():
        assert "por defecto" not in texto.split("persistencia", 1)[1][:40], (
            f"{nombre} matiza la regla 5 con un 'por defecto' que la vuelve otra regla"
        )


#: El commit que partió la hoja de ruta. Los encabezados que tenía antes de eso publicaban un
#: ancla citable, y moverlos sin dejar nada no da 404: da el inicio de la página, en silencio.
#: Un enlace roto se nota; uno que va al lugar equivocado, no.
CORTE_DE_LA_HOJA_DE_RUTA = "356ffce"


def test_los_enlaces_publicados_a_la_hoja_de_ruta_siguen_llegando_a_alguna_parte():
    """Al partir la hoja de ruta, sus fragmentos publicados quedaron apuntando al vacío.

    La primera versión de este guardia comparaba contra una lista de seis escrita a mano, y
    los encabezados que se fueron eran **veintinueve**. Ahora la lista se saca de git: se
    comparan los encabezados de antes del corte contra los anclajes que la página conserva
    hoy, así que no hay lista que mantener ni número que acertar.

    Y se cuentan también los de nivel 4, aunque `myst_heading_anchors` esté en 3: `docutils`
    le pone un `id` a toda sección, así que esos anclajes existían igual. Eso se midió sobre
    el HTML construido, no se dedujo de la configuración.
    """
    import subprocess
    import unicodedata

    antes = subprocess.run(  # noqa: S603
        ["git", "show", f"{CORTE_DE_LA_HOJA_DE_RUTA}^:docs/roadmap.md"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert antes.returncode == 0, (
        f"no se pudo leer `docs/roadmap.md` en {CORTE_DE_LA_HOJA_DE_RUTA}^, que es contra lo "
        "que se comparan los anclajes publicados. Si es un clon superficial, hace falta "
        "`fetch-depth: 0`.\n\n"
        "Antes esto era un `skip`, y con el checkout por defecto de CI el guardia no corría "
        "nunca: verde donde importa y roto en lo publicado. Un guardia que se salta solo es "
        f"peor que no tenerlo.\n\n{antes.stderr}"
    )

    def ancla(titulo: str) -> str:
        plano = "".join(
            c for c in unicodedata.normalize("NFD", titulo) if unicodedata.category(c) != "Mn"
        )
        return re.sub(r"[\s_]+", "-", re.sub(r"[^\w\s-]", "", plano.lower()).strip())

    hoja = _texto(RAIZ / "docs" / "roadmap.md")
    vigentes = {ancla(t) for t in re.findall(r"^#{1,4} (.+)$", hoja, re.M)}
    vigentes |= set(re.findall(r"^\(([\w-]+)\)=", hoja, re.M))

    faltan = sorted({ancla(t) for t in re.findall(r"^#{2,4} (.+)$", antes.stdout, re.M)} - vigentes)
    assert not faltan, (
        f"la hoja de ruta publicó estos anclajes y ya no los tiene: {faltan}. Un enlace a "
        "cualquiera de ellos lleva ahora al inicio de la página sin avisar."
    )


#: El estudio que se cita para no justificar decisiones con `llms.txt`. Vive acá porque la
#: cifra está escrita a mano en tres lugares y no sale de ningún código: es una fuente externa.
#: Lo que el guardia puede hacer no es verificarla, es impedir que las tres copias se
#: contradigan, que es el modo de falla real.
AHREFS = {"dominios": "137.210", "sin_peticiones": "97%", "fecha": "mayo de 2026"}


def test_las_tres_copias_del_estudio_de_llms_txt_dicen_lo_mismo():
    """La cifra está escrita a mano en `ecosistema.md`, en `conf.py` y en la propuesta.

    No sale de ningún código, así que ningún guardia puede verificarla: es una fuente externa.
    Lo que sí se puede impedir es que una se corrija y las otras dos queden diciendo otra cosa.

    NO se filtra a las que ya traen la cifra, que es lo que hacía la primera versión: eso
    excluía del chequeo justo a la página que divergía, y se comprobó cambiando el número en
    una de las tres. Se identifican por citar el estudio, no la cifra.
    """
    donde = ("docs/ecosistema.md", "docs/conf.py", "docs/_propuesta-arquitectura.md")
    citan = [d for d in donde if "Ahrefs" in _texto(RAIZ / d)]
    assert len(citan) == len(donde), (
        f"el estudio se citaba en {len(donde)} lugares y ahora en {len(citan)}: {citan}. Si se "
        "retiró de alguno a propósito, hay que sacarlo de esta lista."
    )

    for d in citan:
        # Sin los marcadores de comentario: en `conf.py` la cita va en un comentario envuelto,
        # y sin quitarlos el texto comparado queda como "137.210 # dominios", lo que obliga a
        # reacomodar la prosa para que el guardia pase. Eso es el guardia mandando sobre el
        # texto en vez de al revés.
        crudo = _texto(RAIZ / d)
        texto = " ".join(re.sub(r"^\s*#\s?", "", crudo, flags=re.M).split())
        for clave, valor in AHREFS.items():
            assert valor in texto, (
                f"{d} cita el estudio sin su {clave} ({valor}). Las tres copias tienen que "
                "decir lo mismo, porque ninguna se puede verificar contra el código."
            )


def test_la_directiva_no_afirma_de_la_georreferencia_mas_que_el_modelo():
    """La directiva es lo que el modelo lee ANTES de cualquier llamada, así que una afirmación
    de más ahí pesa más que en cualquier otro lugar.

    Decía que `false` prueba que el registro no está, sin más. Suprema no publica la columna,
    así que su falso significa que no hay dónde mirar, y confundirlos hace concluir que una
    diligencia no se georreferenció cuando lo que pasa es que esa competencia no lo informa.

    Las competencias se sacan de la tabla, no de una lista escrita a mano.
    """
    from mcp_pjud.server import DIRECTIVA

    con_columna = sorted(
        n
        for n in MODULOS
        if (h := COMPETENCIAS[n].historia) is not None and "georref" in h.columnas
    )
    assert con_columna, "si ninguna publicara la columna, el campo no debería existir"
    assert set(MODULOS) - set(con_columna), (
        "si todas la publicaran, la salvedad sobra y hay que retirarla de la directiva"
    )

    for nombre in con_columna:
        assert nombre in DIRECTIVA, (
            f"{nombre!r} publica la columna de georreferencia y la directiva no lo nombra, así "
            "que el modelo no puede saber dónde su `false` significa ausencia"
        )


def _numero(n: int) -> str:
    """El número en palabras, para comparar contra prosa.

    Levanta con un mensaje propio fuera de rango en vez de reventar con `KeyError`: un guardia
    que se cae con una traza no dice qué pasó, y acá lo que pasa es que la fixture cambió de
    tamaño.
    """
    palabras = {
        1: "una",
        2: "dos",
        3: "tres",
        4: "cuatro",
        5: "cinco",
        6: "seis",
        7: "siete",
        8: "ocho",
        9: "nueve",
        10: "diez",
    }
    assert n in palabras, (
        f"la fixture pasó a traer {n}, que no está en la tabla de números en palabras. "
        "Agregarlo acá es parte de actualizar la prosa."
    )
    return palabras[n]


def test_la_georreferencia_documentada_es_la_que_traen_las_fixtures():
    """Tres afirmaciones verificables entraron sin guardia: cuántas actuaciones tienen
    georreferencia, cuántas rutas hay y con qué parámetro se piden.

    La primera entró mal, y es la peor forma de entrar mal en este proyecto: decía tres, que
    son las del cuaderno principal, y son seis contando el de apremio. Es el falso negativo
    que originó todo esto, cometido en su propia documentación.
    """
    fixtures = RAIZ / "tests" / "fixtures"
    refs = set()
    for nombre in ("c1156_principal.html", "c1156_apremio.html"):
        refs |= set(re.findall(r"geoReferencia\('([^']+)'\)", _texto(fixtures / nombre)))
    assert len(refs) >= 2, "las fixtures dejaron de traer georreferencias"

    # Anclado a la página que OWNS el dato, no a las dos: se comprobó rompiéndolo con la
    # concatenación puesta y quedaba verde, porque la copia de la otra página lo rescataba.
    hoja = _texto(RAIZ / "docs" / "verificacion.md")
    # Sin alternativas: cada `or` de más era una forma de no fallar, y las dos que tenía lo
    # eran. `str(len(refs)) in hoja` calzaba con el 6 suelto de "| Precisión | 6 metros |", así
    # que cambiar el número a "tres" seguía verde: el falso negativo exacto que este guardia
    # dice existir para atrapar. Se exige la palabra, en negrita y junto a lo que cuenta.
    assert f"**{_numero(len(refs))}** actuaciones georreferenciadas" in hoja, (
        f"las fixtures traen {len(refs)} actuaciones georreferenciadas entre los dos "
        "cuadernos, y la documentación dice otra cosa"
    )

    # Las rutas y el parámetro salen del JavaScript versionado, no de una lista a mano.
    js = _texto(fixtures / "consultaUnificada.html")
    rutas = set(re.findall(r"([\w/]*modal/geoReferencia\w*\.php)", js))
    assert rutas, "la fixture dejó de traer las rutas de georreferencia"
    # `numeros.get(n, "")` devolvía cadena vacía para cualquier cuenta fuera del diccionario,
    # y `"" in hoja` es verdadero siempre: este `or` no podía fallar.
    assert f"Hay {_numero(len(rutas))} rutas" in hoja, (
        f"son {len(rutas)} rutas de georreferencia y la documentación dice otra cosa"
    )
    parametro = re.search(r"geoReferenciaCivil\.php'.{0,400}?data\s*:\s*\{\s*(\w+)", js, re.S)
    assert parametro, "la fixture dejó de mostrar con qué parámetro se pide la georreferencia"
    assert f"`{parametro.group(1)}`" in hoja, (
        f"la georreferencia se pide con {parametro.group(1)!r} y la documentación dice otra cosa"
    )


def test_toda_pagina_publicada_declara_de_que_trata():
    """La descripción de cada página es lo que muestra un buscador y lo que se ve al compartir
    el enlace, y es donde la audiencia se nombra sin partir el árbol en dos.

    Sin ella, Sphinx no emite `<meta name="description">` y la página queda sin resumen. Es
    barato de poner y nadie lo nota si falta, que es la combinación que hace falta un guardia.
    """
    sin = []
    for pagina in sorted(RAIZ.glob("docs/*.md")):
        cabecera = _texto(pagina).split("---\n", 2)
        if len(cabecera) < 3 or "description:" not in cabecera[1]:
            sin.append(pagina.name)
    assert not sin, (
        f"páginas publicadas sin descripción: {sin}. Va en el front matter, bajo "
        "`myst: html_meta: description`."
    )


def test_la_portada_declara_las_dos_lecturas():
    """La documentación se escribió para dos audiencias que comparten las mismas páginas, y la
    portada le hablaba sólo a una.

    No se parte el árbol: se agrega una segunda entrada. Lo que este guardia exige es que la
    segunda exista y lleve a `verificacion`, que es la página que responde la única pregunta
    que las dos audiencias comparten: ¿este dato se puede afirmar?
    """
    portada = _texto(RAIZ / "docs" / "index.md")
    puerta = portada.split("## Por dónde empezar", 1)
    assert len(puerta) == 2, "la portada dejó de tener la sección de entrada"

    # Con el salto de línea: "## " calza también dentro de "### ", así que sin él el corte
    # caía justo en el subtítulo de la segunda puerta y se llevaba lo que venía a comprobar.
    segunda = puerta[1].split(chr(10) + "## ", 1)[0]
    assert "evaluar o auditar" in segunda, (
        "la portada no declara la segunda lectura, así que quien viene a auditar el código no "
        "sabe por dónde entrar"
    )
    for destino in ("verificacion", "cumplimiento", "licencia"):
        assert f"<{destino}>" in segunda or f"`{destino}`" in segunda, (
            f"la segunda entrada no lleva a {destino!r}"
        )


def test_la_cuenta_de_dependencias_que_cita_la_guia_es_la_del_paquete():
    """La guía de instalación abre diciendo cuántas dependencias trae, y es lo primero que
    alguien mira para decidir si esto le entra al entorno.

    Quedó vieja al entrar `pypdf`: decía cuatro y eran cinco. Nadie lo iba a notar, porque el
    número está en una frase y no en una tabla.
    """
    numeros = {1: "Una", 2: "Dos", 3: "Tres", 4: "Cuatro", 5: "Cinco", 6: "Seis", 7: "Siete"}
    cuantas = len(tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["dependencies"])
    guia = _texto(RAIZ / "docs" / "instalacion.md")

    dicho = re.search(r"(\w+) dependencias\.", guia)
    assert dicho, "la guía dejó de decir cuántas dependencias trae"
    assert dicho.group(1) == numeros[cuantas], (
        f"la guía dice {dicho.group(1).lower()} dependencias y el paquete declara {cuantas}"
    )


def test_la_cuenta_de_cortes_que_cita_la_referencia_es_la_medida():
    """La referencia dice cuántas cortes hay, y es un dato que se escribe a mano.

    Importa: quien lea "17" y reciba 12 no sabe si la plataforma cambió o si la respuesta vino
    truncada. La fixture es un recorte de la respuesta real y trae la cuenta en el nombre del
    campo, no en la cantidad de filas guardadas, porque guardar las 17 con nombre y código no
    agrega nada que este guardia use.
    """
    import json

    fixture = json.loads(_texto(RAIZ / "tests" / "fixtures" / "combos_cortes.json"))
    assert all("COD_CORTE" in c and "GLS_CORTE" in c for c in fixture), (
        "la fixture de cortes cambió de forma y el cliente la lee por esos dos campos"
    )

    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    dicho = re.search(r"\*\*(\d+) cortes\*\*", referencia)
    assert dicho, "la referencia dejó de decir cuántas cortes hay"
    assert dicho.group(1) == str(CORTES_MEDIDAS), (
        f"la referencia dice {dicho.group(1)} cortes y lo medido son {CORTES_MEDIDAS}"
    )


def test_los_codigos_de_tribunal_que_cita_la_documentacion_son_los_medidos():
    """La hoja de ruta afirma que 162 es el 2º Juzgado Civil de Concepción y 163 el 3º.

    Antes de esta medición el 163 estaba DEDUCIDO: se supuso que seguía al 162 y salió bien,
    que es justo la forma de acertar que la regla de medir antes de exponer existe para no
    aceptar. Ahora hay una respuesta real recortada como fixture y la prosa se compara contra
    ella en vez de repetirse a sí misma.

    Se comprueba por cercanía: donde la página nombra un tribunal medido, su código tiene que
    estar cerca. La primera versión de este guardia comparaba presencia suelta en toda la
    página y no podía fallar, y se supo cambiándole el número a la prosa.
    """
    import json

    medidos = {
        t["COD_TRIBUNAL"]: t["GLS_TRIBUNAL"]
        for t in json.loads(_texto(RAIZ / "tests" / "fixtures" / "combos_tribunales.json"))
    }
    assert medidos, "la fixture de tribunales quedó vacía"

    hoja = _estado_y_plan()
    citados = {c: n for c, n in medidos.items() if n in hoja}
    assert citados, "la hoja de ruta dejó de nombrar los tribunales medidos"

    # El chequeo estricto se hace por PAR y sobre el texto con los espacios normalizados, no
    # por línea: el ejemplo de JSON viene partido en dos líneas en la prosa, así que un
    # chequeo por línea no ve el emparejamiento. Se comprobó rompiéndolo así y quedaba verde.
    #
    # Y se limita a los pares explícitos `COD_TRIBUNAL`/`GLS_TRIBUNAL` en vez de a cualquier
    # cercanía, porque la prosa compara dos códigos a propósito ("163 se dedujo porque 162 era
    # el 2º Juzgado") y exigirle que no nombre otro la haría imposible de escribir.
    plano = " ".join(hoja.split())
    pares = re.findall(r'"COD_TRIBUNAL":\s*"(\d+)",\s*"GLS_TRIBUNAL":\s*"([^"]+)"', plano)
    assert pares, "la documentación dejó de traer un par código/tribunal como dato"
    for codigo, nombre in pares:
        assert medidos.get(codigo) == nombre, (
            f"la documentación empareja el código {codigo} con {nombre!r}, y lo medido es "
            f"{medidos.get(codigo)!r}"
        )

    for codigo, nombre in citados.items():
        cerca = False
        desde = 0
        while (i := hoja.find(nombre, desde)) != -1:
            if codigo in hoja[max(0, i - 120) : i + len(nombre) + 120]:
                cerca = True
                break
            desde = i + 1
        assert cerca, (
            f"la documentación nombra {nombre!r} y en ninguna de sus menciones dice que su "
            f"código es {codigo}, que es el medido"
        )


def test_las_rutas_de_documentos_de_la_hoja_de_ruta_son_las_de_la_respuesta_real():
    """La hoja de ruta nombraba UNA ruta de documentos y la respuesta trae seis.

    Quedó así porque se escribió de memoria en vez de mirar la respuesta guardada, que las
    tenía a la vista con su parámetro y todo. El guardia se ata a la fixture: si el sitio
    agrega o retira una ruta de documentos, la página deja de listarlas y se entera.
    """
    fixture = _texto(RAIZ / "tests" / "fixtures" / "c1156_principal.html")

    rutas = set(re.findall(r"civil/documentos/([\w.-]+\.php)", fixture))
    assert len(rutas) >= 6, f"la fixture dejó de traer las rutas de documentos: {rutas}"

    # Acotado a la SECCIÓN de la tabla y no a la página entera. Se comprobó rompiéndolo:
    # cambiar una ruta en la tabla seguía verde, porque el nombre viejo aparecía en otro
    # párrafo de la misma página, en la lista de rutas mapeadas y sin ejecutar.
    seccion = (
        _texto(RAIZ / "docs" / "verificacion.md")
        .split("## Las rutas que entregan documentos", 1)[1]
        # Con cota superior: sin ella la "sección" llegaba al final del archivo y abarcaba dos
        # secciones más, así que una ruta nombrada en cualquiera de ellas satisfacía el
        # chequeo sin estar en la tabla. El comentario decía "acotado" y no lo estaba.
        .split("\n## ", 1)[0]
    )
    hoja = seccion
    for ruta in rutas:
        assert ruta in hoja, (
            f"la respuesta real ofrece {ruta!r} para descargar documentos y la hoja de ruta no "
            "la nombra"
        )

    # Y el parámetro de cada una, que es lo que hace falta para invocarla. Se saca de la
    # fixture y no de una lista escrita a mano.
    for ruta in rutas:
        tramo = fixture.split(ruta, 1)[1][:400]
        nombres = re.findall(r"name='([\w]+)'", tramo)
        assert nombres, f"la fixture ya no muestra con qué parámetro se invoca {ruta!r}"
        assert nombres[0] in seccion, (
            f"{ruta!r} se invoca con {nombres[0]!r} y la tabla de la hoja de ruta dice otra cosa"
        )


def test_lo_que_la_hoja_de_ruta_dice_del_exhorto_es_lo_que_traen_las_fixtures():
    """La página afirmaba en un párrafo que no se entendía cuándo aparece `piezasExhortoCiv` y
    en el de al lado que sí, con la explicación. Dos respuestas incompatibles a la misma
    pregunta, en la misma página.

    Pasó porque la conclusión se agregó y la viñeta anterior no se retiró. El guardia se ata a
    la evidencia versionada y no a la prosa: las fixtures dicen qué panel trae cada causa, así
    que la tabla de la hoja de ruta se compara contra ellas.

    Los exhortos se cuentan con el parser del proyecto y no con XPath a mano: es el mismo
    código que produce la respuesta, así que si cambia el mapeo esto se entera.
    """
    from mcp_pjud.parser import parse_exhortos

    FIXT = RAIZ / "tests" / "fixtures"
    # C-1156 es el ORIGEN: despacha un exhorto y no es uno. E-468 es el DESTINO: ES un exhorto,
    # y por eso trae las piezas que el tribunal de origen le mandó.
    esperado = {
        "c1156_principal.html": (1, False),
        "detalle_causa_civil.html": (0, True),
    }

    # El diagrama dibujaba una flecha de C-1156 a E-468 como si fueran los dos extremos del
    # mismo exhorto. No lo son: E-468 tiene como origen a C-15411-2025. Por eso el guardia
    # comprueba los roles y el tribunal, no sólo cuántas filas hay.
    despachado = parse_exhortos(_texto(FIXT / "c1156_principal.html"), "civil")[0]
    assert (despachado.rol_origen, despachado.rol_destino) == ("C-1156-2026", "E-875-2026")
    assert despachado.tribunal_destino == "1º Juzgado Civil de Chillán"
    assert "C-15411-2025" in _texto(FIXT / "detalle_causa_civil.html"), (
        "E-468-2026 ya no nombra a su causa de origen, y el diagrama la dibuja"
    )

    for nombre, (exhortos, tiene_piezas) in esperado.items():
        texto = _texto(FIXT / nombre)
        assert len(parse_exhortos(texto, "civil")) == exhortos, (
            f"{nombre} cambió cuántos exhortos despacha, y la hoja de ruta dice {exhortos}"
        )
        presente = 'id="piezasExhortoCiv"' in texto
        assert presente is tiene_piezas, (
            f"{nombre} {'trae' if presente else 'no trae'} el panel de piezas y la hoja de "
            f"ruta dice lo contrario"
        )

    # El diagrama repite las mismas cifras que la tabla, así que es un lugar más donde pueden
    # quedar viejas. Se exige que las diga, no que las dibuje de alguna forma concreta.
    hoja = _texto(RAIZ / "docs" / "verificacion.md")
    diagrama = hoja.split("## Los dos lados del exhorto", 1)[1].split("```", 2)[1]
    for exigido in (
        "C-1156-2026",
        "E-875-2026",
        "C-15411-2025",
        "E-468-2026",
        "exhortosCiv: 1 fila",
        "piezasExhortoCiv: SIN PANEL",
        "exhortosCiv: 0 filas",
        "piezasExhortoCiv: 6 filas",
    ):
        assert exigido in diagrama, (
            f"el diagrama de los dos lados del exhorto ya no dice {exigido!r}, y las fixtures "
            "siguen diciendo eso"
        )

    # La comprobación es sobre la página ENTERA y no sobre una ventana de 1.500 caracteres
    # antes de la sección: al mudar el texto de página, esa ventana pasó a caer sobre prosa
    # de otro tema y el guardia sobrevivió al movimiento dejando de guardar en silencio.
    assert "no está entendido" not in hoja, (
        "la hoja de ruta sigue diciendo que no se entiende cuándo aparece el panel, y el "
        "párrafo siguiente lo explica: dos respuestas a la misma pregunta"
    )


def test_las_tablas_de_competencias_de_la_referencia_salen_del_codigo():
    """Las dos se escribían a mano copiando lo que dice `parser.COMPETENCIAS`.

    La de paneles ya había quedado vieja: decía "las mismas cinco" y "sólo cobranza", frases
    que hay que reescribir cada vez que una competencia gana un panel y que nadie reescribe.
    Ahora las emite `docs/conf.py` al construir, igual que los esquemas.

    El guardia no compara la prosa contra el código, que es lo que se acaba de retirar: corre
    el generador y exige que ninguna competencia ni ningún panel se caiga de la tabla, y que
    la referencia siga incluyéndolas en vez de volver a escribirlas.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_conf_docs", RAIZ / "docs" / "conf.py")
    assert spec is not None
    assert spec.loader is not None
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)
    conf._generar_tablas(None)

    generado = RAIZ / "docs" / "_generado"
    acotacion = _texto(generado / "acotacion.md")
    paneles = _texto(generado / "paneles.md")

    for nombre in MODULOS:
        assert f"`{nombre}`" in acotacion, f"{nombre!r} se cayó de la tabla de acotación"

    for campo in (
        "historia",
        "litigantes",
        "notificaciones",
        "liquidaciones",
        "materias",
        "exhortos",
        "piezas_exhorto",
    ):
        fila = next((f for f in paneles.splitlines() if f.startswith(f"| `{campo}`")), None)
        assert fila, f"la tabla de paneles no tiene fila para {campo!r}"
        cuales = {n for n in MODULOS if getattr(COMPETENCIAS[n], campo) is not None}
        for nombre in cuales:
            assert f"`{nombre}`" in fila, f"{nombre!r} publica {campo!r} y la tabla no lo dice"
        for nombre in set(MODULOS) - cuales:
            assert f"`{nombre}`" not in fila, (
                f"la tabla dice que {nombre!r} publica {campo!r} y el código dice que no"
            )

    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    for archivo in ("acotacion", "paneles"):
        assert f"_generado/{archivo}.md" in referencia, (
            f"la referencia dejó de incluir {archivo}.md, así que volvió a escribirla a mano"
        )


def test_el_readme_nombra_todas_las_herramientas_que_el_servidor_expone(expuestas):
    """La portada listaba dos de ocho y decía "Ambas", así que además de incompleta afirmaba
    que eso era todo.

    Quedó así por acumulación: cada herramienta nueva entró con su sección en la referencia,
    que sí tiene guardia, y nadie volvió a la tabla del README. Es la lista que ve quien
    evalúa si el servidor le sirve, antes de abrir la documentación.
    """
    tabla = _texto(RAIZ / "README.md").split("## Herramientas", 1)[1].split("\n## ", 1)[0]

    for nombre in expuestas:
        assert f"`{nombre}`" in tabla, f"el README no nombra {nombre!r}, que el servidor expone"

    # Y en la otra dirección, que es la que se degrada sola: retirar una herramienta la saca
    # del servidor y no del README, y la portada queda ofreciendo algo que no existe. Sólo la
    # primera celda de cada fila, porque la segunda nombra campos del modelo.
    for fila in tabla.splitlines():
        if not fila.startswith("| `"):
            continue
        nombre = fila.split("`", 2)[1]
        assert nombre in expuestas, f"el README ofrece {nombre!r} y el servidor no lo expone"


def test_la_cuenta_de_rutas_de_la_plataforma_es_la_de_la_fixture():
    """La hoja de ruta afirmaba 169 rutas y son otra cosa: 189 menciones de un `.php`, o sea
    102 distintas.

    El número venía de una medición vieja y nadie podía notar que había envejecido, porque
    estaba escrito a mano en la prosa. La fuente está versionada, así que se cuenta.

    Y son dos números, no uno: cuántas veces el JavaScript nombra un `.php` y cuántas rutas
    distintas hay detrás. Confundirlos es lo que hace parecer que la plataforma tiene casi el
    doble de superficie de la que tiene.
    """
    javascript = (RAIZ / "tests" / "fixtures" / "consultaUnificada.html").read_text(
        encoding="utf-8", errors="replace"
    )
    menciones = re.findall(r"[\w./-]+\.php", javascript)
    texto = _estado_y_plan()

    assert f"{len(menciones)} veces" in texto, (
        f"la fixture nombra un .php {len(menciones)} veces y la hoja de ruta dice otra cosa"
    )
    assert f"{len(set(menciones))} rutas distintas" in texto, (
        f"son {len(set(menciones))} rutas distintas y la hoja de ruta dice otra cosa"
    )


def test_las_notas_de_la_version_salen_del_changelog_y_no_de_la_plantilla_de_github():
    """`--generate-notes` imprime "What's Changed" y "by X in Y", en inglés y sin opción.

    Es la plantilla fija de GitHub, y en un proyecto cuyo idioma es el español de Chile deja la
    página más visible de la publicación en otro idioma que todo lo demás. Las notas se arman
    desde el tramo del CHANGELOG que corresponde a la etiqueta.

    El guardia mira las dos cosas: que no se vuelva a la plantilla, y que se siga pasando el
    archivo. Poner sólo lo primero dejaría pasar una release con el cuerpo vacío.
    """
    flujo = _texto(RAIZ / ".github" / "workflows" / "publicar.yml")
    # Se miran las líneas de comando y no el archivo entero: el comentario que explica por qué
    # se dejó de usar la plantilla nombra la bandera, y hacía fallar al guardia contra el texto
    # que documenta la decisión.
    ordenes = "\n".join(linea for linea in flujo.splitlines() if not linea.lstrip().startswith("#"))
    assert "--generate-notes" not in ordenes, (
        "el flujo de publicación volvió a la plantilla de GitHub, que es fija y viene en inglés"
    )
    assert "--notes-file" in flujo, "la publicación tiene que pasar las notas armadas"
    assert "CHANGELOG.md" in flujo, "las notas salen del CHANGELOG, que es la fuente única"
    # Cada entrada generada viene como "* título by @autor in <enlace>". Traducir sólo los dos
    # encabezados dejaba en inglés la mayor parte del texto, que es justo lo que se quería
    # evitar: una página de publicación mezclando idiomas.
    for trozo in ("por @", "en /g"):
        assert trozo in flujo, (
            "el flujo no traduce las atribuciones `by @autor in`, que son la mayor parte de "
            "las notas generadas"
        )


def test_la_instalacion_documentada_apunta_a_la_rama_publicada():
    """Sin referencia, `uvx --from git+...` toma la rama principal.

    O sea la instalación que la documentación mostraba hacía correr cambios sin publicar, y
    quien la seguía no tenía forma de saberlo: no hay nada en la salida que distinga una
    versión publicada de la rama principal. En una herramienta que se usa para computar plazos,
    eso es exactamente al revés de lo que conviene.

    `stable` la mueve el flujo de publicación, y sólo después de que la versión se creó bien.
    Este guardia mira las dos mitades: que los ejemplos la usen y que el flujo la mueva. Con
    sólo la primera, la documentación recomendaría instalar una rama que nadie actualiza.
    """
    for archivo in ("README.md", "docs/instalacion.md"):
        texto = _texto(RAIZ / archivo)
        # Los botones de un clic esconden su configuración: el de VS Code va en porcentajes y
        # el de Cursor en base64. Mirar sólo el texto plano dejaba el guardia verde mientras un
        # botón seguía instalando la rama principal, que es lo que este cambio existe para
        # evitar. Se decodifica todo antes de buscar.
        for codificada in re.findall(r"config=([A-Za-z0-9+/=%]+)", texto):
            crudo = urllib.parse.unquote(codificada)
            texto += " " + crudo
            with contextlib.suppress(Exception):
                texto += " " + base64.b64decode(crudo + "===").decode("utf-8")

        ejemplos = re.findall(
            r"git\+https://github\.com/notluquis/mcp-pjud-cl([^\s\"',)\]]*)", texto
        )
        assert ejemplos, f"{archivo} ya no muestra cómo instalar"
        sin_referencia = [e for e in ejemplos if not e.startswith("@")]
        assert not sin_referencia, (
            f"{archivo} muestra una instalación sin referencia, que toma la rama principal y "
            "hace correr cambios sin publicar. Ojo con los botones de un clic: esconden su "
            "configuración codificada"
        )

    flujo = _texto(RAIZ / ".github" / "workflows" / "publicar.yml")
    assert "refs/heads/stable" in flujo, (
        "la documentación recomienda instalar `stable` y el flujo de publicación no la mueve: "
        "quedaría clavada en la versión con que se creó"
    )


def test_la_version_de_python_que_piden_las_guias_es_la_que_exige_el_paquete():
    """Subir el piso de Python sin tocar las guías deja a alguien instalando y fallando.

    `uv` respeta `requires-python`, así que el error llega, pero llega como un problema de
    resolución de dependencias en vez de "esta guía te pidió una versión que no sirve".
    """
    exigida = tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["requires-python"]
    numero = re.search(r"(\d+\.\d+)", exigida)
    assert numero, f"no se pudo leer la versión de `requires-python`: {exigida!r}"

    for archivo in ("README.md", "docs/instalacion.md"):
        texto = _texto(RAIZ / archivo)
        if "Python" not in texto:
            continue
        assert f"Python {numero.group(1)}" in texto, (
            f"{archivo} no pide Python {numero.group(1)}, que es lo que el paquete exige"
        )


def test_la_variable_de_entorno_documentada_es_la_que_el_servidor_lee():
    """Si se renombra, el servidor no arranca y la guía sigue diciendo el nombre viejo.

    Y el modo de falla es de los que confunden: el error dice que falta la variable, la persona
    la tiene puesta con el nombre que leyó, y no hay nada que la haga sospechar de la guía.
    """
    servidor = _texto(RAIZ / "src" / "mcp_pjud" / "server.py")
    nombre = re.search(r'os\.environ\.get\(\s*"([A-Z_]+)"', servidor)
    assert nombre, "el servidor ya no lee su contacto de una variable de entorno"

    paginas = [RAIZ / "README.md", RAIZ / "docs" / "instalacion.md"]
    for pagina in paginas:
        assert nombre.group(1) in _texto(pagina), (
            f"{pagina.name} no nombra {nombre.group(1)}, que es la variable que el servidor lee"
        )


def test_nadie_vuelve_a_afirmar_que_cobranza_no_nombra_receptores():
    """La afirmación falsa vivía en CINCO lugares y el primer arreglo tocó dos.

    Decía que `historiaCob` nunca dice "Actuación Receptor". Lo dice tres veces, escrito
    `Actuacion - Receptor`. Estaba en el mensaje de error, en `ecosistema`, en `roadmap`, en
    `herramientas` y en el comentario de `COMPETENCIAS`, o sea en todo lo que alguien podría
    leer para entender por qué se rechaza cobranza.

    Se barre la prosa Y el código, porque el peor de los cinco era el mensaje de error: es lo
    que un modelo le relata a un abogado.
    """
    filas = parse_historia(
        _texto(RAIZ / "tests" / "fixtures" / "detalle_cobranza.html"), competencia="cobranza"
    )
    nombradas = [a.tramite for a in filas if "receptor" in a.tramite.lower()]
    assert nombradas, "la fixture de cobranza dejó de nombrar receptores en su Historia"

    # La cifra está escrita con letras en seis copias, y una sola que cambie contradice a la
    # fixture. Se compara contra lo que la fixture trae de verdad, que es la fuente.
    _EN_LETRAS = {1: "una", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis"}
    cuantas = _EN_LETRAS[len(nombradas)]

    def legible(f: Path) -> str:
        """El texto tal como lo LEE alguien, no como está escrito en el archivo.

        En `client.py` el mensaje se arma con literales adyacentes, así que en el fuente
        aparece `tres "` y `"filas` y la frase nunca está entera. Se juntan con `ast`, que es
        lo que hace el intérprete: si no, el guardia mira una cadena que nadie va a leer.
        """
        crudo = _texto(f)
        if f.suffix != ".py":
            return " ".join(crudo.split())
        # Las dos cosas: los literales unidos por `ast`, para las cadenas partidas, MÁS el
        # fuente crudo, porque los comentarios `#:` de `COMPETENCIAS` también afirman la cifra
        # y `ast` no los ve. Mirar sólo los literales dejaba esa copia sin guardia.
        textos = [n.value for n in ast.walk(ast.parse(crudo)) if isinstance(n, ast.Constant)]
        unidos = " ".join(" ".join(str(t).split()) for t in textos if isinstance(t, str))
        return f"{unidos} {' '.join(crudo.split())}"

    copias = {f.name: legible(f) for f in [*PROSA, *(RAIZ / "src" / "mcp_pjud").glob("*.py")]}
    # La cifra puede ir antes o después de la palabra: el registro escribe "los nombra tres
    # veces", con el sujeto adelante, y el patrón que sólo miraba hacia la derecha lo perdía.
    # Sólo palabras de cantidad, no cualquier palabra antes de "filas": con `\w+` el guardia
    # se llevaba el "de" de "no por falta de filas" y reportaba "qué" como si fuera una cifra.
    NUM = r"(?:una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|\d+)"
    cerca = (
        rf"(?:[Rr]eceptor\w*[^.]{{0,80}}?({NUM}) (?:filas|veces)"
        rf"|({NUM}) (?:filas|veces)[^.]{{0,80}}?[Rr]eceptor)"
    )
    mal = {
        nombre: sorted({g for par in m for g in par if g})
        for nombre, texto in copias.items()
        if (m := re.findall(cerca, texto)) and any(g and g != cuantas for par in m for g in par)
    }
    assert not mal, (
        f"estas copias dicen otra cantidad de filas con receptor que las {cuantas} que trae "
        f"la fixture: {mal}"
    )

    fuentes = [*PROSA, *(RAIZ / "src" / "mcp_pjud").glob("*.py")]
    # Dos formas de decir lo mismo, y la segunda se coló en la misma página que la corregía:
    # afirmar que nunca las nombra, y afirmar que leerla daría una lista VACÍA. La lista sería
    # parcial, que es la diferencia entera.
    contradicciones = (
        r"nunca [\"']?Actuaci[oó]n Receptor",
        r"lista vac[ií]a que la Historia produc",
        r"devolver la lista vac[ií]a[^.]{0,40}cobranza",
    )
    culpables = {
        f.name
        for f in fuentes
        if any(re.search(p, " ".join(_texto(f).split())) for p in contradicciones)
    }
    assert not culpables, (
        f"{sorted(culpables)} sigue afirmando que la Historia de cobranza nunca nombra "
        f"receptores, y la nombra {len(nombradas)} veces: {sorted(set(nombradas))}. Leerla de "
        "ahí daría una lista parcial, no una vacía."
    )


def test_la_comparacion_cuenta_las_herramientas_que_la_pagina_lista():
    """La cifra se escribió a mano y quedó vieja al agregar la quinta.

    Es la clase de dato que envejece sin que nadie lo mire: agregar una sección es lo natural,
    y actualizar una frase tres pantallas más abajo no. Sale de los encabezados de la propia
    sección, así que la siguiente que se agregue entra sola.
    """
    _EN_PALABRAS = {3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho"}
    pagina = _texto(RAIZ / "docs" / "ecosistema.md")
    seccion = pagina.split("## Herramientas chilenas que tocan lo mismo")[1].split("\n## ")[0]
    cuantas = len(re.findall(r"^### ", seccion, re.M))
    assert cuantas >= 3, "la sección de herramientas chilenas se quedó sin entradas"
    assert f"Ninguna de las {_EN_PALABRAS[cuantas]} lo hace" in pagina, (
        f"la página lista {cuantas} herramientas chilenas y la comparación dice otra cifra"
    )


#: Lo que Magnar declara en su material público, revisado el 21 de agosto de 2026. Vive acá
#: porque es una fuente externa que nada del repositorio puede derivar, y el guardia lo que sí
#: puede es exigir que las menciones de la página no se separen entre sí.
MAGNAR_PAGINAS = 10_000
MAGNAR_ANIO = 2025
MAGNAR_PAISES = ("Perú", "Ecuador", "Costa Rica", "Colombia", "Uruguay")

#: Lo que declara hacer, con la frase que lo identifica en cada fila de la tabla. Es lo que
#: sostiene la comparación publicada: si una capacidad cambia y la fila queda igual, quien
#: lea la página para elegir está comparando contra algo que ya no es.
#: El valor COMPLETO de cada fila, no un fragmento: proteger "control de cambios en Word"
#: dejaba borrar "Resúmenes de sentencias" y "tablas comparativas" de la misma celda sin que
#: nada fallara, y ahí la comparación publicada ya no es la que se revisó.
MAGNAR_CAPACIDADES = {
    "Qué declara buscar": (
        '"normativa y jurisprudencia oficial de tu país, con citas verificables y acceso '
        'directo a cada fuente"'
    ),
    "Base propia": "Un banco de fallos en `app.magnar.ai/cl/juris`",
    "Qué genera": (
        "Resúmenes de sentencias, tablas comparativas, ediciones con control de cambios en Word"
    ),
    "Escala que declara": "Expedientes de hasta 10.000 páginas",
    "Qué NO publica": (
        "Ninguna mención de la Oficina Judicial Virtual, de consulta de causas ni de "
        "cómputo de plazos"
    ),
}
#: Con su estado, no sólo el nombre: borrar el "en curso" de la ISO 42001 sin quitar el
#: nombre cambia una afirmación verificable y el guardia no lo veía.
MAGNAR_CERTIFICACIONES = (
    "ISO 27001 obtenida",
    "SOC 2 Type 2 obtenida",
    "RGPD cumple",
    "ISO 42001 en curso",
)


def test_lo_que_magnar_declara_se_cita_igual_en_toda_la_pagina():
    """La cifra de las páginas aparece dos veces y podían separarse.

    Es una afirmación de un tercero, así que no se deriva de nada: lo que sí se puede impedir
    es que una mención se actualice y la otra quede vieja, que es lo mismo que se persigue con
    las cifras propias. Y que las certificaciones se citen completas, porque media lista dice
    algo distinto de la lista entera.
    """
    seccion = _texto(RAIZ / "docs" / "ecosistema.md").split("### Magnar")[1].split("\n### ")[0]
    cifra = miles(MAGNAR_PAGINAS)
    veces = seccion.count(cifra)
    assert veces >= 2, (
        f"la sección de Magnar cita {cifra} páginas {veces} vez/veces, y las menciones que "
        "tenía eran dos: si se quitó una, hay que quitar este guardia con ella"
    )
    faltan = [c for c in MAGNAR_CERTIFICACIONES if c not in seccion]
    assert not faltan, f"la sección dejó de citar {faltan}, que es parte de lo que declara"

    # El año y los países son igual de verificables y cambian igual de fácil: es la
    # comparación publicada, y quien la lea para elegir se merece que esté al día.
    assert f"de {MAGNAR_ANIO}" in seccion, (
        f"la sección dejó de decir que Magnar es de {MAGNAR_ANIO}"
    )
    sin_pais = [p for p in MAGNAR_PAISES if p not in seccion]
    assert not sin_pais, f"la sección dejó de nombrar {sin_pais} entre los países donde opera"
    # La lista se EXTRAE de la frase y se compara entera, en vez de rechazar unos pocos países
    # elegidos a mano: enumerar los que no valen es la misma trampa que enumerar formatos, y
    # dejaba pasar cualquiera que no se me hubiera ocurrido.
    m = re.search(r"ya opera en ([^.]+)\.", " ".join(seccion.split()))
    assert m, "la sección dejó de decir en qué países opera"
    publicados = tuple(
        pais.strip() for pais in re.split(r",\s*|\s+y\s+", m.group(1)) if pais.strip()
    )
    assert publicados == MAGNAR_PAISES, (
        f"la sección publica {publicados} y la fuente revisada declara {MAGNAR_PAISES}: si "
        "Magnar creció, hay que volver a mirar lo que publica en vez de agregarlo suelto"
    )

    # Y las capacidades, que son lo que sostiene la comparación.
    # Se compara el valor COMPLETO de cada fila contra la celda que la página publica, no un
    # fragmento contra la página entera: con el fragmento se podía borrar media celda.
    plana = " ".join(seccion.split())
    mal = {}
    for fila, esperado in MAGNAR_CAPACIDADES.items():
        m = re.search(rf"\| {re.escape(fila)} \| ([^|]+) \|", plana)
        if m is None:
            mal[fila] = "la fila desapareció"
        elif m.group(1).strip() != " ".join(esperado.split()):
            mal[fila] = m.group(1).strip()
    assert not mal, (
        f"estas filas no dicen lo que se revisó: {mal}. La comparación publicada se separó "
        "de la fuente."
    )


def test_lo_comercial_se_declara_como_publicado_y_no_como_medido():
    """De un producto cerrado sólo se sabe lo que publica, y la página tiene que decirlo.

    Es la lección de siempre puesta como guardia: "no cubre X" sobre un producto que no se
    contrató sólo puede querer decir "no lo publica". Sin esa salvedad, la página compara una
    medición contra un folleto y las presenta al mismo nivel.
    """
    pagina = " ".join(_texto(RAIZ / "docs" / "ecosistema.md").split())
    assert "sólo se puede afirmar lo que publican" in pagina, (
        "`ecosistema.md` dejó de acotar qué se sabe de los productos comerciales"
    )
    assert "no lo publica" in pagina, (
        "`ecosistema.md` dejó de decir que un 'no cubre X' sobre un producto cerrado significa "
        "que no lo publica, no que no lo haga"
    )


def test_la_licencia_dice_lo_mismo_en_todas_partes():
    """Tres archivos declaran la licencia y ninguno leía a los otros.

    En un proyecto cuya licencia prohíbe distribuir y modificar, que dos archivos declaren
    cosas distintas no es un detalle de metadatos: es la parte que alguien lee antes de decidir
    qué puede hacer con esto.
    """
    declarada = tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["license"]
    assert f"license: {declarada}" in _texto(RAIZ / "CITATION.cff"), (
        f"CITATION.cff no declara {declarada!r}, que es la licencia del paquete"
    )


def test_la_revision_del_protocolo_que_se_nombra_es_la_del_sdk():
    """La revisión del protocolo se nombra en el código y en la referencia, y va a cambiar.

    El SDK la expone, así que escribirla a mano es aceptar que quede vieja: subir la
    dependencia dejaría al proyecto diciendo que habla una revisión que ya no es, en la página
    que alguien lee para saber si su cliente es compatible.
    """
    from mcp.types import LATEST_PROTOCOL_VERSION

    servidor = _texto(RAIZ / "src" / "mcp_pjud" / "server.py")
    assert LATEST_PROTOCOL_VERSION in servidor, (
        f"el servidor nombra otra revisión del protocolo; el SDK trae {LATEST_PROTOCOL_VERSION}"
    )
    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    assert LATEST_PROTOCOL_VERSION in referencia, (
        f"la referencia nombra otra revisión; el SDK trae {LATEST_PROTOCOL_VERSION}"
    )


def test_la_cuenta_de_buscadores_verificados_es_la_del_codigo():
    """Registrar un buscador nuevo y no tocar la prosa deja la página contando de menos.

    Y en esta herramienta contar de menos importa: quien lee "tres de diez" decide si le sirve
    o si tiene que buscar la sentencia por otro lado.
    """
    from mcp_pjud.juris import BUSCADORES

    numeros = {
        1: "uno",
        2: "dos",
        3: "tres",
        4: "cuatro",
        5: "cinco",
        6: "seis",
        7: "siete",
        8: "ocho",
        9: "nueve",
        10: "diez",
    }
    esperado = numeros[len(BUSCADORES)]
    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    dicho = re.search(r"Están verificados (\w+) de los \w+ buscadores", referencia)
    assert dicho, "la referencia ya no dice cuántos buscadores están verificados"
    assert dicho.group(1) == esperado, (
        f"la referencia dice {dicho.group(1)} buscadores verificados y el código registra "
        f"{len(BUSCADORES)}"
    )
    for nombre in BUSCADORES:
        assert f"**{nombre}**" in referencia, f"la referencia no nombra el buscador {nombre!r}"


def test_el_esquema_dice_donde_el_rol_lleva_libro(expuestas):
    """La referencia lo explicaba y el esquema seguía diciendo sólo "Letra del rol".

    Lo que el modelo lee es el esquema, no esta página. Con la descripción vieja mandaba una
    letra o un valor vacío en apelaciones, donde el número de rol se repite entre libros, y la
    desambiguación fallaba con un error que parece de la plataforma.

    Se deriva de `parser.COMPETENCIAS` para que agregar una competencia con libro no dependa de
    que alguien se acuerde de dos lugares.
    """
    con_libro = [n for n in MODULOS if COMPETENCIAS[n].rol_con_libro]
    assert con_libro, "si ninguna lleva libro, este guardia hay que retirarlo"

    descripciones = [
        p.get("description", "")
        for h in expuestas.values()
        for nombre, p in (h.input_schema or {}).get("properties", {}).items()
        if nombre == "tipo"
    ]
    assert descripciones, "ninguna herramienta declara el parámetro `tipo`"
    for descripcion in descripciones:
        for competencia in con_libro:
            assert competencia in descripcion, (
                f"el esquema del parámetro `tipo` no dice que en {competencia} va el libro"
            )


def test_las_entradas_del_registro_de_cambios_son_breves():
    """El registro dice QUÉ cambió, no cómo se encontró.

    Se degradó solo: las entradas pasaron a ser párrafos, una versión llegó a 333 líneas con 67
    viñetas, y varias repetían lo que la sección de al lado ya decía. Un dato repetido es un
    dato que va a quedar viejo, y un registro que hay que leer entero deja de servir para lo
    único que sirve: decidir si conviene actualizar.

    El límite es mecánico a propósito. No mide calidad, mide que nadie vuelva a escribir un
    ensayo donde va una línea: lo que no cabe se cuenta en el PR, que es donde se busca.
    """
    LARGO_MAXIMO = 4

    lineas = _texto(RAIZ / "CHANGELOG.md").splitlines()
    largas: dict[str, int] = {}
    actual: list[str] = []

    def cerrar() -> None:
        if len(actual) > LARGO_MAXIMO:
            largas[actual[0].strip()[:60]] = len(actual)

    for linea in lineas:
        if linea.startswith("- "):
            cerrar()
            actual = [linea]
        elif actual and linea.startswith("  "):
            actual.append(linea)
        else:
            cerrar()
            actual = []
    cerrar()

    assert not largas, (
        f"Entradas del registro de cambios más largas de {LARGO_MAXIMO} líneas: {largas}. "
        "Lo que no cabe va en el pull request."
    )


def test_las_entradas_del_registro_de_cambios_no_pasan_de_dos_frases():
    """El de arriba cuenta líneas, así que atrapa el desborde y no el contenido.

    Es su límite conocido, está escrito en `AGENTS.md`, y aun así se coló tres veces: una
    viñeta que cabe justo en cuatro líneas y dedica dos frases al mecanismo pasa sin
    problema. La tercera la encontró una revisión, no el guardia.

    Contar frases lo cierra. Antes de escribirlo se midió contra el registro entero, porque
    un guardia con falso positivo enseña a ignorarlo, que es peor que no tenerlo: de las 79
    viñetas, 58 tienen una frase y 21 tienen dos.

    Los dos falsos positivos que aparecieron midiendo, y que por eso se descuentan: `art. 9
    inc. 3 de la Ley 20.886`, que obliga a descontar la abreviatura también cuando la sigue un
    número, y la referencia final `([#11], [#21])`, que va después del punto y no es una frase.
    """
    FRASES_MAXIMAS = 2

    def contar(cuerpo: str) -> int:
        # Fuera lo que trae puntos y no termina frase: código, enlaces, versiones, montos y
        # abreviaturas legales, que acá son frecuentes y todas llevan punto.
        limpio = re.sub(r"`[^`]*`", "X", cuerpo)
        limpio = re.sub(r"\[[^\]]*\]\([^)]*\)", "X", limpio)
        limpio = re.sub(r"\d[\d.]*\d", "N", limpio)
        limpio = re.sub(r"\b[A-Za-zÁÉÍÓÚáéíóúñÑ]{1,4}\.\s*(?=[a-záéíóúñ0-9])", "X ", limpio)
        return len(re.findall(r"[.!?](?=\s|$)", limpio.strip()))

    actual: list[str] = []
    viñetas: list[str] = []
    for linea in _texto(RAIZ / "CHANGELOG.md").splitlines():
        if linea.startswith("- "):
            if actual:
                viñetas.append(" ".join(actual))
            actual = [linea[2:]]
        elif actual and linea.startswith("  "):
            actual.append(linea.strip())
        elif actual and not linea.strip():
            # Una línea en blanco NO cierra la viñeta: puede venir un segundo párrafo indentado.
            # Cerrarla acá era como se colaban las entradas de dos párrafos, que sumaban cuatro
            # frases y pasaban como dos.
            actual.append("")
        else:
            if actual:
                viñetas.append(" ".join(actual))
            actual = []
    if actual:
        viñetas.append(" ".join(actual))

    assert len(viñetas) > 50, "el recolector dejó de reconocer las viñetas del registro"

    largas = {v[:70]: contar(v) for v in viñetas if contar(v) > FRASES_MAXIMAS}
    assert not largas, (
        f"Entradas del registro con más de {FRASES_MAXIMAS} frases: {largas}. El registro "
        "dice QUÉ cambió; el mecanismo y el diagnóstico van en el commit y en el PR."
    )


def test_la_ultima_version_publicada_no_gana_entradas_despues_de_publicarse():
    """Una entrada nueva va a `[No publicado]`, no a la versión de arriba.

    Pasó: publicar consiste en insertar la versión nueva justo debajo de `[No publicado]`, así
    que el cambio siguiente ancló su viñeta en el texto de al lado y quedó archivada bajo una
    versión **ya etiquetada**. El registro afirmaba que 0.5.1 traía un campo que se agregó
    después, mientras la publicación en GitHub, generada al etiquetar, decía la verdad.

    Se cuentan viñetas y no se compara el texto: corregir la redacción de una versión
    publicada es legítimo, agregarle contenido no.

    Sólo se mira la última publicada. Las anteriores cambiaron de tamaño en la reescritura del
    registro, que fue deliberada, y guardarlas obligaría a una lista de excepciones escrita a
    mano que envejece sola.
    """
    texto = _texto(RAIZ / "CHANGELOG.md")

    def viñetas_por_version(contenido: str) -> dict[str, int]:
        cuenta = {}
        for tramo in re.split(r"^## (?=\[)", contenido, flags=re.M)[1:]:
            m = re.match(r"\[(\d+\.\d+\.\d+)\]", tramo)
            if m:
                cuenta[m.group(1)] = len([x for x in tramo.splitlines() if x.startswith("- ")])
        return cuenta

    ahora = viñetas_por_version(texto)
    assert ahora, "el registro no declara ninguna versión publicada"
    ultima = max(ahora, key=lambda v: tuple(int(x) for x in v.split(".")))

    # S603: el argumento no es entrada externa, es una versión que este mismo archivo acaba de
    # leer del registro y que ya calzó contra \d+\.\d+\.\d+.
    publicado = subprocess.run(  # noqa: S603
        ["git", "show", f"v{ultima}:CHANGELOG.md"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    if publicado.returncode != 0:
        # La etiqueta se crea DESPUÉS de mezclar el cambio que sube la versión, así que en el
        # pull request que la publica todavía no existe. No hay nada que comparar y no es un
        # fallo: al pasar por `main` ya existe y el guardia muerde.
        pytest.skip(f"la etiqueta v{ultima} todavía no existe")

    antes = viñetas_por_version(publicado.stdout).get(ultima)
    assert antes is not None, f"la etiqueta v{ultima} no traía su propia sección en el registro"
    assert ahora[ultima] <= antes, (
        f"la versión {ultima} tenía {antes} entradas al publicarse y ahora tiene "
        f"{ahora[ultima]}. Lo nuevo va en `[No publicado]`: la publicación en GitHub se generó "
        "al etiquetar y ya no dice lo mismo que el archivo."
    )


def test_cada_version_del_registro_enlaza_a_su_publicacion():
    """Publicar consiste en insertar un encabezado, y las referencias del final se olvidan.

    Cuando pasa, el encabezado de la versión nueva deja de enlazar a su release y `[No
    publicado]` sigue comparando contra la anterior, o sea muestra como pendiente todo lo que
    esa versión ya publicó. Las dos cosas se derivan del propio archivo.
    """
    registro = _registro()
    versiones = _versiones_del_registro(registro)
    assert versiones, "el registro dejó de tener versiones"

    # Que la referencia exista no basta: apuntando a la etiqueta anterior el encabezado enlaza
    # a la release equivocada y el archivo se ve correcto. Ya pasó con `[0.1.0]`.
    referencias = dict(re.findall(r"^\[(\d+\.\d+\.\d+)\]: (\S+)$", registro, re.M))
    # 0.1.0 es anterior a que se etiquetara nada: su `v0.1.0` nunca existió, así que enlaza al
    # commit a propósito. Es una excepción histórica y cerrada, no un patrón que se pueda repetir.
    mal = {
        v: referencias.get(v)
        for v in versiones
        if v != "0.1.0" and not (referencias.get(v) or "").endswith(f"/releases/tag/v{v}")
    }
    assert not mal, (
        f"estas versiones no enlazan a su propia publicación: {mal}. Al publicar hay que "
        "agregar `[x.y.z]: .../releases/tag/vx.y.z` al final del archivo."
    )

    # La base sale del propio archivo y no se escribe otra vez: ya son cuatro copias y por eso
    # `docs/_bloques.py` centraliza la del bloque de configuración.
    base = next(iter(referencias.values())).split("/releases/")[0]
    ultima = versiones[0]
    esperado = f"[No publicado]: {base}/compare/v{ultima}...HEAD"
    assert esperado in registro, (
        f"`[No publicado]` no compara contra la última versión publicada ({ultima}), así que "
        "muestra como pendiente lo que esa versión ya publicó."
    )


def test_ninguna_version_del_registro_repite_una_seccion():
    """Dos `### Agregado` bajo la misma versión rompen la página de la publicación.

    El flujo de publicación copia el tramo entero entre un `## [versión]` y el siguiente, así
    que la release muestra el encabezado repetido. Y como publicar consiste en insertar la
    versión nueva justo debajo de `[No publicado]`, el error se cuela sin que nadie lo mire:
    ya pasó, con las dos primeras líneas visibles siendo un archivo de tests y una dependencia
    de desarrollo.
    """
    texto = _texto(RAIZ / "CHANGELOG.md")
    versiones = re.split(r"^## (?=\[)", texto, flags=re.M)[1:]

    repetidas = {}
    for tramo in versiones:
        nombre = tramo.splitlines()[0].strip()
        secciones = re.findall(r"^### (.+)$", tramo, re.M)
        duplicadas = {s for s in secciones if secciones.count(s) > 1}
        if duplicadas:
            repetidas[nombre] = sorted(duplicadas)

    assert not repetidas, (
        f"Versiones del registro con una sección repetida: {repetidas}. La publicación copia "
        "el tramo entero, así que el encabezado saldría dos veces en la página."
    )


#: Lo que el contrato de cada herramienta NO puede perder, porque sin eso el modelo informa
#: algo que no puede afirmar. Cada entrada nombra un aviso, no una redacción: se busca el
#: término, así que reescribir el párrafo alrededor no rompe nada y borrarlo sí.
AVISOS_QUE_NO_SE_PUEDEN_PERDER = {
    "obtener_actuaciones_receptor": (
        # La razón de existir del proyecto, y su contrato se podía vaciar entero sin que nada
        # se pusiera en rojo: `obtener_detalle_causa` tenía guardia y ésta no.
        "fecha_diligencia",
        "fecha_registro",
        "plazos",
        "ebook",
    ),
    "buscar_jurisprudencia": ("ocultas", "no_entregadas", "subconjunto"),
    "obtener_documento": ("escaneo", "OCR", "no es un PDF"),
    # `fecha_diligencia` es el aviso que más importa de los cuatro: sin él, un modelo puede
    # tomar la hora del aparato como la fecha que corre el plazo, y ésta es una TERCERA
    # fuente para contrastar, no un reemplazo. Faltaba justo ése.
    "obtener_georreferencia": (
        "precision_metros",
        "hora",
        "existe",
        "fecha_diligencia",
        "NO reemplaza",
    ),
}


@pytest.mark.parametrize("nombre", sorted(AVISOS_QUE_NO_SE_PUEDEN_PERDER))
def test_el_contrato_de_cada_herramienta_conserva_sus_avisos(expuestas, nombre):
    """Lo que el modelo lee antes de llamar es lo único que le dice qué NO puede afirmar.

    `obtener_detalle_causa` ya tenía este guardia. Las demás no, y eso incluía a
    `obtener_actuaciones_receptor`, que `AGENTS.md` llama la razón de existir del proyecto:
    su descripción entera se podía reemplazar por "Devuelve una lista" y la suite seguía
    verde. Sin ese contrato, un modelo devuelve `fecha_registro` creyendo que corre plazos.
    """
    herramienta = expuestas.get(nombre)
    assert herramienta is not None, f"{nombre} ya no está expuesta"
    contrato = (herramienta.description or "").lower()
    faltan = [a for a in AVISOS_QUE_NO_SE_PUEDEN_PERDER[nombre] if a.lower() not in contrato]
    assert not faltan, (
        f"el contrato de {nombre} dejó de mencionar {faltan}, y sin eso el modelo informa "
        "un dato que no puede afirmar"
    )


def test_el_detalle_combinado_advierte_lo_que_cuesta_un_plazo(expuestas):
    """Su contrato reúne lo que antes advertían tres herramientas, y no puede perderlo.

    Tres cosas que un modelo tiene que saber antes de informar: que `fecha_diligencia` viene
    en nulo salvo en dos competencias, que las notificaciones incluyen las NO practicadas, y
    que los litigantes traen datos personales de terceros. Al juntar las lecturas, cada aviso
    que no se copie desaparece sin que nada falle.
    """
    herramienta = expuestas.get("obtener_detalle_causa")
    assert herramienta is not None, "la lectura combinada del detalle ya no está expuesta"

    contrato = herramienta.description or ""
    for exigido in (
        "fecha_diligencia",
        "no practicadas",
        "estado",
        "personales",
        # Este se perdió de verdad: lo llevaba `obtener_liquidaciones_causa`, y al retirarla
        # el aviso se fue con ella. Sumar las liquidaciones informa una deuda varias veces
        # más grande que la real.
        "NO se suman",
        # El título decía "detalle completo" y el contrato no desmentía nada. Un modelo que
        # lo lee así informa "la causa no tiene escritos" cuando lo que pasa es que este
        # servidor no sabe leer ese panel.
        "NO es el expediente completo",
    ):
        assert exigido.lower() in contrato.lower(), (
            f"el contrato de la lectura combinada no menciona {exigido!r}, y sin eso el "
            "modelo informa un dato que no puede afirmar"
        )
