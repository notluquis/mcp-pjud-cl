"""Las fixtures no deben contener datos personales reales.

Las respuestas de la Oficina Judicial Virtual traen RUT y nombres completos de personas
naturales que son parte en juicios. Que ese dato sea consultable en la plataforma no autoriza
a republicarlo en un repositorio público: allá vive detrás de una consulta puntual, y acá
quedaría indexado y permanente. Es un cambio de finalidad.

Si estos tests fallan, corre `uv run python tests/fixtures/anonimizar.py`.
"""

import hashlib
import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

_RUT = re.compile(r"\b(\d{7,8})-([\dkK])\b")
_IDENTIFICADOR_ABOGADO = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{4,}\d{7,8}\b")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")

#: Los RUT ficticios son dígitos repetidos: 11111111-1, 22222222-2, etc.
_FICTICIO = re.compile(r"^(\d)\1{6,7}$")


def _archivos() -> list[Path]:
    archivos = sorted(FIXTURES.glob("*.html"))
    # Sin esto, un glob que no encuentra nada hace pasar todos los tests de abajo.
    # Ya ocurrió una vez durante el desarrollo, con el cwd equivocado.
    assert archivos, f"No se encontró ninguna fixture en {FIXTURES}"
    return archivos


def test_hay_fixtures():
    assert len(_archivos()) >= 3


def test_sin_rut_reales():
    encontrados = {}
    for archivo in _archivos():
        for cuerpo, dv in _RUT.findall(archivo.read_text(encoding="utf-8")):
            if not _FICTICIO.match(cuerpo):
                encontrados.setdefault(archivo.name, set()).add(f"{cuerpo}-{dv}")
    assert not encontrados, (
        f"RUT reales en fixtures: {encontrados}. Corre: uv run python tests/fixtures/anonimizar.py"
    )


def test_sin_identificadores_de_abogado():
    """El campo `Institución` trae APELLIDO + RUT sin dígito verificador.

    Permite reconstruir la cartera completa de un abogado, así que se anonimiza igual.
    """
    encontrados = {}
    for archivo in _archivos():
        for ident in _IDENTIFICADOR_ABOGADO.findall(archivo.read_text(encoding="utf-8")):
            if ident != "ESTUDIO00000000":
                encontrados.setdefault(archivo.name, set()).add(ident)
    assert not encontrados, f"Identificadores de abogado sin anonimizar: {encontrados}"


#: sha256 de las identidades que ya se anonimizaron una vez, en mayúsculas y sin espacios
#: sobrantes. Se guardan como hash y no en claro: publicar la lista de nombres reales
#: desharía la anonimización que este mismo test protege.
_NOMBRES_RETIRADOS = {
    "57c6ab2cde0f0577a101d61e301a26c6c430028fd6b77050625b20c946ff8e8d",
    "697e19a30c414722d14d87c43e3fadfdf69785f57e8921485286415225a5c9c8",
    "789071cded7db7fcee5a3eb38342bed8087ce3077ebebde9b6ac6d5aa6258e14",
    "89b87997a8eb260a6692b61440539c5c64950f6770d76df49668d9556c542272",
    "8c89342be628f7cb8143f52c0230a85f6cefb705717541fa31a8fc14fc4fc270",
    "a35e09efbb7d06ac500b4a7efbca11e4903b14610e8519f5d9f923b076099090",
    "d8e1ed7044e561e2224e8288c92d3d5113f4fb0ae1e21c9978379a38acce4e75",
    # Las dos que estaban en `detalle_cobranza.html` y ningún guardia veía: el juez asignado de
    # la cabecera y la responsable de una diligencia. Venían en mayúscula y minúscula, y los
    # cuatro patrones de acá buscaban corridas EN MAYÚSCULAS.
    "c29bf725261bf5a827a20a6e541be6f41b824bb80965646c612625f1f896aab1",
    "7ebd2473e57017c6a6c9acfb083e9b118f359107340341b72752888d34080e0b",
    # Y la tercera, que apareció al escribir el guardia nuevo: un abogado en `detalle_laboral`.
    # Ésta SÍ venía en mayúsculas, y se escapaba por otra rendija: el `(Poder Amplio)` del
    # final, porque los paréntesis no están en la clase de caracteres del patrón viejo.
    "f9b27137e89b3b75fb1f0a0117a9dca904b37d2e0b496e3baafa8614862fc160",
}


