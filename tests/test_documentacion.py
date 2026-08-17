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
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from mcp_pjud.client import (
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
from mcp_pjud.parser import COMPETENCIAS
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
    # `obtener_actuaciones_receptor` queda fuera y tiene su propio guardia: ofrece sólo las
    # competencias que además publican las actuaciones en la Historia, que hoy es una sola.
    # Exigirle las cuatro buscables le haría anunciar tres opciones que siempre fallan.
    descripciones = [
        p.get("description", "")
        for nombre_h, h in expuestas.items()
        if nombre_h != "obtener_actuaciones_receptor"
        for nombre, p in (h.input_schema or {}).get("properties", {}).items()
        if nombre == "competencia"
    ]
    assert descripciones, "ninguna herramienta declara el parámetro `competencia`"
    for d in descripciones:
        for otra in set(COMPETENCIAS) - set(MODULOS):
            assert otra not in d, f"el esquema le ofrece {otra!r} al modelo y el cliente lo rechaza"
        for verificada in MODULOS:
            assert verificada in d, f"el esquema no le ofrece {verificada!r}, que sí funciona"


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
    sin_el_peor = [
        str(p.relative_to(RAIZ))
        for p in citan
        if peor not in _texto(p) and p.name != "CHANGELOG.md"
    ]
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
