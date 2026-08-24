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
import json
import re
import subprocess
import tomllib
import urllib.parse
from pathlib import Path

import pytest
import yaml
from lxml import html
from mcp.client import Client

from mcp_pjud.client import (
    ANEXOS,
    ANEXOS_MEDIDOS_SIN_EXPONER,
    AUDIO_CAMPO,
    AUDIO_RUTA,
    CORTES_MEDIDAS,
    CUELGUES_DE_COMBOS_SIN_MEDIR,
    DOCUMENTOS,
    DOCUMENTOS_EJECUTADAS,
    EL_ROL_NO_BASTA,
    INTERVALO_MINIMO,
    MODULOS,
    RAFAGA_MAXIMA,
    SEGUNDOS_BUSQUEDA_MEDIDOS,
    SEGUNDOS_BUSQUEDA_PEOR_MEDIDO,
    SEGUNDOS_PAGINA_MEDIDOS,
)
from mcp_pjud.juris import (
    BUSCADORES,
    FECHA_MEDICION,
    FILAS_MAXIMAS,
    IDENTIFICADORES_MEDIDOS,
    INDEXADAS_MEDIDAS,
    VISIBLES_MEDIDAS,
    miles,
)
from mcp_pjud.parser import (
    _PANELES_ANEXO,
    COMPETENCIAS,
    SEGUNDOS_DECLARADOS_POR_LA_REFERENCIA,
    SIN_FILAS_OBSERVADAS,
    CausaEncontrada,
    Competencia,
    DetalleCausa,
    Panel,
    parse_historia,
)
from mcp_pjud.server import _CON_DETALLE, TOPE_DEL_CLIENTE, _sin_prosa, mcp

from .conftest import CARACTERES_DE_UNA_SENTENCIA, raiz_del_repo

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

RAIZ = raiz_del_repo()
HERRAMIENTAS = (RAIZ / "docs" / "herramientas.md").read_text(encoding="utf-8")

#: Todo lo que un lector puede tomar por cierto. Se recorre entero en vez de mirar una página,
#: porque el dato viejo puede quedar en cualquiera.
PROSA = sorted(
    p
    for p in [*RAIZ.glob("*.md"), *(RAIZ / "docs").glob("*.md"), *(RAIZ / ".github").glob("*.md")]
    if "_build" not in p.parts
)


#: Los números que la prosa escribe con letras. Se comparan contra `len(...)` del código, que
#: es donde vive la cuenta de verdad.
EN_LETRAS = {
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
    11: "once",
    12: "doce",
    13: "trece",
    14: "catorce",
    15: "quince",
    16: "dieciséis",
    17: "diecisiete",
    18: "dieciocho",
    19: "diecinueve",
    20: "veinte",
    21: "veintiuno",
    22: "veintidós",
    23: "veintitrés",
    24: "veinticuatro",
    25: "veinticinco",
    26: "veintiséis",
    27: "veintisiete",
    28: "veintiocho",
}