#: Cualquier texto de celda que pueda ser el nombre de una persona, en MAYÚSCULAS o en
#: mayúscula y minúscula.
#:
#: El patrón anterior sólo veía corridas en mayúsculas, y con eso los dos nombres reales que
#: `detalle_cobranza.html` traía en la cabecera y en el panel de diligencias eran invisibles
#: para los cuatro guardias de este archivo a la vez. El sitio escribe algunos rótulos de una
#: forma y otros de la otra, así que el guardia no puede elegir una.
_CANDIDATOS_A_NOMBRE = re.compile(r">\s*([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\s]{10,60})\s*<")


def _huella(texto: str) -> str:
    return hashlib.sha256(" ".join(texto.split()).upper().encode()).hexdigest()


def test_sin_nombres_reales_conocidos():
    """Guardia contra reintroducir identidades que ya se anonimizaron.

    Compara hashes de los nombres que aparecen en las fixtures contra la lista de los que se
    retiraron. No necesita conocer los nombres reales para funcionar.
    """
    encontrados = {}
    for archivo in _archivos():
        texto = archivo.read_text(encoding="utf-8")
        for candidato in _CANDIDATOS_A_NOMBRE.findall(texto):
            if _huella(candidato) in _NOMBRES_RETIRADOS:
                encontrados.setdefault(archivo.name, set()).add("(identidad retirada)")
    assert not encontrados, (
        f"Se reintrodujo una identidad que ya se había anonimizado: {encontrados}"
    )


def test_los_nombres_de_las_fixtures_son_los_ficticios():
    """Refuerzo del anterior: los nombres presentes deben ser los ficticios conocidos.

    El test de hashes sólo detecta identidades ya vistas. Éste detecta cualquier nombre nuevo
    que se cuele, incluido uno que nunca haya pasado por el anonimizador.
    """
    # Cada excepción se agrega de a una y con su motivo. Ensanchar este conjunto es la forma
    # más fácil de tapar una fuga real, así que lo que entra acá tiene que ser verificable a
    # simple vista como algo que NO identifica a nadie.
    #
    # Las tres últimas son descripciones de trámite del detalle de suprema: la plataforma las
    # imprime en mayúsculas en la misma clase de celda donde van los nombres, así que el patrón
    # no puede distinguirlas. Son texto procesal, no identidades.
    permitidos = {
        "BANCO DE CHILE",
        "CONFIRMA SENTENCIA APELADA",
        "TÉNGASE PRESENTE COMPARECENCIA Y ALEGATOS",
        "CERTIFICADO DE INGRESO",
    }
    inesperados = {}
    for archivo in _archivos():
        texto = archivo.read_text(encoding="utf-8")
        for candidato in re.findall(r">\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{14,60})\s*<", texto):
            nombre = " ".join(candidato.split())
            if len(nombre.split()) < 3 or nombre in permitidos:
                continue
            if not nombre.startswith(("PERSONA ", "ABOGAD", "EMPRESA ", "DEMANDAD")):
                inesperados.setdefault(archivo.name, set()).add(nombre)
    assert not inesperados, (
        f"Nombres que no son ficticios en las fixtures: {inesperados}. "
        "Corre: uv run python tests/fixtures/anonimizar.py"
    )


#: Los encabezados de columna que llevan el nombre de una persona, y los rótulos de cabecera
#: que hacen lo mismo. Salen de mirar las fixtures, no de imaginarlos.
_COLUMNAS_CON_NOMBRE = {
    "nombre",
    "nombre o razón social",
    "responsable",
    "destinatario",
    "abog. defensor",
    "juez asignado",
}

#: Lo que puede aparecer ahí sin identificar a nadie. Cada entrada se agrega de a una: esto es
#: lo que hace pasar un valor, así que ensancharlo es la forma más fácil de tapar una fuga.
_NO_IDENTIFICAN = {"no", "no asignado", "sin asignar", "banco de chile"}

#: Cómo empiezan los nombres ficticios que este repositorio usa.
_PREFIJOS_FICTICIOS = ("PERSONA ", "EMPRESA ", "ABOGAD", "DEMANDAD")


