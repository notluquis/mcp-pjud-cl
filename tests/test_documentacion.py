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

import asyncio
import re
import tomllib
from pathlib import Path

import pytest

from mcp_pjud.client import INTERVALO_MINIMO, MODULOS
from mcp_pjud.juris import (
    BUSCADORES,
    FECHA_MEDICION,
    FILAS_MAXIMAS,
    INDEXADAS_MEDIDAS,
    VISIBLES_MEDIDAS,
    miles,
)
from mcp_pjud.server import mcp

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
    for campo in ("visibles", "coincidencias", "ocultas", "condiciones_de_publicacion"):
        assert campo in salida, f"el modelo dejó de declarar `{campo}`"
        assert f"`{campo}`" in HERRAMIENTAS, f"`{campo}` no está en la referencia"


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
PAGINAS_CON_LA_MEDICION = (
    "docs/herramientas.md",
    "docs/roadmap.md",
    "CHANGELOG.md",
)


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
    """Una cifra medida sin fecha no se puede evaluar: quien la lea no sabe si sigue vigente."""
    for p in PROSA:
        t = _texto(p)
        if miles(INDEXADAS_MEDIDAS) in t:
            assert FECHA_MEDICION in t or "16-08-2026" in t or "16 de agosto" in t, (
                f"{p.relative_to(RAIZ)} cita la medición sin decir cuándo se hizo"
            )


def test_los_topes_declarados_coinciden_con_el_codigo():
    """El tope de filas se documenta como rango. Si cambia en el código y no en la página,
    quien lea pedirá un valor que la herramienta rechaza antes de consultar."""
    assert f"de 1 a {FILAS_MAXIMAS}" in HERRAMIENTAS, (
        f"la referencia no declara el tope real de filas ({FILAS_MAXIMAS})"
    )


# -- lo que la documentación promete que está verificado -------------------------


def test_la_documentacion_no_anuncia_competencias_que_el_codigo_rechaza():
    """`MODULOS` es la lista de lo verificado. Anunciar una competencia que el cliente
    rechaza haría que alguien planifique con una función que no existe."""
    assert set(MODULOS) == {"civil"}, (
        "Se amplió MODULOS: hay que actualizar la referencia y el roadmap antes de anunciarlo"
    )
    assert "Sólo `civil` está verificada" in HERRAMIENTAS


def test_la_documentacion_no_anuncia_buscadores_que_el_codigo_rechaza():
    assert set(BUSCADORES) == {"suprema"}, (
        "Se amplió BUSCADORES: hay que actualizar la referencia y el roadmap"
    )
    assert "Sólo el buscador de **Corte Suprema** está verificado" in HERRAMIENTAS


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