def _texto(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _legible(f: Path) -> str:
    """El texto de un archivo tal como lo LEE alguien, no como está escrito en el fuente.

    En `client.py` los mensajes se arman con literales adyacentes, así que en el archivo
    aparece `tres "` y `"filas` y la frase nunca está entera. Se juntan con `ast`, que es lo
    que hace el intérprete: si no, el guardia mira una cadena que nadie va a leer.

    Y se devuelven las dos cosas, los literales unidos MÁS el fuente crudo, porque los
    comentarios `#:` de `COMPETENCIAS` también afirman cosas y `ast` no los ve. Mirar sólo los
    literales dejaba esas copias sin guardia.
    """
    crudo = _texto(f)
    if f.suffix != ".py":
        return " ".join(crudo.split())
    textos = [n.value for n in ast.walk(ast.parse(crudo)) if isinstance(n, ast.Constant)]
    unidos = " ".join(" ".join(str(t).split()) for t in textos if isinstance(t, str))
    return f"{unidos} {' '.join(crudo.split())}"


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


@pytest.fixture(scope="module")
def plantillas():
    return {p.name: p for p in asyncio.run(mcp.list_prompts())}


@pytest.fixture(scope="module")
def secciones_de_plantillas():
    """Cada `### \\`nombre\\`` de la sección de plantillas, con su cuerpo.

    Va con `###` y con guiones en el nombre porque así se llaman: el barrido de herramientas
    busca `## \\`nombre_con_guion_bajo\\``, así que las dos secciones no se pisan y ninguna
    plantilla se cuela entre las herramientas que la referencia promete.
    """
    seccion = HERRAMIENTAS.split("\n## Plantillas\n")[1].split("\n## ")[0]
    nombres = re.findall(r"^### `([a-z-]+)`", seccion, re.M)
    cuerpos = re.split(r"^### `[a-z-]+`", seccion, flags=re.M)[1:]
    return dict(zip(nombres, cuerpos, strict=True))


def test_toda_plantilla_del_servidor_esta_documentada(plantillas, secciones_de_plantillas):
    """Y el error contrario: una plantilla que se quitó del servidor y quedó descrita."""
    faltantes = sorted(set(plantillas) - set(secciones_de_plantillas))
    assert not faltantes, f"El servidor expone plantillas sin documentar: {faltantes}"
    inventadas = sorted(set(secciones_de_plantillas) - set(plantillas))
    assert not inventadas, f"La referencia describe plantillas inexistentes: {inventadas}"


def test_todo_argumento_aparece_en_la_seccion_de_su_plantilla(plantillas, secciones_de_plantillas):
    """La tabla de argumentos de cada plantilla dice exactamente los que acepta.

    Las dos direcciones importan por lo mismo que en las herramientas: uno sin documentar deja
    a quien invoca sin saber que existe, y uno documentado de más lo hace escribir un argumento
    que el servidor rechaza.
    """
    for nombre, plantilla in plantillas.items():
        cuerpo = secciones_de_plantillas[nombre]
        declarados = {a.name for a in plantilla.arguments or []}
        documentados = set(re.findall(r"^\s*\|\s*`(\w+)`\s*\|", cuerpo, re.M))
        assert documentados == declarados, (
            f"`{nombre}` acepta {sorted(declarados)} y la referencia tabula {sorted(documentados)}"
        )
        obligatorios = {a.name for a in plantilla.arguments or [] if a.required}
        tabulados = set(re.findall(r"^\s*\|\s*`(\w+)`\s*\|\s*sí\s*\|", cuerpo, re.M))
        assert tabulados == obligatorios, (
            f"`{nombre}` exige {sorted(obligatorios)} y la referencia marca como obligatorios "
            f"{sorted(tabulados)}"
        )


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
    medidas = {r for paneles in ANEXOS.values() for r in paneles} | set(ANEXOS_MEDIDOS_SIN_EXPONER)
    assert f"**{len(rutas - medidas)} de las {len(rutas)} rutas de anexo**" in lista, (
        f"el sitio nombra {len(rutas)} rutas de anexo, {len(rutas & medidas)} están medidas y "
        "la lista dice otra cosa"
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


def test_la_hoja_de_ruta_cuenta_los_paneles_de_anexo_como_el_codigo():
    """El encabezado de la sección contaba tres ofrecidos de siete medidos, y son cuatro de ocho.

    El párrafo de más abajo de esa misma sección ya decía "se ofrecen cuatro", así que la página
    se contradecía consigo misma: la frase en negrita es la que alguien lee al pasar, y era la
    equivocada. Pasó porque el cuarto panel entró con la 0.11.0 y sólo se tocó el párrafo.
    """
    ofrecidas = {r for paneles in ANEXOS.values() for r in paneles}
    medidas = ofrecidas | set(ANEXOS_MEDIDOS_SIN_EXPONER)
    hoja = _texto(RAIZ / "docs" / "roadmap.md")
    dicho = re.search(r"\*\*Anexos: (\w+) paneles ofrecidos de (\w+) medidos\.\*\*", hoja)
    assert dicho, "la hoja de ruta ya no dice cuántos paneles de anexo se ofrecen"
    assert dicho.group(1) == EN_LETRAS[len(ofrecidas)], (
        f"la hoja de ruta ofrece {dicho.group(1)} paneles y `ANEXOS` trae {len(ofrecidas)}"
    )
    assert dicho.group(2) == EN_LETRAS[len(medidas)], (
        f"la hoja de ruta mide {dicho.group(2)} paneles y el código anota {len(medidas)}"
    )


def test_las_cifras_sueltas_de_la_referencia_salen_del_codigo():
    """Tres cuentas que estaban escritas a mano y ningún guardia miraba.

    La peor no era un número: la referencia decía que la columna `Anexo` **no se puede pedir**,
    y `obtener_anexos_escrito` existe desde la 0.10.0. La misma página, veinte líneas más
    arriba, ya explicaba cómo pedirla en la tabla de campos. Una página que se contradice sola
    se lee entera como poco confiable, y la mitad equivocada era la que va en un aviso.
    """
    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    hoja = _texto(RAIZ / "docs" / "roadmap.md")

    js = _texto(RAIZ / "tests" / "fixtures" / "consultaUnificada.html")
    nombradas = set(re.findall(r"/(?:\w+)/modal/(\w*[Aa]nexo\w*\.php)", js))
    ofrecidas = {r for paneles in ANEXOS.values() for r in paneles}
    assert f"nombra {EN_LETRAS[len(nombradas)]} rutas" in referencia, (
        f"el sitio nombra {len(nombradas)} rutas de anexo y la referencia dice otra cosa"
    )
    assert f"se ofrecen {EN_LETRAS[len(ofrecidas)]} paneles" in referencia, (
        f"`ANEXOS` ofrece {len(ofrecidas)} paneles y la referencia dice otra cosa"
    )
    # El aviso decía lo contrario de lo que el servidor hace, y eso no lo atrapa contar. Se
    # busca el bloque por su contenido y no por su posición: contar bloques deja el guardia
    # mirando otro aviso en cuanto alguien agrega uno más arriba.
    # Desde el segundo trozo: el primero es lo que va ANTES del primer aviso, y si esa parte
    # nombrara la columna el guardia se pondría verde mirando texto que no es el aviso.
    aviso = next(
        b for b in referencia.split(":::{warning}")[1:] if "La columna `Anexo`" in b.split(":::")[0]
    ).split(":::")[0]
    assert "obtener_anexos_escrito" in aviso, (
        "el aviso de la columna `Anexo` no nombra la herramienta que la pide"
    )

    sin_filas = EN_LETRAS[len(SIN_FILAS_OBSERVADAS)].capitalize()
    assert f"{sin_filas} paneles se leen con las columnas" in referencia, (
        f"`SIN_FILAS_OBSERVADAS` trae {len(SIN_FILAS_OBSERVADAS)} y la referencia dice otra cosa"
    )

    ejecutadas = EN_LETRAS[len(DOCUMENTOS_EJECUTADAS)]
    civil, total = len(DOCUMENTOS["civil"]), sum(len(r) for r in DOCUMENTOS.values())
    # Normalizado: la frase va envuelta y el salto cae justo en medio, así que atarse al texto
    # crudo pone en rojo un reajuste de línea que no cambia nada.
    verificacion = " ".join(_texto(RAIZ / "docs" / "verificacion.md").split())
    assert f"**{ejecutadas} de las {EN_LETRAS[total]} se han pedido de verdad**" in verificacion, (
        f"se pidieron {len(DOCUMENTOS_EJECUTADAS)} rutas de {total} y la página dice otra cosa"
    )
    assert "_generado/documentos.md" in verificacion, (
        "la tabla de rutas de documento dejó de generarse desde `DOCUMENTOS`"
    )
    assert f"son {EN_LETRAS[civil]} en civil y **{EN_LETRAS[total]}**" in hoja, (
        f"`DOCUMENTOS` trae {civil} rutas en civil y {total} en total, y la hoja dice otra cosa"
    )


def test_la_pagina_de_uso_no_promete_menos_competencias_de_las_que_hay():
    """Decía "sólo cubre causas civiles" con seis buscables y cinco con detalle.

    Está en la sección "Qué NO hace", que es la que alguien lee para decidir si la herramienta
    le sirve. Prometer de menos ahí no es prudente: manda a un abogado de cobranza a buscar por
    otro lado algo que este servidor ya entrega.
    """
    uso = _texto(RAIZ / "docs" / "uso.md")
    con_detalle = {n for n in MODULOS if COMPETENCIAS[n].historia is not None}
    assert f"Las otras {EN_LETRAS[len(MODULOS)]} se buscan" in uso, (
        f"el servidor busca en {len(MODULOS)} competencias y la página de uso dice otra cosa"
    )
    assert f"el detalle se lee en {EN_LETRAS[len(con_detalle)]}" in uso, (
        f"el detalle se lee en {len(con_detalle)} competencias y la página de uso dice otra cosa"
    )
    # Dentro del paréntesis y no en la página entera: `cobranza` y `penal` aparecen sueltos más
    # arriba, así que buscarlos en todo el archivo daba un guardia que no puede fallar.
    listadas = re.search(r"se buscan \(([^)]+)\)", uso)
    assert listadas, "la página de uso ya no enumera las competencias que busca"
    for nombre in MODULOS:
        assert nombre in listadas.group(1), (
            f"la página de uso no nombra la competencia {nombre!r} entre las que busca"
        )


def test_ninguna_pagina_dice_que_sólo_civil_esta_implementada():
    """Fue cierto hasta la 0.4.0 y quedó escrito en tres páginas distintas.

    Es la afirmación que más caro sale de las que envejecieron: manda a quien lee a resolver por
    otro lado algo que este servidor ya entrega. Se barre la prosa entera en vez de arreglar la
    copia que se encontró, porque las tres se escribieron en momentos distintos.
    """
    coladas = []
    for f in PROSA:
        texto = " ".join(_texto(f).split()).lower()
        for frase in ("sólo civil está", "solo civil está", "sólo cubre causas civiles"):
            # El registro de cambios cuenta lo que pasó en su día y ahí la frase es correcta.
            if frase in texto and f.name != "CHANGELOG.md":
                coladas.append(f"{f.relative_to(RAIZ).as_posix()}: {frase!r}")
    assert not coladas, (
        f"{coladas} quedó de cuando civil era la única competencia, y hoy son {len(MODULOS)}"
    )


def test_las_rutas_de_anexo_que_faltan_se_cuentan_solas():
    """Decía doce cuando eran once: cada ruta que se mide baja ese número y nadie volvía acá.

    La resta sale del JavaScript del sitio menos lo medido, igual que en la lista de mapeado sin
    ejecutar, porque escribirla a mano es lo que la dejó vieja. Y la frase importa: es la que
    explica por qué no se piden a ciegas.
    """
    js = _texto(RAIZ / "tests" / "fixtures" / "consultaUnificada.html")
    nombradas = set(re.findall(r"/(?:\w+)/modal/(\w*[Aa]nexo\w*\.php)", js))
    medidas = {r for paneles in ANEXOS.values() for r in paneles} | set(ANEXOS_MEDIDOS_SIN_EXPONER)
    faltan = EN_LETRAS[len(nombradas - medidas)]
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    assert f"Las {faltan} que faltan se rechazan a propósito" in pagina, (
        f"faltan {len(nombradas - medidas)} rutas de anexo por medir y la página dice otra cosa"
    )
    assert f"ninguno de los {faltan} que" in pagina, (
        "la segunda mención de las rutas que faltan quedó con otro número"
    )
    hoja = _texto(RAIZ / "docs" / "roadmap.md")
    assert f"Las {faltan} que faltan siguen sin ejecutarse" in hoja, (
        "la hoja de ruta cuenta otras rutas de anexo pendientes que la página de verificación"
    )


def test_ninguna_pagina_cuenta_las_competencias_por_su_cuenta():
    """Seis se buscan y cinco tienen detalle, y las dos cifras andan sueltas por la prosa.

    Misma forma que el barrido de buscadores: dos cuentas pegadas, las dos legales, y lo que
    discrimina es la frase alrededor. Acá hay una tercera cuenta que no es ninguna de las dos,
    las cinco competencias con rutas de documento, así que la frase que no se puede clasificar
    se salta en vez de contarse mal: un guardia que adivina es peor que uno que no mira.
    """
    buscables = EN_LETRAS[len(MODULOS)]
    con_detalle = EN_LETRAS[len({n for n in MODULOS if COMPETENCIAS[n].historia is not None})]
    malas = []
    for f in [*PROSA, *sorted((RAIZ / "src" / "mcp_pjud").glob("*.py"))]:
        crudo = _legible(f) if f.suffix == ".py" else _sin_lo_ya_publicado(f)
        # Normalizado: "en las cinco competencias\n  con detalle mapeado" viene partido, y el
        # discriminador cae justo del otro lado del salto de línea.
        texto = " ".join(crudo.split())
        for m in re.finditer(r"(?:en|de)(?: las)? (\w+) competencias", texto):
            escrito = m.group(1).lower()
            if escrito not in EN_LETRAS.values():
                continue
            antes, despues = (
                texto[max(0, m.start() - 80) : m.start()],
                texto[m.end() : m.end() + 80],
            )
            detalle = _distancia(r"detalle|historia|panel|litigante", antes, despues)
            busqueda = _distancia(r"busca|búsqueda|por rol|expone|verificad", antes, despues)
            if min(detalle, busqueda) > 60:
                continue
            toca = con_detalle if detalle < busqueda else buscables
            if escrito != toca:
                malas.append(
                    f"{f.relative_to(RAIZ).as_posix()}: dice {escrito!r} donde va {toca!r}"
                )
    # Y la frase que se repite en tres páginas para decir la otra mitad. Va aparte porque no
    # lleva la palabra "competencias" detrás del número, así que el barrido de arriba no la ve.
    for f in PROSA:
        texto = " ".join(_sin_lo_ya_publicado(f).split())
        for m in re.finditer(r"el detalle se lee en (\w+)", texto):
            if m.group(1).lower() in EN_LETRAS.values() and m.group(1).lower() != con_detalle:
                malas.append(
                    f"{f.relative_to(RAIZ).as_posix()}: el detalle se lee en {m.group(1)!r} y "
                    f"son {con_detalle!r}"
                )

    assert not malas, "cuentas de competencias que el código contradice: " + "; ".join(malas)


def test_el_nulo_de_ocultas_esta_avisado_donde_sobrevive_al_corte(expuestas):
    """`ocultas` en nulo llega en seis de los siete buscadores, y leerlo como cero es afirmar
    completitud sin fundamento: justo lo que el proyecto entero existe para no hacer.

    El aviso estaba en la directiva, y la directiva pesaba 3.770 bytes contra un tope de
    corte de 2.048: esta regla caía del otro lado y no llegaba. Ahora la advertencia corta va
    en la directiva, que cabe entera, y el detalle con los nombres en la herramienta que lo
    devuelve.

    La cara negativa importa tanto como la positiva: sin ella, reponer el detalle en la
    directiva la vuelve a llenar y nadie se entera hasta que se corte otra regla.
    """
    from mcp_pjud.server import DIRECTIVA

    con_numero = sorted(n for n, b in BUSCADORES.items() if b.coincidencias_por_consulta)
    assert "`ocultas` en NULO tampoco" in DIRECTIVA, (
        "la directiva dejó de advertir que `ocultas` puede venir en nulo"
    )
    detalle = f"Sólo {', '.join(con_numero)} la trae con número."
    descripcion = expuestas["buscar_jurisprudencia"].description or ""
    assert detalle in descripcion, (
        f"`buscar_jurisprudencia` no nombra {con_numero} como los que traen `ocultas` con número"
    )
    assert detalle not in DIRECTIVA, (
        "el detalle volvió a la directiva, que tiene 2.048 bytes para todo el servidor"
    )


def test_los_paneles_que_nombra_la_hoja_de_ruta_son_los_que_el_codigo_pide():
    """La tabla dice con qué panel se lee cada competencia, y ese nombre es lo que se manda.

    Un nombre mal escrito acá no rompe nada hoy, y por eso envejece tranquilo: la próxima
    persona que mida una competencia nueva copia el de al lado. `movimientoLab` va en singular y
    `movimientosSup` en plural, que es la clase de detalle que nadie recuerda y que la
    plataforma no perdona.
    """
    seccion = _texto(RAIZ / "docs" / "roadmap.md").split("### 0.8:")[1].split("\n### ")[0]
    # Con los espacios sueltos: una tabla realineada a mano es lo normal en Markdown, y ya
    # pasó una vez que un guardia se cayera por un espacio de más sin decir nada del dato.
    filas = re.findall(r"^\s*\|\s*`(\w+)`\s*\|\s*`(\w+)`\s*\|", seccion, re.M)
    assert filas, "la tabla de competencia y panel de la sección 0.8 desapareció"
    pedidos = {c.historia.panel for c in COMPETENCIAS.values() if c.historia is not None}
    for competencia, panel in filas:
        historia = COMPETENCIAS[competencia].historia
        if historia is None:
            # La fila de penal está a propósito: documenta el panel que se PIDIÓ y no existe,
            # que es la parte cara de esa medición. Lo que hay que cuidar es que no se cuele
            # como si fuera un panel que este servidor usa.
            assert panel not in pedidos, (
                f"{competencia!r} no está mapeada y la tabla nombra {panel!r}, que sí se pide"
            )
            continue
        assert historia.panel == panel, (
            f"la hoja de ruta dice que {competencia!r} se lee del panel {panel!r} y el código "
            f"pide {historia.panel!r}"
        )


#: Bloques `json` que NO son ejemplos de respuesta y por eso no se comparan contra el modelo:
#: la configuración del cliente MCP, y la respuesta de una API de terceros que `ecosistema`
#: cita para explicar qué hace esa otra herramienta.
CLAVES_QUE_NO_SON_DEL_MODELO = frozenset({"mcpServers", "servers", "data", "date", "status"})


def test_los_ejemplos_json_no_ensenan_campos_que_el_modelo_no_tiene():
    """Un ejemplo con un campo que ya no existe enseña a leer una respuesta imaginaria.

    Los ejemplos están recortados a propósito ("recortada al folio que interesa"), así que
    validarlos con `model_validate` mediría mal: fallaría por los campos ausentes. Lo que sí
    muerde es el subconjunto, toda clave del ejemplo tiene que ser un campo de algún modelo, y
    es la dirección que importa: sobra un campo inventado o viejo, no falta uno recortado.
    """
    from pydantic import BaseModel

    from mcp_pjud import parser as modelos

    # Por modelo y no como una bolsa con todos los campos juntos: la bolsa deja pasar el caso
    # que importa. Renombrar `fecha_diligencia` en `Actuacion` la sigue encontrando en otro
    # modelo que también la publica, y el ejemplo de una actuación queda enseñando un campo que
    # esa actuación ya no trae.
    familias = {
        nombre: set(getattr(modelos, nombre).model_fields)
        for nombre in dir(modelos)
        if isinstance(getattr(modelos, nombre, None), type)
        and issubclass(getattr(modelos, nombre), BaseModel)
    }
    assert "fecha_diligencia" in familias["Actuacion"], "no se recogieron los campos del modelo"

    revisados, malas = 0, []
    for f in [*PROSA, RAIZ / "README.md"]:
        for bloque in re.findall(r"```json\n(.*?)\n```", _texto(f), re.S):
            datos = json.loads(bloque)
            filas = datos if isinstance(datos, list) else [datos]
            for fila in filas:
                if not isinstance(fila, dict) or set(fila) & CLAVES_QUE_NO_SON_DEL_MODELO:
                    continue
                revisados += 1
                # El modelo que más claves comparte con el ejemplo: los ejemplos vienen
                # recortados, así que se elige por parecido y no por coincidencia exacta.
                cual = max(familias, key=lambda n: len(set(fila) & familias[n]))
                malas += [
                    f"{f.name}: `{c}` no es campo de {cual}"
                    for c in sorted(set(fila) - familias[cual])
                ]
    assert revisados >= 3, f"se dejaron de revisar los ejemplos de respuesta: {revisados}"
    assert not malas, (
        f"estos ejemplos enseñan campos que ningún modelo trae: {malas}. Un ejemplo con un "
        "campo viejo enseña a leer una respuesta que no llega."
    )


def test_la_hoja_de_ruta_cuenta_lo_que_falta_con_las_cifras_del_codigo():
    """La tabla de lo que queda es lo primero que alguien lee para saber si el proyecto sirve.

    Sus dos cifras son restas, no datos: rutas aceptadas menos ejecutadas, y rutas que el sitio
    nombra menos medidas. Escritas a mano quedan viejas justo cuando se mide una más, que es
    cuando importa que la tabla diga la verdad.
    """
    faltan_documentos = sum(len(r) for r in DOCUMENTOS.values()) - len(DOCUMENTOS_EJECUTADAS)
    js = _texto(RAIZ / "tests" / "fixtures" / "consultaUnificada.html")
    nombradas = set(re.findall(r"/(?:\w+)/modal/(\w*[Aa]nexo\w*\.php)", js))
    medidas = {r for paneles in ANEXOS.values() for r in paneles} | set(ANEXOS_MEDIDOS_SIN_EXPONER)

    hoja = " ".join(_texto(RAIZ / "docs" / "roadmap.md").split())
    total = sum(len(r) for r in DOCUMENTOS.values())
    assert (
        f"{EN_LETRAS[faltan_documentos].capitalize()} de las {EN_LETRAS[total]} rutas de documento"
        in hoja
    ), f"faltan {faltan_documentos} rutas de documento de {total} y la hoja de ruta dice otra cosa"
    assert f"{EN_LETRAS[len(nombradas - medidas)].capitalize()} rutas de anexo" in hoja, (
        f"faltan {len(nombradas - medidas)} rutas de anexo por medir y la hoja dice otra cosa"
    )


def test_el_servidor_se_registra_con_el_mismo_nombre_en_todas_las_guias():
    """Seis lugares registran el servidor y sólo cuatro pasan por `cog`.

    Los otros dos son los botones de un clic del README, que llevan el nombre dentro de una URL
    y encima repetido: en `name=` y dentro del `config` codificado. Ahí es donde se desincroniza
    sin que nadie lo note, porque un botón con otro alias instala igual y deja al usuario con
    dos servidores que hacen lo mismo.
    """
    # Se carga por ruta y no con un `import`: `docs/` no es un paquete, así que el chequeador
    # de tipos no puede resolverlo y la corrida de CI se cae por algo que en ejecución anda.
    # Es el mismo mecanismo con que este archivo carga `docs/conf.py`.
    import importlib.util

    spec = importlib.util.spec_from_file_location("_bloques", RAIZ / "docs" / "_bloques.py")
    assert spec is not None
    assert spec.loader is not None
    bloques = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bloques)
    ALIAS = bloques.ALIAS

    readme = _texto(RAIZ / "README.md")
    guia = _texto(RAIZ / "docs" / "instalacion.md")

    assert f"claude mcp add {ALIAS} " in readme
    assert f"claude mcp add {ALIAS} " in guia
    assert f"codex mcp add {ALIAS} " in guia
    assert f'[mcp_servers."{ALIAS}"]' in guia
    assert readme.count(f"name={ALIAS}&config=") == 2, (
        "los dos botones de un clic tienen que registrar el mismo alias que el resto"
    )
    # Y el alias dentro del `config` del botón de VS Code, que va aparte del `name=`.
    assert f"%22name%22%3A%22{ALIAS}%22" in readme, (
        "el botón de VS Code lleva el nombre dos veces y una quedó con el alias viejo"
    )


#: El tope no es estético: el cliente DIFIERE las definiciones cuando pasan del 10% de su
#: ventana de contexto, y ahí una sesión carga parte del catálogo sin enterarse de que le
#: faltan herramientas. Pasó, y por eso existe este guardia.
#:
#: Lo que el catálogo pesa HOY no se escribe en ninguna parte a propósito: cambia con cada
#: descripción que se toca, así que una cifra escrita queda vieja al PR siguiente. Ya pasó una
#: vez, en este mismo comentario. Lo que sí se escribe es lo medido antes del tope, que es un
#: hecho fechado, y vive abajo con su guardia.
PRESUPUESTO_DEL_CATALOGO = 60_000

#: Lo que pesaban el catálogo y la directiva ANTES de este trabajo, medido el 24 de agosto de
#: 2026 por stdio contra el ejecutable publicado, y cuántas herramientas llegaron de las
#: catorce. Son hechos fechados, no valores vigentes: la documentación los cita para explicar
#: por qué existen los topes, y sin fuente única cada página los iba a envejecer por su lado.
CATALOGO_ANTES = 104_475
DIRECTIVA_ANTES = 3_770
DESCRIPCION_ANTES = 2_390
HERRAMIENTAS_QUE_LLEGARON = 10

#: Cuántas había ese día. Congelada y NO `len(_catalogo())`: atada al número de hoy, agregar la
#: decimoquinta herramienta pondría la suite en rojo hasta que alguien escribiera "diez de las
#: quince", que es una medición que nadie hizo. El guardia obligaría a falsear el hecho que dice
#: proteger.
HERRAMIENTAS_DE_ESE_DIA = 14

#: Claude Code trunca en 2 KB cada descripción de herramienta y las instrucciones del servidor,
#: en silencio. Lo que cae del otro lado del corte no llega y nadie lo nota. El número sale del
#: código, que es donde lo mira quien escribe la prosa.
TOPE_DE_UNA_DESCRIPCION = TOPE_DEL_CLIENTE


def _catalogo() -> tuple[dict, ...]:
    """El catálogo tal como viaja, no como está en memoria.

    Sin `functools.cache`, aunque cueste una sesión por test que lo pida. Con la caché, sólo el
    PRIMER test que llegara acá ejecutaba `list_tools`, así que el testing de mutación atribuía
    `_sin_prosa` a ese test y a ninguno más: cinco mutantes que dejan la prosa viajando se
    daban por vivos, y la suite entera los mataba. Medido el 24 de agosto de 2026.

    Va por una sesión MCP de verdad y no por `mcp.list_tools()` porque lo que hay que medir es
    lo que el cliente recibe: el SDK cuelga un `_meta` del resultado, y si algún día colgara
    algo de cada herramienta, medir el objeto en memoria daría un presupuesto que nadie gasta.
    Hoy las dos cuentas coinciden, que es justo lo que esto deja fijado.

    `by_alias` porque el cable usa `outputSchema` y el objeto `output_schema`.
    """

    async def anunciar() -> tuple[dict, ...]:
        async with Client(mcp) as cliente:
            listado = await cliente.list_tools()
            return tuple(h.model_dump(by_alias=True, exclude_none=True) for h in listado.tools)

    return asyncio.run(anunciar())


def test_la_directiva_entera_llega_al_modelo():
    """Las instrucciones del servidor se cortan en el mismo tope que una descripción.

    Pesaban 3.770 bytes y nadie lo notó, porque un corte silencioso se ve igual que un texto
    que termina. Lo que caía del otro lado eran tres reglas, y las tres son de las que evitan
    afirmar de más: el nulo de `ocultas`, la cita no verificada, y el ritmo.

    Se comprueban por separado de la medida porque son cosas distintas: el tope se puede
    cumplir borrando justamente lo que hay que decir.
    """
    from mcp_pjud.server import DIRECTIVA

    pesa = len(DIRECTIVA.encode())
    assert pesa <= TOPE_DEL_CLIENTE, (
        f"la directiva pesa {pesa} bytes y el cliente corta en {TOPE_DEL_CLIENTE}, sin avisar. "
        "Lo que sobra no llega, y lo que sobra es el final"
    )
    for regla in (
        f"hasta {RAFAGA_MAXIMA} peticiones",
        f"cada {INTERVALO_MINIMO:.0f} segundos",
        "en NULO tampoco es cero",
        "Nunca presentar una cita como verificada si la",
    ):
        assert regla in DIRECTIVA, (
            f"la directiva dejó de decir {regla!r}, que es de las que el corte se llevaba"
        )

    # Y el tope escrito a mano en la prosa, contra la constante. Sin esto, cambiar el número
    # deja el test verde y las páginas documentando un corte que ya no es el que ocurre.
    escrito = f"{TOPE_DEL_CLIENTE:,}".replace(",", ".")
    obligadas = [
        RAIZ / "docs" / "herramientas.md",
        RAIZ / "docs" / "uso.md",
        RAIZ / "docs" / "roadmap.md",
    ]
    for pagina in obligadas:
        assert f"{escrito} bytes" in _texto(pagina), (
            f"{pagina.relative_to(RAIZ)} explica el corte del cliente y no cita los {escrito} "
            "bytes en que ocurre"
        )
    # El otro tope, el del catálogo entero. La hoja de ruta lo cita al lado del anterior: si
    # cambia la constante y no la página, queda describiendo un corte que ya no es el que hay.
    presupuesto = f"{PRESUPUESTO_DEL_CATALOGO:,}".replace(",", ".")
    assert presupuesto in _texto(RAIZ / "docs" / "roadmap.md"), (
        f"la hoja de ruta explica el diferimiento del catálogo y no cita su tope ({presupuesto})"
    )
    donde_corta = re.compile(r"(?:corta en|cabe en) \*{0,2}([\d.]+) bytes")
    for fuente in PROSA:
        for cita in donde_corta.finditer(_texto(fuente)):
            assert cita.group(1) == escrito, (
                f"{fuente.relative_to(RAIZ)} dice que el corte es a los {cita.group(1)} bytes "
                f"y la constante son {escrito}"
            )


def test_las_cifras_del_corte_son_las_medidas():
    """Las tres que explican por qué existen los topes, contra su fuente única.

    Son de una medición fechada, así que no se derivan de nada vivo: si alguien las corrige o
    vuelve a medir, la página que no se toque sigue publicando la vieja y nadie se entera. Es
    la misma clase de dato repetido que el resto de este archivo persigue, y se coló igual.

    La cara negativa es la que hace trabajo: cualquier OTRA cifra presentada como el peso de
    aquel catálogo o de aquella directiva se rechaza, porque el modo de falla no es que la
    frase desaparezca, es que se escriba distinta en una página sola.
    """

    def escrita(n: int) -> str:
        return f"{n:,}".replace(",", ".")

    catalogo, directiva = escrita(CATALOGO_ANTES), escrita(DIRECTIVA_ANTES)
    # Las tres del mismo trabajo. La de la descripción mayor no es obligatoria en ninguna
    # página, pero tiene que poder escribirse con el mismo verbo sin poner la suite en rojo.
    medidas = (catalogo, directiva, escrita(DESCRIPCION_ANTES))
    obligadas = [RAIZ / "docs" / "uso.md"]
    for pagina in obligadas:
        texto = _texto(pagina)
        for cifra, que in ((catalogo, "el catálogo"), (directiva, "la directiva")):
            assert cifra in texto, (
                f"{pagina.relative_to(RAIZ)} explica el corte y no cita lo que pesaba {que} "
                f"antes ({cifra})"
            )
        cuantas = (
            f"{EN_LETRAS[HERRAMIENTAS_QUE_LLEGARON]} de las {EN_LETRAS[HERRAMIENTAS_DE_ESE_DIA]}"
        )
        assert cuantas in texto, (
            f"{pagina.relative_to(RAIZ)} no dice cuántas herramientas llegaron de las que hay "
            "hoy, que es lo que vuelve concreto el defecto"
        )

    # Cuánto se perdía es una resta, no una medición aparte: escrita a mano fue "un tercio",
    # que sobre 3.770 contra 2.048 son 1.722, o sea casi la mitad. Una fracción redonda en la
    # prosa no tiene con qué comprobarse; la resta sí.
    perdidos = f"{DIRECTIVA_ANTES - TOPE_DEL_CLIENTE:,}".replace(",", ".")
    for pagina in (RAIZ / "docs" / "uso.md", RAIZ / "docs" / "roadmap.md"):
        assert perdidos in _texto(pagina), (
            f"{pagina.relative_to(RAIZ)} dice cuánto de la directiva se perdía y no son los "
            f"{perdidos} bytes que dan {DIRECTIVA_ANTES} menos {TOPE_DEL_CLIENTE}"
        )

    # Y que ninguna fuente le ponga OTRA cifra a lo mismo. De quién habla se busca hacia atrás:
    # las tres cifras son reales y son de objetos distintos, así que aceptar cualquiera para
    # cualquiera deja pasar "el catálogo pesaba 2.390", que es falso con números verdaderos.
    de_quien = {
        "catálogo": catalogo,
        "tools/list": catalogo,
        "directiva": directiva,
        "instructions": directiva,
        "descripción": escrita(DESCRIPCION_ANTES),
    }
    pesaba = re.compile(r"[Pp]esaba[n]?\s+(?:de\s+)?([\d.]+)")
    for fuente in [*PROSA, *(RAIZ / "src" / "mcp_pjud").glob("*.py")]:
        texto = _legible(fuente)
        for mencion in pesaba.finditer(texto):
            antes = texto[max(0, mencion.start() - CERCA) : mencion.start()].lower()
            sujetos = [(antes.rfind(n), c) for n, c in de_quien.items() if n in antes]
            esperada = max(sujetos)[1] if sujetos else None
            assert mencion.group(1) == (esperada or mencion.group(1)), (
                f"{fuente.relative_to(RAIZ)} le atribuye {mencion.group(1)} a algo que ese día "
                f"midió {esperada}"
            )
            assert mencion.group(1) in medidas, (
                f"{fuente.relative_to(RAIZ)} dice que algo pesaba {mencion.group(1)}, que no "
                f"es ninguna de las tres medidas de ese día: {', '.join(medidas)}"
            )


def test_el_catalogo_cabe_en_el_presupuesto_del_cliente():
    """Un catálogo que pasa del 10% de la ventana se difiere entero, y eso no falla: calla.

    La herramienta que el modelo no ve no la puede pedir, y no hay señal de que falte. Es un
    falso negativo del mismo tipo que los del parser, servido por el protocolo.
    """
    pesa = len(json.dumps(_catalogo()))
    assert pesa <= PRESUPUESTO_DEL_CATALOGO, (
        f"el catálogo pesa {pesa:,} caracteres y el tope es {PRESUPUESTO_DEL_CATALOGO:,}. "
        "Sobre el 10% de la ventana del cliente las definiciones se difieren en silencio"
    )


def test_ninguna_descripcion_de_herramienta_pasa_del_tope_del_cliente():
    """Se trunca en 2 KB, sin aviso, y lo que se pierde es el final: los avisos van al final."""
    largas = {
        h["name"]: len(h["description"].encode())
        for h in _catalogo()
        if len(h.get("description", "").encode()) > TOPE_DE_UNA_DESCRIPCION
    }
    assert not largas, (
        f"estas descripciones pasan de {TOPE_DE_UNA_DESCRIPCION} bytes y el cliente las corta "
        f"por la mitad sin avisar: {largas}"
    )


def test_los_cuelgues_que_subieron_el_techo_salen_de_su_constante():
    """La medición que justifica el techo de espera se cita en prosa, y era libre.

    `CUELGUES_DE_COMBOS_SIN_MEDIR` guarda cuántas consultas murieron en el techo viejo, y de
    ellas se conoce una COTA INFERIOR y no una duración: el timeout las mató. Las páginas que
    lo cuentan repetían el número a mano, así que corregir la medición dejaba la explicación
    con otra cifra sin que nada fallara.
    """
    en_letras = EN_LETRAS[CUELGUES_DE_COMBOS_SIN_MEDIR]
    obligadas = [RAIZ / "docs" / "uso.md", RAIZ / "docs" / "roadmap.md"]
    for pagina in obligadas:
        texto = _texto(pagina)
        assert f"{en_letras} cuelgues" in texto or f"{en_letras} consultas" in texto, (
            f"{pagina.relative_to(RAIZ)} cuenta los cuelgues que subieron el techo y no dice "
            f"{en_letras}, que es lo que guarda la constante"
        )


def test_la_referencia_tabula_todas_las_excepciones_del_paquete():
    """La tabla de errores se escribe a mano y el código gana excepciones.

    Quien conecta esto lee esa tabla para saber qué hacer con cada fallo. Dos ya se habían
    quedado fuera sin que nada avisara: `ResultadosTruncados`, que la directiva misma explica
    ("si una búsqueda excede el tope de páginas, la herramienta falla"), y `CausaNoEncontrada`,
    que es la que distingue una causa que no se encontró de una sin actuaciones.

    Se deriva de los módulos y no de una lista escrita acá: una excepción nueva entra sola al
    guardia, que es justo lo que no pasó con estas dos.
    """
    import inspect

    from mcp_pjud import client as _cliente_mod
    from mcp_pjud import juris as _juris_mod
    from mcp_pjud import parser as _parser_mod

    clases = {
        nombre
        for modulo in (_cliente_mod, _parser_mod, _juris_mod)
        for nombre, objeto in vars(modulo).items()
        if inspect.isclass(objeto)
        and issubclass(objeto, Exception)
        and objeto.__module__.startswith("mcp_pjud")
    }
    assert clases, "no se encontró ninguna excepción del paquete: el barrido dejó de mirar"

    # De las FILAS de la tabla y no de la sección entera: los nombres aparecen también en el
    # párrafo de abajo, así que borrar una fila dejaba el guardia verde. Medido con
    # `PjudNoRespondio`, que se nombra en los dos lados.
    seccion = HERRAMIENTAS.split("## Errores")[1].split("\n## ")[0]
    tabulados = set(re.findall(r"^\s*\|\s*`(\w+)`\s*\|", seccion, re.M))
    faltan = sorted(c for c in clases if c not in tabulados)
    assert not faltan, (
        f"estas excepciones pueden llegarle a quien consulta y la referencia no las tabula: "
        f"{faltan}"
    )


def test_ninguna_plantilla_pasa_del_tope_en_lo_que_el_cliente_lista():
    """El mismo corte que a las herramientas, sobre el campo que de verdad viaja en la lista.

    Ojo con cuál es. El CUERPO que una plantilla devuelve entra a la conversación como texto de
    la persona y no lo corta nadie: medido, `revisar-causa` son 2.177 bytes y está bien. Lo que
    el cliente lista y podría cortar es la `description`, que es la que decide si alguien elige
    la plantilla, igual que en una herramienta.

    Se escribe porque la confusión ya ocurrió: al escribirlas se cuidó el largo del cuerpo,
    que no hacía falta, y nadie miraba el campo que sí.
    """
    largas = {
        p.name: len((p.description or "").encode())
        for p in asyncio.run(mcp.list_prompts())
        if len((p.description or "").encode()) > TOPE_DE_UNA_DESCRIPCION
    }
    assert not largas, (
        f"estas descripciones de plantilla pasan de {TOPE_DE_UNA_DESCRIPCION} bytes y el "
        f"cliente las corta sin avisar: {largas}"
    )


def test_despojar_la_prosa_no_se_lleva_un_campo_que_se_llame_asi():
    """`description` es una palabra de JSON Schema en un nivel y un nombre de campo en otro.

    Dentro de `properties` o de `$defs` la clave es el nombre, así que filtrarla sacaría el
    campo del esquema anunciado y dejaría su `required` apuntando a nada: el modelo dejaría de
    ver un campo que la respuesta sí trae, sin que nada falle.

    Hoy ningún modelo tiene un campo así porque los nombres van en español. El guardia va sobre
    un esquema sintético a propósito: el día que alguien agregue uno, esto ya está puesto.
    """
    esquema = {
        "description": "esto es prosa y se va",
        "properties": {
            "description": {"type": "string", "description": "esto también es prosa"},
            "properties": {"type": "integer", "description": "un campo con nombre engañoso"},
        },
        "required": ["description", "properties"],
        "$defs": {"description": {"type": "object", "description": "un modelo así llamado"}},
        # Las cuatro posiciones donde el contenido es el VALOR del campo. Con sólo `default`,
        # sacar las otras tres de `_VALORES_OPACOS` dejaba la suite verde: ningún esquema real
        # las usa todavía, que es justo la razón por la que se cubrieron.
        "default": {"description": "esto es el VALOR del campo, no prosa de la herramienta"},
        "const": {"description": "un valor constante compuesto"},
        "enum": [{"description": "una alternativa"}, {"description": "otra"}],
        "examples": [{"description": "un ejemplo"}],
    }
    despojado = _sin_prosa(esquema)
    # `_sin_prosa` declara `object` porque recorre cualquier nodo; acá entró un diccionario.
    assert isinstance(despojado, dict)

    assert "description" not in despojado, "la anotación del nivel de arriba tenía que irse"
    assert set(despojado["properties"]) == {"description", "properties"}, (
        "se perdió un campo: su nombre coincidía con una palabra de JSON Schema"
    )
    assert "description" not in despojado["properties"]["description"], (
        "la anotación DENTRO del campo sí es prosa y tenía que irse"
    )
    assert set(despojado["$defs"]) == {"description"}, "se perdió un modelo de `$defs`"
    # Los nombres sobreviven Y sus valores se siguen recorriendo: sin esta línea, una rama que
    # devolviera el mapa tal cual pasaría el test dejando viajar la prosa de adentro.
    assert "description" not in despojado["$defs"]["description"], (
        "dentro de un modelo de `$defs` la anotación sí es prosa y tenía que irse"
    )
    for clave in ("default", "const", "enum", "examples"):
        assert despojado[clave] == esquema[clave], (
            f"lo que cuelga de `{clave}` es el valor del campo: borrarle una clave le cambia "
            "al modelo el dato que el servidor sí valida"
        )
    assert despojado["required"] == ["description", "properties"], (
        "`required` quedó nombrando campos que ya no están en el esquema"
    )


def test_ningun_esquema_de_salida_anunciado_lleva_prosa():
    """La prosa de los campos vive en el modelo y se publica en la referencia; en el cable
    ocupa el 38% del catálogo y el modelo ya la tiene en la descripción de la herramienta.

    Es recursivo a propósito: la prosa se esconde en `$defs`, que es donde estaba el 89% del
    peso de `obtener_detalle_causa`.
    """

    def prosa(nodo, camino=""):
        if isinstance(nodo, dict):
            hallada = [camino] if "description" in nodo else []
            return hallada + [
                x for k, v in nodo.items() for x in prosa(v, f"{camino}.{k}" if camino else k)
            ]
        if isinstance(nodo, list):
            return [x for i, v in enumerate(nodo) for x in prosa(v, f"{camino}[{i}]")]
        return []

    con_prosa = {
        h["name"]: len(prosa(h["outputSchema"])) for h in _catalogo() if "outputSchema" in h
    }
    con_prosa = {k: v for k, v in con_prosa.items() if v}
    assert not con_prosa, (
        f"estos esquemas de salida anuncian prosa por campo: {con_prosa}. El protocolo anuncia "
        "la FORMA; lo que el modelo tiene que saber va en la descripción de la herramienta"
    )


def test_la_seccion_de_anexos_nombra_cada_panel_medido_con_su_campo_y_su_descarga():
    """Lo que la página afirma sobre los paneles medidos sale del código, no de la memoria.

    Son ocho paneles con formas distintas, y esa tabla es lo que alguien va a leer para
    repetir la medición cuando la plataforma cambie. Escribirla a mano la deja envejecer justo
    ahí, y de a un panel por vez, que es como no se nota.
    """
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    seccion = pagina.split("## El segundo canal de documentos")
    assert len(seccion) == 2, "la sección del canal de anexos desapareció"
    seccion = seccion[1].split("\n## ")[0]

    medidos = {r: campo for paneles in ANEXOS.values() for r, campo in paneles.items()}
    medidos.update(ANEXOS_MEDIDOS_SIN_EXPONER)
    for ruta, campo in medidos.items():
        assert f"`{ruta}`" in seccion, f"la sección no nombra el panel {ruta!r}"
        assert f"`{campo}`" in seccion, f"la sección no dice con qué campo se pide {ruta!r}"

    # Las columnas también: son lo que distingue un panel de otro, y la afirmación de la página
    # es justamente que NO comparten forma.
    for ruta, spec in _PANELES_ANEXO.items():
        assert f"`{ruta}`" in seccion, f"{ruta!r} está mapeado y la sección no lo nombra"
        fila = next(li for li in seccion.splitlines() if f"`{ruta}`" in li)
        for encabezado in spec.encabezados:
            assert encabezado in fila.lower(), (
                f"la fila de {ruta!r} no nombra su columna {encabezado!r}, y el mapeo es posicional"
            )

    # Y la ruta de descarga de cada competencia, que sale de `DOCUMENTOS`.
    for competencia in ANEXOS:
        descargas = [
            r for r in DOCUMENTOS[competencia] if "anexo" in r.lower() or "escrito" in r.lower()
        ]
        assert descargas, f"{competencia} no declara ninguna ruta de descarga de anexo"


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


def test_la_referencia_nombra_los_paneles_que_el_detalle_sí_trae():
    """La frase que abre la sección enumera lo que llega, y se quedó corta dos veces seguidas.

    Es lo primero que lee quien evalúa si la herramienta le sirve, y cada panel nuevo entró con
    su fila en la tabla generada mientras esa frase seguía diciendo lo de antes. Los nombres
    salen de los campos del modelo, no de una lista escrita al lado.
    """
    seccion = HERRAMIENTAS.split("## `obtener_detalle_causa`")[1].split("\n## ")[0]
    # Normalizado: la frase va envuelta, y "escritos por resolver" cae partido en dos líneas.
    apertura = " ".join(seccion.split("\n\n")[1].split()).lower()

    # Los campos que son paneles, con la palabra que la prosa usa para nombrarlos. Los que no
    # son paneles quedan fuera con su razón.
    palabras = {
        "historia": "historia",
        "litigantes": "litigantes",
        "notificaciones": "notificaciones",
        "liquidaciones": "liquidaciones",
        "diligencias": "diligencias",
        "materias": "materias",
        "escritos_pendientes": "escritos por resolver",
        "exhortos": "exhorto",
        "piezas_exhorto": "exhorto",
        "causa_de_origen": "causa de la que subió el recurso",
        "causas_agregadas": "causas agregadas",
    }
    fuera = {
        "causa_encontrada",  # dice si la búsqueda dio con el rol, no es un panel
        "causa_es_exhorto",  # sale de la cabecera, y tiene su propia explicación abajo
        "audio_referencia",  # es con qué pedir otra herramienta, y tiene su párrafo aparte
    }
    sin_declarar = sorted(set(DetalleCausa.model_fields) - set(palabras) - fuera)
    assert not sin_declarar, (
        f"campos nuevos en `DetalleCausa` que este guardia no sabe si son paneles: "
        f"{sin_declarar}. Agrégalos con la palabra que la prosa usa, o a `fuera` con su razón"
    )
    faltan = sorted({p for _campo, p in palabras.items() if p not in apertura})
    assert not faltan, (
        f"la frase que abre `obtener_detalle_causa` no nombra {faltan}, que la respuesta sí "
        "trae. Es lo primero que se lee para saber si la herramienta sirve"
    )


def test_el_contrato_del_detalle_nombra_los_paneles_que_no_lee():
    """La respuesta combinada no es el expediente, y su contrato tiene que decirlo.

    La hoja de ruta lo exigía desde hace versiones y no se había cumplido: el docstring decía
    "todo lo que la respuesta del detalle publica", con nueve paneles sin mapear en las cinco
    competencias. Una ausencia sin declarar se lee como inexistencia, que es la regla 4 una
    capa más arriba: no hay lista vacía, hay un campo que no existe.

    Los paneles se derivan de las fixtures y no de una lista escrita al lado: si mañana se mapea
    uno, este guardia exige que salga del contrato, y si el sitio publica uno nuevo, exige que
    entre.

    Ojo con lo que NO puede hacer: busca el concepto en el contrato entero, así que si el
    docstring nombra un panel por otro motivo, el guardia lo da por declarado y deja de ver ese
    panel. Al mapear `corteApelaciones` hubo que sacar "Corte de Apelaciones" de todo el
    docstring, no sólo de la frase de los paneles sin leer: con el nombre puesto en la frase que
    describe el campo nuevo, desmapear el panel volvía a este test verde. Se midió rompiéndolo.
    """
    fixtures = {
        "civil": "detalle_causa_civil.html",
        "cobranza": "detalle_cobranza.html",
        "laboral": "detalle_laboral.html",
        "apelaciones": "detalle_apelaciones.html",
        "suprema": "detalle_suprema.html",
    }
    # Los atributos que son un panel salen de `Competencia`, no de una lista escrita acá: la
    # lista se quedó corta tres veces seguidas, una por cada panel nuevo, y el efecto es que el
    # guardia exige nombrar en el contrato algo que sí se lee.
    paneles = tuple(
        campo
        for campo in Competencia._fields
        if any(
            isinstance(getattr(c, campo), Panel)
            or (campo.endswith("_origen") and getattr(c, campo))
            for c in COMPETENCIAS.values()
        )
    )
    assert len(paneles) >= 8, f"la derivación de paneles encontró {paneles}: dejó de ver algo"
    # Normalizado: el docstring va envuelto a 96 columnas, así que "Corte de Apelaciones"
    # puede venir partido en dos líneas y una comparación cruda no lo encuentra.
    contrato = " ".join((DetalleCausa.__doc__ or "").split()).lower()

    sin_leer = set()
    for competencia, fixture in fixtures.items():
        arbol = html.fromstring(_texto(RAIZ / "tests" / "fixtures" / fixture))
        con_tabla = [e for e in arbol.iter() if e.get("id") and e.findall(".//table")]
        # Sólo las hojas: los contenedores de pestaña también traen tabla adentro, y contarlos
        # haría que el contrato tuviera que nombrar la pestaña además del panel.
        hojas = {
            e.get("id")
            for e in con_tabla
            if not any(otro is not e and otro in e.iterdescendants() for otro in con_tabla)
        }
        # `causa_de_origen` declara el `id` a secas y no un `Panel`: su panel no es una tabla
        # de filas sino pares de rótulo y valor, así que no tiene columnas ni encabezados.
        leidos = {
            panel.panel if isinstance(panel, Panel) else panel
            for atributo in paneles
            if (panel := getattr(COMPETENCIAS[competencia], atributo, None)) is not None
        }
        # `loadHistCuaderno*` es la historia de otro cuaderno, que sí se lee: el recorrido pide
        # cada cuaderno por separado.
        sin_leer |= {p for p in hojas - leidos if p and not p.startswith("loadHistCuaderno")}

    assert sin_leer, "ninguna fixture trae paneles sin mapear: el guardia dejó de ver algo"
    # No se exige el `id` literal, que es jerga del sitio: se exige que el contrato nombre la
    # cosa. `escritosCiv` -> "escritos", `diligenciasLab` -> "diligencias".
    conceptos = {
        "escritosciv": "escritos",
        "escpendlab": "escritos",
        "diligenciaslab": "diligencias",
        "liquidacionlab": "liquidaciones",
        "exhortosape": "exhortos",
        "incompetenciaape": "incompetencia",
        "agregadossup": "agregad",
        "corteapelaciones": "corte de apelaciones",
    }
    faltan = sorted(p for p in sin_leer if conceptos.get(p.lower(), p.lower()) not in contrato)
    assert not faltan, (
        f"el detalle no lee estos paneles y su contrato no los nombra: {faltan}. Quien reciba "
        "la respuesta va a leer la ausencia como inexistencia."
    )


def test_la_ruta_ejecutada_no_figura_entre_las_que_nunca_se_pidieron():
    """La página se contradecía consigo misma y la suite estaba verde.

    `docuN.php` aparecía en la lista de "mapeado pero nunca ejecutado" y, treinta líneas más
    arriba, entre lo medido contra la plataforma. Los cuatro guardias de rutas de documento
    verifican nombres y parámetros; ninguno miraba la afirmación de haberla EJECUTADO, que es la
    que distingue "el sitio emite esta ruta" de "esta ruta responde".
    """
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    sin_ejecutar = pagina.split("### Mapeado pero nunca ejecutado")[1].split("\n### ")[0]

    # Con el mismo patrón tolerante que la aserción de abajo: la página escribe unas rutas
    # sueltas y otras con su carpeta delante (`civil/documentos/docuN.php`), y buscar sólo la
    # forma suelta dejaba pasar la otra. Un guardia que no ve la mitad de las formas en que se
    # escribe el dato es el que no puede fallar.
    #
    # El prefijo termina en `/` o no existe. Sin esa barra, `docu.php` calzaba dentro de
    # `otro_docu.php`: tolerante de más también deja de distinguir, y `DOCUMENTOS` tiene cuatro
    # rutas que empiezan igual.
    coladas = sorted(
        r
        for r in DOCUMENTOS_EJECUTADAS
        if re.search(rf"`(?:[\w/]*/)?{re.escape(r)}`", sin_ejecutar)
    )
    assert not coladas, (
        f"{coladas} se ejecutaron contra la plataforma y siguen en la lista de lo nunca "
        "ejecutado. Las dos afirmaciones no pueden convivir"
    )
    for ruta in DOCUMENTOS_EJECUTADAS:
        assert re.search(rf"`(?:[\w/]*/)?{re.escape(ruta)}`", pagina), (
            f"{ruta!r} se ejecutó y la página no la nombra en ninguna parte"
        )
    # Y al revés: lo ejecutado tiene que ser una ruta que el cliente acepte, o la constante
    # estaría declarando una medición sobre algo que nadie puede pedir.
    aceptadas = {r for rutas in DOCUMENTOS.values() for r in rutas}
    assert aceptadas >= DOCUMENTOS_EJECUTADAS, (
        f"{sorted(DOCUMENTOS_EJECUTADAS - aceptadas)} figura como ejecutada y `obtener_documento` "
        "no la acepta"
    )

    # La tabla de lo medido tiene que decir exactamente lo mismo que la constante. Esto NO
    # comprueba que la medición ocurrió, que no es comprobable desde acá: obliga a que declararla
    # cueste editar las dos, en vez de que una diga siete y la otra ocho.
    tabla = pagina.split("| Ruta ejecutada | Competencia | Medido |")[1].split("\n\n")[0]
    # Con los espacios sueltos: una tabla realineada a mano es lo normal en Markdown, y un
    # guardia que se cae por un espacio de más no dice nada sobre el dato que cuida.
    publicadas = set(re.findall(r"^\s*\|\s*`([\w.]+)`\s*\|", tabla, re.M))
    assert publicadas == DOCUMENTOS_EJECUTADAS, (
        f"la tabla de rutas ejecutadas publica {sorted(publicadas)} y el código declara "
        f"{sorted(DOCUMENTOS_EJECUTADAS)}"
    )


def test_el_estado_declarado_es_el_que_el_codigo_hace():
    """El archivo de estado no puede declarar expuesto lo que el cliente rechaza, ni al revés.

    Es la mitad que hace útil tener los datos aparte de la prosa. La otra mitad es que un
    estado distinto de `expuesto` obliga a escribir `razon`: escrito a mano, "no cubierto" no
    cuesta nada y la razón se pierde, que es como una página de estado se vuelve una lista de
    huecos sin explicación.
    """
    estado = yaml.safe_load(_texto(RAIZ / "docs" / "estado-de-verificacion.yml"))

    for familia in ("buscadores", "competencias"):
        for e in estado[familia]:
            if e["estado"] != "expuesto":
                assert e.get("razon"), (
                    f"{e['nombre']!r} figura como {e['estado']!r} y no dice por qué"
                )

    buscadores = {e["nombre"]: e for e in estado["buscadores"]}
    assert {n for n, e in buscadores.items() if e["estado"] == "expuesto"} == set(BUSCADORES), (
        "el archivo de estado y `BUSCADORES` no ofrecen los mismos buscadores"
    )
    for nombre, identificador in IDENTIFICADORES_MEDIDOS.items():
        assert buscadores[nombre].get("id") == identificador, (
            f"el identificador de {nombre!r} no es el que se midió: {identificador}"
        )

    competencias = {e["nombre"]: e for e in estado["competencias"]}
    con_detalle = {n for n in MODULOS if COMPETENCIAS[n].historia is not None}
    assert {n for n, e in competencias.items() if e["estado"] == "expuesto"} == con_detalle, (
        "el archivo de estado y `COMPETENCIAS` no leen el detalle de las mismas competencias"
    )
    # Penal se busca y no se abre: es la distinción que la tabla existe para no perder.
    assert set(MODULOS) - con_detalle == {
        n for n, e in competencias.items() if e["estado"] == "medido-no-expuesto"
    }


def test_la_pagina_de_verificacion_publica_las_dos_tablas_de_estado():
    """Los datos sirven si alguien los ve: la página tiene que incluir las tablas generadas.

    Sin esto, el archivo de estado y sus guardias podrían quedar perfectos y la página
    publicada seguir mostrando una tabla vieja escrita a mano, que es exactamente el problema
    que este cambio vino a cerrar.
    """
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    for familia in ("buscadores", "competencias"):
        assert f"_generado/estado-{familia}.md" in pagina, (
            f"la página dejó de incluir la tabla de estado de {familia}"
        )


def test_toda_ruta_de_documento_que_el_cliente_acepta_esta_nombrada():
    """`obtener_documento` rechaza lo que no esté en `DOCUMENTOS`, así que esa tabla es la
    lista de lo que el servidor puede entregar, y la página que dice qué entrega la plataforma
    tiene que nombrarlas todas.

    Doce de las entonces veinticinco no estaban: la sección se escribió cuando eran seis, todas
    de civil, y cada competencia nueva agregó las suyas sin volver a la página. Quien la leyera
    para saber qué puede pedir veía menos de la mitad. Hoy son veintisiete, y ese número no se
    escribe acá: el guardia recorre la tabla.
    """
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
    faltan = sorted(
        f"{competencia}:{ruta}"
        for competencia, rutas in DOCUMENTOS.items()
        for ruta in rutas
        # La tabla de civil las escribe con su carpeta delante (`civil/documentos/docu.php`) y
        # las demás sueltas. Las dos formas nombran la ruta, que es lo que este guardia mide.
        if not re.search(rf"`(?:[\w/]*/)?{re.escape(ruta)}`", pagina)
    )
    assert not faltan, (
        f"`obtener_documento` acepta estas rutas y `verificacion` no las nombra: {faltan}"
    )


def test_lo_medido_de_penal_no_se_pierde():
    """Penal se lee, y no por la ruta que lleva su nombre.

    Lo caro de esa medición tampoco son las cifras: es que `penal/modal/causaPenal.php`
    responde 200 con los cuatro paneles, sus encabezados y CERO filas. Quien lo mida de nuevo
    sin esta advertencia va a concluir que las causas penales no publican nada, que es la misma
    forma del falso negativo que ya apareció con los audios y con los anexos.

    Y los tres datos que un mapeo futuro no puede deducir de las otras competencias: los `id`
    genéricos, que sus litigantes no traen RUT, y que `relaciones` existe con dos formas
    distintas según la ruta.
    """
    # Barre las tres páginas Y el código: la razón vieja ("ningún panel suyo está medido")
    # sobrevivió en la referencia y en un comentario de `server.py` después de que la decisión
    # se tomara, y este guardia miraba una sola página.
    razon_vieja = "ningún panel suyo está medido"
    donde = [*PROSA, *sorted((RAIZ / "src" / "mcp_pjud").glob("*.py"))]
    quedan = [str(p.relative_to(RAIZ)) for p in donde if razon_vieja in _texto(p)]
    assert not quedan, (
        f"{quedan} explica el rechazo de penal por falta de medición, y se midió: queda fuera "
        "por decisión. La copia que el modelo lee es la descripción, no la página"
    )

    pagina = " ".join(_texto(RAIZ / "docs" / "verificacion.md").split())
    for afirmacion in (
        "queda fuera de alcance",
        "detalleCausaPenalUnificado",
        "unificado/modal/causaUnificado.php",
        "**Pedirle el detalle a `penal/modal/causaPenal.php` responde 200 con una carcasa vacía.**",
        "Los `id` de los paneles son genéricos",
        "Los litigantes NO traen RUT",
        "`relaciones` no existe en ninguna otra",
    ):
        assert afirmacion in pagina, (
            f"`verificacion.md` dejó de decir {afirmacion!r} sobre el detalle de penal"
        )

    # Y la corrección sobre el captcha, que es lo que impide repetir una conclusión errónea:
    # el token está en el JavaScript de las SEIS rutas de detalle, incluida la de civil, que
    # este proyecto lee sin ninguno.
    js = _texto(RAIZ / "tests" / "fixtures" / "consultaUnificada.html")
    con_token = {
        m.group(1)
        for m in re.finditer(r"url\s*:\s*'[^']*?/(\w+/modal/causa\w+\.php)'", js)
        if "tokenCaptcha" in js[m.start() : m.start() + 400]
    }
    assert len(con_token) > 1, (
        f"sólo {sorted(con_token)} adjunta token de captcha en el JavaScript. Si de verdad "
        "quedara una sola, la afirmación de la página sobre el captcha hay que reescribirla"
    )
    assert "civil/modal/causaCivil.php" in con_token, (
        "la página dice que el token aparece hasta en la ruta de civil, que se lee sin ninguno"
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


def test_la_verificacion_afirma_solo_pdf_y_las_fixtures_lo_sostienen():
    """De esa afirmación cuelga `_MAGIA_PDF`, que rechaza en duro lo que no empiece en `%PDF-`.

    Si una fixture llega a traer evidencia de otro formato y nadie lo mira, el documento de
    trabajo sigue diciendo "sólo PDF" y la implementación que salga de él rechaza un documento
    real informando que la referencia caducó. Se deriva de las fixtures, que es donde la página
    dice haberlo buscado.
    """
    pagina = _texto(RAIZ / "docs" / "verificacion.md")
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
    # Normalizado: la frase va envuelta y el salto cae en medio.
    assert f"**{marcas}** veces con el icono `fa-file-pdf-o`" in " ".join(pagina.split()), (
        f"el cuaderno principal de C-1156-2026 marca {marcas} enlaces con `fa-file-pdf-o` y la "
        "página dice otra cosa"
    )


def test_el_umbral_de_lo_embebido_es_exactamente_una_respuesta():
    """La referencia afirma una igualdad, y una igualdad se comprueba o no se escribe.

    Es la razón por la que el tope va sobre la respuesta entera y no sobre cada pieza: un
    documento justo en el límite gasta el presupuesto completo. Si alguien mueve
    `LIMITE_EMBEBIDO` o `CARACTERES_DE_UNA_RESPUESTA`, la frase pasa a describir una aritmética
    que ya no es la del código, y ahí el umbral deja de tener la justificación que dice tener.
    """
    from mcp_pjud.client import CARACTERES_DE_UNA_RESPUESTA
    from mcp_pjud.server import LIMITE_EMBEBIDO

    en_base64 = -(-LIMITE_EMBEBIDO // 3) * 4
    assert en_base64 == CARACTERES_DE_UNA_RESPUESTA, (
        f"el umbral ya no es una respuesta entera: {en_base64} contra "
        f"{CARACTERES_DE_UNA_RESPUESTA}. La referencia afirma que son exactamente iguales"
    )
    dicho = (
        f"**{miles(LIMITE_EMBEBIDO)} bytes en base64 son exactamente "
        f"{miles(en_base64)} caracteres**"
    )
    assert dicho in " ".join(_texto(RAIZ / "docs" / "herramientas.md").split()), (
        f"la referencia dejó de decir la igualdad que justifica el umbral: {dicho}"
    )


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
    # actuaciones en la Historia, y `obtener_detalle_causa` sólo aquellas cuyo panel está
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


#: Qué papel hace `tribunal`/`corte` en cada herramienta que los declara. Son tres, y decirlos
#: con una sola descripción costó datos: la de las búsquedas de nombre viajaba en las seis, y
#: una sesión leyó ahí que omitir el tribunal "AMPLÍA los resultados", lo omitió en una
#: búsqueda por rol, y recibió 43 causas de 43 personas distintas por preguntar por una.
PAPELES_DE_LA_ACOTACION = {
    # Acotan una búsqueda que puede devolver muchas: la plataforma los exige según competencia.
    "acota": {
        "buscar_causa_por_nombre",
        "buscar_causa_por_rut_juridica",
        "buscar_causa_por_fecha",
    },
    # Busca por rol, que no identifica una causa: omitirlos barre en vez de ampliar.
    "rol": {"buscar_causa_por_rit"},
    # Devuelven UNA causa: sin ellos la llamada falla por ambigüedad.
    "desambigua": {"obtener_actuaciones_receptor", "obtener_detalle_causa"},
    # `listar_tribunales` recibe `corte` con otro sentido: no acota una búsqueda de causas,
    # dice de qué corte se quieren los tribunales.
    "otro": {"listar_tribunales"},
}


def test_toda_herramienta_que_pide_tribunal_o_corte_declara_para_que(expuestas):
    """La tabla de arriba tiene que cubrir a todas, y ése es el guardia.

    El anterior recorría las herramientas y le exigía a cada una la frase de las búsquedas de
    nombre. Por construcción no podía notar dónde esa frase no aplica: una herramienta nueva
    que devolviera una sola causa pasaba el test copiando una explicación equivocada.
    """
    declaran = {
        n
        for n, h in expuestas.items()
        if {"tribunal", "corte"} & set((h.input_schema or {}).get("properties", {}))
    }
    clasificadas = set().union(*PAPELES_DE_LA_ACOTACION.values())
    assert declaran <= clasificadas, (
        f"estas herramientas piden `tribunal` o `corte` y no dicen para qué: "
        f"{sorted(declaran - clasificadas)}. Cada papel quiere otra descripción"
    )
    assert clasificadas <= declaran, (
        f"la tabla clasifica herramientas que ya no piden ninguno de los dos: "
        f"{sorted(clasificadas - declaran)}"
    )


def test_las_busquedas_dicen_que_campos_son_de_una_sola_competencia(expuestas):
    """Lo que se perdió al despojar los esquemas de salida tiene que estar en otro lado.

    La prosa por campo dejó de viajar para que el catálogo entre en la ventana del cliente, y
    era justo ahí donde decía "Sólo en penal y cobranza". Sin eso, cuatro campos en nulo se
    leen como que la causa no los tiene: es el falso negativo de siempre, corrido del parser a
    la descripción.

    Se deriva del modelo y no de una lista escrita acá: un campo nuevo de una sola competencia
    tiene que aparecer solo en las cuatro descripciones o este guardia se cae.
    """
    de_una_competencia = [
        n
        for n, campo in CausaEncontrada.model_fields.items()
        if (campo.description or "").startswith("Sólo en")
    ]
    assert de_una_competencia, "el modelo dejó de declarar campos de una sola competencia"

    for nombre_h in PAPELES_DE_LA_ACOTACION["acota"] | PAPELES_DE_LA_ACOTACION["rol"]:
        descripcion = expuestas[nombre_h].description or ""
        for campo in de_una_competencia:
            assert f"`{campo}`" in descripcion, (
                f"{nombre_h}: la descripción no nombra {campo!r}, que sólo publica una "
                "competencia. En nulo se lee como que la causa no lo tiene"
            )
        assert "obtener_detalle_causa" in descripcion, (
            f"{nombre_h}: la descripción no dice dónde están la historia y las partes, que el "
            "listado no trae"
        )
        # El puente del listado al detalle: el rol se repite entre competencias y entre
        # juzgados, así que mandar a llamar el detalle "con el mismo rol" deja que use su
        # `competencia` por defecto y abra una causa ajena que se ve perfectamente bien.
        assert "`competencia`" in descripcion, (
            f"{nombre_h}: manda al detalle sin decir que hay que repetir la competencia, y el "
            "detalle asume civil"
        )
        # Y la búsqueda ofrece competencias que el detalle rechaza: sin la salvedad, después
        # de una búsqueda ahí el modelo hace una llamada que falla siempre.
        sin_detalle = sorted(set(MODULOS) - set(_CON_DETALLE))
        aviso = next((f for f in descripcion.split(".") if "no hay detalle" in f), "")
        assert aviso, f"{nombre_h}: no dice qué competencias no tienen detalle"
        # El listado publica el NOMBRE del tribunal y el detalle exige el CÓDIGO. Sin decir de
        # dónde sale, "repite el tribunal de la fila" manda a inventar un número.
        for resolutor in ("listar_tribunales", "listar_cortes"):
            assert resolutor in descripcion, (
                f"{nombre_h}: manda a repetir el tribunal o la corte y no dice que el listado "
                f"publica el nombre y el código sale de `{resolutor}`"
            )
        # Y ese consejo no vale en todas: suprema no se acota por ninguno de los dos, y su
        # código no existe (`listar_cortes` enumera las Cortes de Apelaciones). Sin la
        # salvedad, el modelo busca un número que no hay y se detiene antes del detalle.
        # Se busca dentro de la frase de la salvedad y no en toda la descripción: "suprema"
        # aparece igual en la lista de campos de una sola competencia, así que el guardia
        # ancho pasa aunque la salvedad no exista. Medido: se puso verde sin ella.
        salvedad = next((f for f in descripcion.split(".") if "que resolver" in f), "")
        assert salvedad, f"{nombre_h}: no dice dónde no hay código que resolver"
        for competencia in (n for n in MODULOS if COMPETENCIAS[n].acota_por is None):
            assert competencia in salvedad, (
                f"{nombre_h}: {competencia!r} no se acota por tribunal ni por corte y la "
                "descripción manda a resolver un código que no existe"
            )
        # La salvedad es la que enumera qué se repite ahí, así que enumerarlo de menos es
        # peor que no decirlo: decía "bastan tipo, rol y año", y `competencia` omitida cae en
        # su valor por defecto, que es civil. Se comprueba DENTRO de la frase porque el
        # literal aparece igual dos oraciones antes, y el guardia ancho pasaba con la
        # enumeración corta puesta.
        assert "competencia" in salvedad, (
            f"{nombre_h}: la salvedad enumera qué repetir y deja fuera la competencia, que "
            "omitida vale civil y abre el mismo rol de otra"
        )
        for competencia in sin_detalle:
            assert competencia in aviso, (
                f"{nombre_h}: {competencia!r} no tiene detalle y el aviso no lo nombra"
            )


#: Los otros dos identificadores opacos que la plataforma emite, y de los que sólo se sabe que
#: existen. Se nombran acá para que el guardia pueda distinguir a cuál se le atribuye una
#: duración: dárselas por iguales es lo que haría publicar una cifra que nadie midió.
TOKENS_SIN_MEDIR = ("documento_referencia", "Cuaderno.referencia")

#: Cómo se nombra en la prosa el token que SÍ se midió. Sólo el nombre del campo: "del
#: listado" es una frase suelta que puede venir DESPUÉS de nombrar otro token
#: ("`documento_referencia` se obtiene del listado y dura 30 minutos"), y ahí quedaba haciendo
#: pasar por medido justamente al que no lo está.
TOKEN_MEDIDO = ("CausaEncontrada.referencia",)

#: Cuántos caracteres cuentan como "al lado" al atribuirle una duración a un token. En la
#: tabla de `verificacion.md` los tres caben en menos que esto, y ahí lo que decide es cuál
#: queda más cerca; en la prosa suelta alcanza para cruzar el corte de línea.
CERCA = 200


def test_la_duracion_de_la_referencia_es_la_que_el_token_declara():
    """Son TRES tokens y sólo uno está medido; aplanarlos haría la documentación más falsa.

    El JWT del listado declara `exp - iat` y ahí sale la cifra. De `documento_referencia` y de
    `Cuaderno.referencia` no se midió nada, así que su prosa NO se deriva de la constante y
    tiene que seguir diciendo que no se midió: borrar esa frase para que las tres digan lo
    mismo se siente limpieza y es una afirmación inventada.

    También se cuida el verbo. "Caduca a los N minutos" afirma lo que hace la plataforma;
    medido está lo que el token DICE, y las dos cosas se separan por una petición que nadie
    hizo.
    """
    minutos = SEGUNDOS_DECLARADOS_POR_LA_REFERENCIA // 60
    fuentes = [*PROSA, *(RAIZ / "src" / "mcp_pjud").glob("*.py")]

    citan = [p for p in fuentes if f"{minutos} minutos" in _texto(p)]
    assert citan, f"ninguna fuente cita los {minutos} minutos que el token declara"

    # No basta con que ALGUNA diga la cifra buena: así, una página que cambie a 20 minutos
    # deja el guardia verde porque las otras dos siguen bien. Se mira cada mención de una
    # duración que hable de una referencia.
    #
    # Y se mira a qué token se la atribuye, porque no todas son de la misma. La tabla de
    # `verificacion.md` pone los tres a menos de doscientos caracteres, así que una ventana
    # sola le daría a uno la cifra del otro: el día que se mida el del cuaderno, documentarlo
    # bien pondría la suite en rojo contra la constante equivocada.
    def a_quien_se_lo_atribuye(texto: str, posicion: int) -> str | None:
        """Qué token nombra el texto justo ANTES de la duración, si nombra alguno.

        Antes y no "el más cercano": en la tabla de `verificacion.md` la fila del token medido
        termina con su cifra y la del siguiente empieza a 49 caracteres, más cerca que el
        nombre de su propia fila. Quien escribe nombra el token y después dice cuánto dura.

        Sobre `_legible`, que junta los literales adyacentes y colapsa los saltos: así el corte
        de línea a noventa y ocho columnas deja de partir la frase, que es por donde se colaba.
        """
        candidatos = [
            (texto.rfind(nombre, max(0, posicion - CERCA), posicion), nombre)
            for nombre in (*TOKENS_SIN_MEDIR, *TOKEN_MEDIDO)
        ]
        encontrados = [(donde, nombre) for donde, nombre in candidatos if donde != -1]
        return max(encontrados)[1] if encontrados else None

    duracion = re.compile(r"(\d+)\s+minutos")
    for fuente in fuentes:
        texto = _legible(fuente)
        for mencion in duracion.finditer(texto):
            de_quien = a_quien_se_lo_atribuye(texto, mencion.start())
            assert de_quien not in TOKENS_SIN_MEDIR, (
                f"{fuente.relative_to(RAIZ)} le pone una duración a `{de_quien}`, y de ése no "
                "se midió ninguna: sólo se leyó el `exp` del listado"
            )
            contexto = texto[max(0, mencion.start() - CERCA) : mencion.end() + CERCA].lower()
            if "referencia" not in contexto:
                continue
            assert int(mencion.group(1)) == minutos, (
                f"{fuente.relative_to(RAIZ)} dice que una referencia dura "
                f"{mencion.group(1)} minutos y el token declara {minutos}"
            )

    afirman_de_mas = [
        str(p.relative_to(RAIZ)) for p in citan if f"caduca a los {minutos}" in _texto(p).lower()
    ]
    assert not afirman_de_mas, (
        f"Estas dicen que la referencia CADUCA a los {minutos} minutos: {afirman_de_mas}. "
        "Medido está lo que el token declara; que la plataforma lo rechace ahí no se probó"
    )

    # El de los documentos, con la salvedad que lo distingue.
    sin_medir = RAIZ / "src" / "mcp_pjud" / "server.py"
    assert "Cuánto dura no se midió" in _texto(sin_medir), (
        "`documento_referencia` dejó de decir que su duración no se midió, y es el único aviso "
        "que impide leerle la del listado"
    )


def test_el_esquema_dice_donde_el_rol_no_lleva_nada_adelante(expuestas):
    """El rol se publica de tres formas y el esquema nombraba dos.

    En civil va una letra, en apelaciones y penal el libro, y en suprema no va nada. Sin la
    tercera dicha, el modelo manda una letra donde no corresponde: el rol esperado queda en
    `X-999999-2020`, no calza ninguna fila, y el error habla de revisar `tipo` sin decir que
    ahí va vacío.

    Sale de `parser.COMPETENCIAS` y no de una lista escrita acá, igual que las otras dos.
    """
    sin_prefijo = sorted(n for n in MODULOS if COMPETENCIAS[n].rol_sin_prefijo)
    assert sin_prefijo, "si ninguna publicara el rol pelado, la salvedad sobra"
    assert set(MODULOS) - set(sin_prefijo), (
        "si todas lo publicaran pelado, lo que sobra es el resto de la descripción"
    )

    for nombre_h, h in expuestas.items():
        tipo = (h.input_schema or {}).get("properties", {}).get("tipo", {}).get("description", "")
        if not tipo:
            continue
        for competencia in sin_prefijo:
            assert competencia in tipo, (
                f"{nombre_h}: en {competencia!r} el rol no lleva nada adelante y la "
                "descripción de `tipo` no lo dice, así que el modelo manda una letra"
            )

    # Y la referencia publicada, que se escribe a mano y decía "Letra del rol" en las dos
    # tablas. Quien arme la llamada leyendo esa página manda un prefijo igual, aunque el
    # esquema ya no se lo pida.
    filas = [
        linea
        for linea in _texto(RAIZ / "docs" / "herramientas.md").splitlines()
        if linea.startswith("| `tipo` |")
    ]
    assert filas, "la referencia dejó de describir `tipo` en sus tablas de parámetros"
    for fila in filas:
        for competencia in sin_prefijo:
            assert competencia in fila, (
                f"la referencia describe `tipo` sin decir que en {competencia!r} va vacío: {fila}"
            )


def test_el_esquema_dice_que_competencia_exige_que_acotacion(expuestas):
    """Y no puede decirlo a mano: se deriva de `parser.COMPETENCIAS`.

    Sin esto, quitar `tribunal` de la firma dejaría al modelo sin saber cuándo hace falta, y
    la llamada fallaría en el cliente con un error que el modelo atribuye a la plataforma.
    """
    from mcp_pjud.server import ACOTACION, DIRECTIVA

    for nombre in MODULOS:
        assert nombre in ACOTACION, f"la regla de acotación no nombra a {nombre!r}"
    # Viajaba en la directiva, que no cabe en los 2.048 bytes que el cliente deja: se leía a
    # medias o no se leía. Va con las tres búsquedas que la obedecen, y en ninguna otra.
    for nombre_h in PAPELES_DE_LA_ACOTACION["acota"]:
        assert ACOTACION in (expuestas[nombre_h].description or ""), (
            f"{nombre_h} tiene que traer la regla de acotación: es la que dice con qué acotar "
            "según la competencia, y el modelo la lee al elegir la herramienta"
        )
    assert ACOTACION not in DIRECTIVA, (
        "la regla volvió a la directiva, que tiene 2.048 bytes para todo el servidor"
    )

    for nombre_h in PAPELES_DE_LA_ACOTACION["acota"]:
        propiedades = (expuestas[nombre_h].input_schema or {}).get("properties", {})
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


def test_donde_el_rol_no_identifica_una_causa_el_esquema_no_habla_de_acotar(expuestas):
    """La frase que costó las 43 causas, prohibida donde no aplica.

    `buscar_causa_por_rit` y las dos que devuelven una sola causa no acotan nada con
    `tribunal`: lo usan para identificar. Ahí "omitirlo AMPLÍA los resultados" es literalmente
    cierto y prácticamente engañoso, y "obligatorio en las búsquedas de nombre" describe otra
    herramienta.

    La cara positiva va contra la constante compartida y no contra una frase escrita acá: el
    error de ambigüedad y esta descripción tienen que decir lo mismo, porque el modelo lee una
    antes de llamar y el otro después.
    """
    from mcp_pjud.server import ACOTACION

    for papel in ("rol", "desambigua"):
        for nombre_h in PAPELES_DE_LA_ACOTACION[papel]:
            propiedades = (expuestas[nombre_h].input_schema or {}).get("properties", {})
            tribunal = propiedades.get("tribunal", {}).get("description", "")
            assert EL_ROL_NO_BASTA in tribunal, (
                f"{nombre_h}: la descripción de `tribunal` no dice por qué el rol no basta, "
                "que es lo único que evita que el modelo lo omita"
            )
            # Y esa razón no vale en todas: apelaciones se desambigua por corte y suprema por
            # ninguno de los dos. Sin la salvedad, el esquema afirma que la llamada falla sin
            # `tribunal` justo donde ese código no existe, y el modelo va a buscar uno.
            for otra in [n for n in MODULOS if COMPETENCIAS[n].acota_por != "tribunal"]:
                assert otra in tribunal, (
                    f"{nombre_h}: `tribunal` no acota {otra!r} y la descripción no lo dice, "
                    "así que afirma que sin él la llamada falla también ahí"
                )
            for prohibida in ("AMPLÍA", "búsquedas de nombre", ACOTACION):
                for campo in ("tribunal", "corte"):
                    descripcion = propiedades.get(campo, {}).get("description", "")
                    assert prohibida not in descripcion, (
                        f"{nombre_h}: la descripción de {campo!r} trae {prohibida[:40]!r}, que "
                        "describe las búsquedas de nombre y no esta herramienta"
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
        # `__mutmut`: bajo `mutmut run` cada método se reescribe en una familia
        # `xǁClaseǁmétodo__mutmut_N` que no empieza con guion bajo, así que este guardia las
        # leía como búsquedas sin exponer y la corrida entera se caía antes de mutar nada.
        if not nombre.startswith("_")
        and "__mutmut" not in nombre
        and nombre not in NO_SON_HERRAMIENTAS
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


def test_los_topes_del_indice_del_documento_son_los_que_aplica_el_codigo():
    """La referencia dice cuántos tramos y cuántos marcadores se enumeran, y esas cifras se
    escriben a mano: son un dato repetido, o sea uno que va a quedar viejo.

    Y quedar viejo acá no es un detalle de redacción. Quien lea "se enumeran hasta 20 tramos"
    y reciba diez concluye que el archivo tiene diez, no que la página está desactualizada.
    """
    from mcp_pjud.client import (
        LARGO_MAXIMO_MARCADOR,
        MAXIMO_MARCADORES,
        MAXIMO_RANGOS,
        PROFUNDIDAD_MARCADORES,
    )

    referencia = " ".join(_texto(RAIZ / "docs" / "herramientas.md").split())
    afirmacion = (
        f"Se enumeran hasta **{MAXIMO_RANGOS}** tramos y hasta **{MAXIMO_MARCADORES}** "
        f"marcadores, bajando **{PROFUNDIDAD_MARCADORES}** niveles, con los títulos "
        f"recortados a **{LARGO_MAXIMO_MARCADOR}** caracteres."
    )
    assert afirmacion in referencia, (
        f"la referencia no dice los topes que el código aplica. Tendría que decir: {afirmacion}"
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


#: Versiones publicadas que la hoja de ruta NO tiene por qué contar, con su razón.
#:
#: Cada entrada se agrega de a una. Que este conjunto crezca sin motivo escrito es la forma
#: barata de que la hoja vuelva a quedarse atrás sin que nada lo diga.
VERSIONES_SIN_SECCION = {
    # La primera. La hoja de ruta empieza donde empezó el trabajo que hubo que planificar, y
    # antes de la 0.2.0 no había nada que planificar todavía.
    "0.1",
}


def test_toda_version_publicada_tiene_su_seccion_en_la_hoja_de_ruta():
    """La hoja se quedó atrás tres veces seguidas y nadie se enteró.

    Cada versión entraba con su entrada en el registro, la suite quedaba verde, y la página que
    dice hacia dónde va el proyecto seguía describiendo el estado de dos versiones antes. Quien
    la lea para evaluar si esto le sirve está leyendo lo que era cierto hace tres publicaciones.

    Las versiones salen del registro y no de una lista escrita acá, que es lo que se quedó
    corto. Los parches (`0.2.1`) no cuentan: los encabezados de la hoja van por versión menor.
    """
    registro = _registro()
    menores = {
        ".".join(v.split(".")[:2]) for v in re.findall(r"^## \[(\d+\.\d+\.\d+)\]", registro, re.M)
    }
    assert len(menores) > 5, f"el barrido del registro encontró {menores}: dejó de ver versiones"

    hoja = _texto(RAIZ / "docs" / "roadmap.md")
    # `\D` y no `[:a-z]`: lo que sigue al número puede ser dos puntos, una letra de hito
    # (`0.7a`) o cualquier otra cosa, y exigir una forma de título convierte un cambio de
    # redacción en un fallo que no dice nada. Lo que sí importa es que NO sea un dígito, o
    # `0.10` se leería como `0.1`.
    titulos = re.findall(r"^#{2,4} (\d+\.\d+)\D", hoja, re.M)
    faltan = sorted(menores - set(titulos) - VERSIONES_SIN_SECCION)
    assert not faltan, (
        f"estas versiones se publicaron y la hoja de ruta no las cuenta: {faltan}. O entra su "
        "sección, o entra a `VERSIONES_SIN_SECCION` con la razón escrita"
    )


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


def test_las_copias_del_estudio_de_llms_txt_dicen_lo_mismo():
    """La cifra está escrita a mano en `ecosistema.md` y en `conf.py`.

    No sale de ningún código, así que ningún guardia puede verificarla: es una fuente externa.
    Lo que sí se puede impedir es que una se corrija y las otras dos queden diciendo otra cosa.

    NO se filtra a las que ya traen la cifra, que es lo que hacía la primera versión: eso
    excluía del chequeo justo a la página que divergía, y se comprobó cambiando el número en
    una de las tres. Se identifican por citar el estudio, no la cifra.
    """
    donde = ("docs/ecosistema.md", "docs/conf.py")
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

    # El `true` es la otra mitad, y vale en las mismas competencias. Vivía sólo en
    # `obtener_actuaciones_receptor`, que acepta civil: quien leyera la historia de cobranza,
    # laboral o apelaciones por el detalle no tenía cómo saber que `true` no prueba nada.
    assert "`true` significa que el sitio lo ofrece" in DIRECTIVA, (
        "la directiva dice cuándo el falso prueba ausencia y no dice que el verdadero no "
        "prueba existencia, que es el mismo error al revés"
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


def test_lo_que_la_hoja_de_ruta_da_por_cerrado_del_protocolo_sigue_siendo_cierto():
    """La tabla de "lo que no se adopta" existe para no volver a medir, y por eso puede mentir.

    Sus filas son afirmaciones sobre el SDK, y `pyproject.toml` no le pone techo a `mcp`: una
    actualización puede volverlas falsas con la suite entera en verde. Peor que una página
    vieja, porque se presenta como una medición que ya no hace falta repetir, así que la
    próxima revisión leería la tabla en vez de medir.

    Cada fila se compara contra su fuente. Las que no dependen del SDK (los iconos por
    herramienta, el esquema de salida apagado) tienen su propio guardia y no se repiten acá.
    """
    from mcp_types.methods import CLIENT_REQUESTS, INPUT_REQUIRED_METHODS, SERVER_REQUESTS
    from mcp_types.version import LATEST_PROTOCOL_VERSION

    hoja = " ".join(_texto(RAIZ / "docs" / "roadmap.md").split())
    assert "lo que no se adopta" in hoja, (
        "desapareció la tabla que este guardia cuida, así que estaría cuidando nada"
    )

    v = LATEST_PROTOCOL_VERSION
    tareas = [m for m, _ in CLIENT_REQUESTS] + [m for m, _ in SERVER_REQUESTS]
    assert not [m for m in tareas if m.startswith("tasks/")], (
        "el SDK ya trae métodos `tasks/*` y la hoja de ruta los da por ausentes: hay que "
        "decidir si se adoptan en vez de que la tabla lo niegue"
    )
    assert not [m for m, r in SERVER_REQUESTS if r == v], (
        f"la revisión {v} ya define peticiones del servidor al cliente, y la tabla dice que "
        "no hay ninguna que adoptar (sampling, roots, elicitación)"
    )
    assert ("subscriptions/listen", v) in CLIENT_REQUESTS, (
        "desapareció `subscriptions/listen`, de la que el SDK deriva `subscribe` y "
        "`listChanged` en el carril moderno: la explicación de la tabla deja de aplicar"
    )
    assert "tools/call" in INPUT_REQUIRED_METHODS, (
        "`InputRequiredResult` dejó de alcanzar a `tools/call`, así que la fila que explica "
        "por qué no se adopta ya no habla de lo que hay"
    )


def test_las_capacidades_del_carril_moderno_no_las_declara_este_servidor():
    """La tabla dice que `subscribe` y `listChanged` los deriva el SDK, no nosotros.

    Se mide por el cable en los dos carriles: en el viejo salen en falso, que es lo que este
    servidor pide, y en el moderno en verdadero sin que nadie los haya pedido. Si algún día
    salen iguales en los dos, la fila deja de ser cierta y hay que decidir qué se declara.
    """
    import asyncio

    from mcp.client import Client
    from mcp_types.version import LATEST_PROTOCOL_VERSION

    from mcp_pjud import server as servidor

    async def capacidades(modo: str) -> dict:
        async with Client(servidor.mcp, mode=modo) as cliente:
            if modo == "legacy":
                saludo = cliente.session.initialize_result
                return saludo.capabilities.model_dump(by_alias=True, exclude_none=True)
            crudo = await cliente.session.send_discover(LATEST_PROTOCOL_VERSION)
            return crudo["capabilities"]

    viejo = asyncio.run(capacidades("legacy"))
    moderno = asyncio.run(capacidades(LATEST_PROTOCOL_VERSION))

    assert viejo["resources"]["subscribe"] is False, (
        "el carril viejo declara `subscribe`, y este servidor no atiende suscripciones"
    )
    assert moderno["resources"]["subscribe"] is True, (
        "el carril moderno dejó de declarar `subscribe`: la hoja de ruta explica que el SDK lo "
        "deriva de servir `subscriptions/listen`, y esa explicación ya no aplica"
    )
    assert "extensions" not in moderno, (
        "el servidor empezó a anunciar extensiones (SEP-2133) y la hoja de ruta dice que no "
        "define ninguna"
    )


def test_el_codigo_no_importa_nada_que_no_este_declarado():
    """Una dependencia transitiva es una decisión ajena, y cuando cambia el servidor muere al
    importar, antes de la primera línea de trabajo.

    Ya pasó dos veces: `anyio` entraba de prestado por `mcp` y se declaró por eso, y
    `mcp_types` se importó directo aunque quien lo trae es `mcp`, que lo fija en una versión
    exacta. La segunda no la vio ningún guardia, por eso existe éste.

    Mira los imports de verdad y no una lista escrita al lado, que sería otra copia que se
    queda vieja.

    Compara el nombre del paquete con el del módulo, que en las cinco dependencias de hoy es
    el mismo. Si algún día entra una donde no lo sea (`python-dateutil` se importa `dateutil`),
    esto se pone rojo con una dependencia legítima y lo que falta es la equivalencia, no la
    declaración.
    """
    import ast
    import sys

    declaradas = {
        re.split(r"[<>=!\[;\s]", d)[0].replace("-", "_").lower()
        for d in tomllib.loads(_texto(RAIZ / "pyproject.toml"))["project"]["dependencies"]
    }
    propias = {"mcp_pjud", "__future__"}

    # `rglob` y no `glob`: hoy el paquete es plano y el día que deje de serlo este guardia
    # no se entera, que es como se le escapó `mcp_types`.
    for modulo in sorted((RAIZ / "src" / "mcp_pjud").rglob("*.py")):
        arbol = ast.parse(modulo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                raices = {a.name.split(".")[0] for a in nodo.names}
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                raices = {nodo.module.split(".")[0]}
            else:
                continue
            for raiz in raices - propias - set(sys.stdlib_module_names):
                assert raiz.replace("-", "_").lower() in declaradas, (
                    f"`{modulo.name}` importa `{raiz}`, que no está en las dependencias del "
                    f"paquete: hoy entra de prestado y el día que deje de entrar el servidor "
                    f"muere al importar"
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
        "diligencias",
        "materias",
        "exhortos",
        "piezas_exhorto",
        "causa_de_origen",
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

    copias = {f.name: _legible(f) for f in [*PROSA, *(RAIZ / "src" / "mcp_pjud").glob("*.py")]}
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


def test_nadie_afirma_que_las_diligencias_de_cobranza_no_se_leen():
    """`diligenciaCob` pasó de no leerse a leerse, y la afirmación vieja vivía en SIETE copias.

    La referencia, la hoja de ruta, la página de verificación, la del ecosistema, el mensaje
    con que el cliente rechaza actuaciones en cobranza, el esquema que el servidor publica y
    el contrato del detalle. Al mapear el panel, la suite entera siguió verde: ningún guardia
    miraba esas frases, así que la documentación podía seguir diciendo que el dato no se lee
    mientras el servidor lo entregaba.

    Se barre la prosa Y el código, por lo de siempre: la copia que un modelo le relata a un
    abogado es el mensaje de error, no la página.
    """
    from mcp_pjud.parser import parse_diligencias

    assert COMPETENCIAS["cobranza"].diligencias is not None, (
        "si el panel dejara de estar mapeado, este guardia sobra y hay que retirarlo junto con "
        "el campo, no dejarlo pasando en vacío"
    )
    assert parse_diligencias(_texto(RAIZ / "tests" / "fixtures" / "detalle_cobranza.html")), (
        "la fixture de cobranza dejó de traer filas en `diligenciaCob`"
    )

    # Las tres formas medidas de decirlo, incluida la que no nombra el panel: la referencia
    # decía "un panel propio ... que este proyecto todavía no lee" y el servidor "otro panel
    # que este servidor todavía no lee", sin el identificador en ninguna de las dos.
    contradicciones = (
        r"`?diligenciaCob`?[^.]{0,140}?(?:todav[ií]a )?no (?:se )?lee",
        r"no (?:se )?lee[^.]{0,140}?`?diligenciaCob`?",
        r"(?:otro|propio|aparte|distinto) panel[^.]{0,140}?(?:todav[ií]a )?no (?:se )?lee",
        r"panel (?:otro|propio|aparte|distinto)[^.]{0,140}?(?:todav[ií]a )?no (?:se )?lee",
    )
    # El registro de cambios queda fuera y no por comodidad: sus entradas dicen qué cambió en
    # una versión, y la de la 0.3.0 era cierta cuando se publicó. Editarla para que este
    # guardia pase falsearía el registro, que es lo mismo que ya se decidió con la tabla de
    # user agents medidos.
    fuentes = [f for f in PROSA if f.name != "CHANGELOG.md"]
    culpables = {
        f.name: [p for p in contradicciones if re.search(p, _legible(f))]
        for f in [*fuentes, *(RAIZ / "src" / "mcp_pjud").glob("*.py")]
        if any(re.search(p, _legible(f)) for p in contradicciones)
    }
    assert not culpables, (
        f"{sorted(culpables)} sigue diciendo que las diligencias de cobranza no se leen, y el "
        "detalle las entrega en `diligencias`. Quien lo lea va a buscar el dato en el "
        "expediente teniendo la respuesta a mano."
    )

    # Y la otra forma de decir lo mismo, que no usa el verbo: figurar entre los canales
    # mapeados y nunca ejecutados. Ahí estaba, encabezando la lista.
    sin_ejecutar = (
        _texto(RAIZ / "docs" / "verificacion.md")
        .split("### Mapeado pero nunca ejecutado", 1)[1]
        .split("###", 1)[0]
    )
    assert "diligenciaCob" not in sin_ejecutar, (
        "`diligenciaCob` se lee y sigue listado entre los canales mapeados y nunca ejecutados"
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
    # Normalizado y con la frase, no sólo el número: la página lo cita dos veces (la revisión
    # que el SDK conoce, y la que se pidió al medir), así que buscarlo suelto deja pasar que
    # una de las dos quede vieja mientras la otra la rescata.
    referencia = " ".join(_texto(RAIZ / "docs" / "herramientas.md").split())
    assert f"conoce hasta **{LATEST_PROTOCOL_VERSION}**" in referencia, (
        f"la referencia nombra otra revisión; el SDK trae {LATEST_PROTOCOL_VERSION}"
    )

    # Y la del SALUDO, que es la que de verdad negocia un cliente. Nombrar sólo la más nueva
    # decía que este servidor habla una revisión que por stdio no habla: todos los clientes
    # que la guía documenta lo levantan como proceso aparte, y ahí el saludo llega una menos.
    from mcp_types.version import LATEST_HANDSHAKE_VERSION

    assert LATEST_HANDSHAKE_VERSION in referencia, (
        f"la referencia no nombra la revisión que se negocia por stdio, que es "
        f"{LATEST_HANDSHAKE_VERSION}: es la que obtiene cualquier cliente de los documentados"
    )


def test_la_referencia_cita_la_pista_de_frescura_que_de_verdad_viaja():
    """Los dos valores de la pista viven en el código y la página los copia.

    Es la afirmación que un cliente puede comprobar contra el cable en un segundo, así que una
    página que anuncie otra frescura se nota enseguida y no es lo que se quiere que se note.
    """
    from mcp_pjud.server import CACHE_DEL_CATALOGO

    referencia = " ".join(HERRAMIENTAS.split())
    for escrito in (
        f"`ttlMs: {CACHE_DEL_CATALOGO.ttl_ms}`",
        f"`cacheScope: {CACHE_DEL_CATALOGO.scope}`",
    ):
        assert escrito in referencia, (
            f"la referencia no cita {escrito}, que es lo que sale hoy en los catálogos"
        )

    # Y CUÁLES la llevan, que es la mitad que se quedó vieja: la página decía "`tools/list`,
    # y es la única" cuando ya la llevaban los cinco.
    from mcp_pjud.server import CATALOGOS_CON_PISTA

    for metodo in sorted(CATALOGOS_CON_PISTA):
        assert f"`{metodo}`" in referencia, (
            f"la referencia no nombra `{metodo}` entre los catálogos que llevan pista"
        )


def test_la_referencia_nombra_todo_lo_que_se_completa():
    """Un argumento completable que la página no nombra es una función que nadie va a usar.

    Se deriva del mapa del servidor y no de una frase, porque una frase se queda vieja en cuanto
    entra un argumento más: es el mismo descuido que dejó la página diciendo que la pista de
    frescura iba en un solo catálogo.

    Se mira sólo en los párrafos que hablan de `completion/complete`: los nombres aparecen
    también en las tablas de argumentos, así que buscarlos en la página entera pasaría con la
    función sin documentar.
    """
    from mcp_pjud.server import VALORES_COMPLETABLES

    parrafos = [
        " ".join(bloque.split())
        for bloque in HERRAMIENTAS.split("\n\n")
        if "completion/complete" in bloque
    ]
    assert parrafos, "la referencia no habla de `completion/complete` en ninguna parte"

    donde = " ".join(parrafos)
    for prompt, argumento in VALORES_COMPLETABLES:
        assert f"`{prompt}`" in donde, f"la referencia no dice que `{prompt}` complete argumentos"
        assert f"`{argumento}`" in donde, (
            f"la referencia no nombra `{argumento}` entre lo que se completa"
        )


def test_la_cuenta_de_buscadores_verificados_es_la_del_codigo():
    """Registrar un buscador nuevo y no tocar la prosa deja la página contando de menos.

    Y en esta herramienta contar de menos importa: quien lee "tres de diez" decide si le sirve
    o si tiene que buscar la sentencia por otro lado.
    """
    from mcp_pjud.juris import BUSCADORES

    # Dos cuentas distintas, y la confusión entre ellas ya se coló una vez: los MEDIDOS son los
    # que tienen identificador anotado, incluido el que se decidió no ofrecer, y los EXPUESTOS
    # son los que el cliente acepta. La prosa decía "siete verificados y seis expuestos" con
    # siete en la tabla y ocho medidos, y el guardia sólo miraba la primera mitad de la frase.
    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    dicho = re.search(
        r"Están verificados (\w+) de los \w+ buscadores y se exponen (\w+):", referencia
    )
    assert dicho, "la referencia ya no dice cuántos buscadores están verificados y expuestos"
    assert dicho.group(1) == EN_LETRAS[len(IDENTIFICADORES_MEDIDOS)], (
        f"la referencia dice {dicho.group(1)} buscadores medidos y el código anota "
        f"{len(IDENTIFICADORES_MEDIDOS)}"
    )
    assert dicho.group(2) == EN_LETRAS[len(BUSCADORES)], (
        f"la referencia dice {dicho.group(2)} buscadores expuestos y el cliente acepta "
        f"{len(BUSCADORES)}"
    )
    for nombre in BUSCADORES:
        assert f"**{nombre}**" in referencia, f"la referencia no nombra el buscador {nombre!r}"


#: Los archivos que SÍ tienen que contar los buscadores. Sin esta lista el barrido de abajo se
#: pone verde borrando la frase, que es la forma más barata de "arreglar" un guardia.
CUENTAN_BUSCADORES = (
    "AGENTS.md",
    "docs/herramientas.md",
    "docs/roadmap.md",
    "docs/verificacion.md",
    "src/mcp_pjud/juris.py",
)


def _sin_lo_ya_publicado(f: Path) -> str:
    """El registro de cambios es histórico: cada versión describe el estado de SU día.

    Congelar esas cifras contra el código de hoy pondría en rojo una entrada correcta de hace
    tres versiones. Lo único que tiene que cuadrar con el código es lo que está por publicarse.
    """
    texto = _texto(f)
    if f.name != "CHANGELOG.md":
        return texto
    return texto.split("\n## [0.")[0]


def test_ninguna_pagina_cuenta_los_buscadores_por_su_cuenta():
    """Ocho medidos y siete expuestos son dos cuentas pegadas, y las dos son legales.

    Por eso el guardia de `herramientas` no alcanza: mira UNA frase de UNA página, y las cifras
    viejas quedaron regadas. `AGENTS.md` seguía diciendo "sólo tres de los diez están medidos",
    que es lo que otro agente lee como instrucción, y la hoja de ruta contaba tres verificados
    en un párrafo y siete en el de más arriba.

    Lo que discrimina las dos cuentas no es el número sino el verbo que lo acompaña, así que se
    busca el más cercano en las dos direcciones: "anda contra siete" va delante, "ocho están
    medidos" va detrás.
    """
    medidos, expuestos = len(IDENTIFICADORES_MEDIDOS), len(BUSCADORES)
    archivos = [*PROSA, *sorted((RAIZ / "src" / "mcp_pjud").glob("*.py"))]
    con_cuenta, malas = set(), []
    for f in archivos:
        relativo = f.relative_to(RAIZ).as_posix()
        texto = _legible(f) if f.suffix == ".py" else _sin_lo_ya_publicado(f)
        for m in re.finditer(r"(\w+) de los diez", texto):
            escrito = m.group(1).lower()
            if escrito not in EN_LETRAS.values():
                continue
            con_cuenta.add(relativo)
            antes = texto[max(0, m.start() - 90) : m.start()]
            despues = texto[m.end() : m.end() + 90]
            exponer = _distancia(r"expon|ofrec|anda contra|acepta|consulta", antes, despues)
            medir = _distancia(r"midi|medid|verificad", antes, despues)
            toca = expuestos if exponer < medir else medidos
            if escrito != EN_LETRAS[toca]:
                malas.append(f"{relativo}: dice {escrito!r} donde el código anota {toca}")
    assert not malas, "cuentas de buscadores que el código contradice: " + "; ".join(malas)
    faltan = sorted(set(CUENTAN_BUSCADORES) - con_cuenta)
    assert not faltan, f"{faltan} dejó de contar los buscadores, así que este guardia no lo mira"


def _distancia(verbos: str, antes: str, despues: str) -> int:
    """Cuán lejos queda el verbo más cercano, mirando para los dos lados."""
    atras = [m.end() for m in re.finditer(verbos, antes)]
    adelante = re.search(verbos, despues)
    return min(
        len(antes) - atras[-1] if atras else 10_000,
        adelante.start() if adelante else 10_000,
    )


def test_donde_ocultas_trae_numero_lo_dice_la_tabla_de_buscadores():
    """`ocultas` en nulo es la diferencia entre "no hay nada reservado" y "acá no se puede
    saber", y la página decía en cuáles buscadores pasa cada cosa.

    Contaba dos de tres cuando ya eran seis de siete: la frase se escribió cuando los
    buscadores eran tres, y cada uno de los cuatro que entraron después llegó con la bandera en
    falso sin que nadie volviera a la página. Quien la leyera concluiría que en `civiles` un
    cero significa "no hay nada reservado", que es justo lo contrario.
    """
    con_numero = sorted(n for n, b in BUSCADORES.items() if b.coincidencias_por_consulta)
    referencia = _texto(RAIZ / "docs" / "herramientas.md")
    dicho = re.search(
        r"`ocultas` sólo trae\s+número en (\w+) de los (\w+) buscadores expuestos, `(\w+)`, y en "
        r"los otros (\w+) viene en nulo",
        referencia,
    )
    assert dicho, "la referencia ya no dice en cuáles buscadores `ocultas` trae número"
    assert dicho.group(1) == EN_LETRAS[len(con_numero)]
    assert dicho.group(2) == EN_LETRAS[len(BUSCADORES)]
    assert [dicho.group(3)] == con_numero, (
        f"la referencia nombra {dicho.group(3)!r} y la bandera está puesta en {con_numero}"
    )
    assert dicho.group(4) == EN_LETRAS[len(BUSCADORES) - len(con_numero)]


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