def _valores_de_columnas_con_nombre(texto: str) -> set[str]:
    """Lo que las fixtures publican en las celdas que llevan nombres de personas.

    Se mira POR COLUMNA y no por la forma del texto, y ésa es la diferencia con los guardias de
    arriba: un nombre en mayúscula y minúscula es indistinguible de una descripción de trámite
    ("Designación de Martillero" también son tres palabras capitalizadas), así que el patrón no
    puede separarlos y el encabezado sí.
    """
    from lxml import etree
    from lxml import html as H

    doc = H.fromstring(texto)
    etree.strip_elements(doc, etree.Comment, with_tail=False)

    def texto_de(elemento) -> str:
        return " ".join(elemento.text_content().split())

    valores = set()
    tablas: list = list(doc.iter("table"))
    for tabla in tablas:
        cabecera: list = list(tabla.iter("th"))
        encabezados = {i: texto_de(th).lower() for i, th in enumerate(cabecera)}
        columnas = [i for i, h in encabezados.items() if h in _COLUMNAS_CON_NOMBRE]
        if not columnas:
            continue
        for fila in tabla.iter("tr"):
            celdas: list = fila.findall("td")
            for i in columnas:
                if i < len(celdas) and (v := texto_de(celdas[i])):
                    valores.add(v)
    # Y los rótulos de cabecera, que no viven en una tabla con encabezados sino en un `strong`
    # con el valor en su cola. Ahí estaba el juez asignado.
    for etiqueta in doc.iter("strong"):
        rotulo = texto_de(etiqueta).rstrip(":").lower()
        if rotulo in _COLUMNAS_CON_NOMBRE and (v := " ".join((etiqueta.tail or "").split())):
            valores.add(v)
    return valores


def test_las_celdas_que_llevan_nombres_traen_los_ficticios():
    """El agujero que dejó pasar dos nombres reales durante versiones.

    Los otros guardias de este archivo buscan corridas EN MAYÚSCULAS, así que un nombre escrito
    como lo escribe una persona era invisible para los cuatro a la vez. `detalle_cobranza.html`
    traía dos: el juez asignado de la cabecera y la responsable de una diligencia.

    Éste no mira la forma del texto sino la COLUMNA: lo que va bajo `Nombre`, `Responsable`,
    `Destinatario` o `Juez Asignado` identifica a una persona, se escriba como se escriba.
    """
    inesperados = {}
    for archivo in _archivos():
        for valor in _valores_de_columnas_con_nombre(archivo.read_text(encoding="utf-8")):
            if valor.lower() in _NO_IDENTIFICAN:
                continue
            if not valor.upper().startswith(_PREFIJOS_FICTICIOS):
                inesperados.setdefault(archivo.name, set()).add(valor)
    assert not inesperados, (
        f"Celdas con nombre que no son ficticias: {inesperados}. "
        "Corre: uv run python tests/fixtures/anonimizar.py"
    )


def test_sin_jwt_de_la_plataforma():
    """Las respuestas traen JWT como referencia opaca de causa, cuaderno o documento.

    Caducan a los 30 minutos, así que no sirven de credencial, pero su carga va cifrada y
    probablemente codifica identificadores de la misma causa cuyos nombres y RUT ya se
    anonimizaron. Además los detectores de secretos los marcan en cada revisión, lo que
    entrena a ignorar alertas.
    """
    encontrados = {}
    for archivo in _archivos():
        hallados = _JWT.findall(archivo.read_text(encoding="utf-8"))
        if hallados:
            encontrados[archivo.name] = len(hallados)
    assert not encontrados, (
        f"JWT de la plataforma en fixtures: {encontrados}. "
        "Corre: uv run python tests/fixtures/anonimizar.py"
    )


def test_sin_consultas_sql_de_la_plataforma():
    """El detalle de Cortes de Apelaciones imprime un SELECT dentro de una celda.

    Trae el esquema, la tabla y los parámetros con nombre del sistema del Poder Judicial. No es
    un dato de este proyecto ni de las partes: son internos de un tercero, y republicarlos acá
    los deja indexados y permanentes. Es la misma razón por la que los hallazgos de seguridad
    de la plataforma no se publican en el repositorio.
    """
    encontrados = {}
    for archivo in _archivos():
        if re.search(
            r"SELECT\s+[A-Z_0-9,\s]+FROM\s+\w+\.\w+", archivo.read_text(encoding="utf-8"), re.I
        ):
            encontrados[archivo.name] = "consulta SQL de la plataforma"
    assert not encontrados, (
        f"Consultas internas de la plataforma en fixtures: {encontrados}. "
        "Corre: uv run python tests/fixtures/anonimizar.py"
    )
