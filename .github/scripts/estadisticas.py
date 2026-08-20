"""Guarda una foto diaria del tráfico del repositorio.

La API de tráfico de GitHub sólo retiene **catorce días**, y no hay forma de pedirle más:
lo que no se guarde antes de que caduque se pierde para siempre. Por eso esto existe y por
eso corre a diario.

Se escriben CSV y no JSON a propósito: el archivo crece por líneas, así que el `git diff` de
cada foto se lee, y una hoja de cálculo lo abre sin nada en el medio.

Las filas se reemplazan por clave y no se agregan. La ventana de catorce días significa que
la foto de hoy trae de nuevo los trece días anteriores, y GitHub corrige hacia arriba el día
en curso: agregar produciría trece duplicados diarios y un día de hoy contado catorce veces.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import pathlib
import subprocess
import sys

REPO = os.environ.get("GITHUB_REPOSITORY", "notluquis/mcp-pjud-cl")
DESTINO = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "datos")


def api(ruta: str, paginar: bool = False):
    """Una lectura de la API. Sin reintento: si falla, la foto de hoy no sale y se ve.

    Fallar es lo correcto acá. Guardar una foto a medias la dejaría indistinguible de un día
    sin tráfico, y ese cero se arrastraría para siempre en el CSV sin que nada avise.
    """
    orden = ["gh", "api", f"repos/{REPO}/{ruta}".rstrip("/")]
    if paginar:
        # `gh api` trae 30 elementos por página y no avisa que hay más. Sin esto, pasadas 30
        # versiones dejarían de contarse las descargas de las viejas, en silencio, que es la
        # misma truncación callada que el resto del proyecto levanta en vez de esconder.
        # `--slurp` junta las páginas en un arreglo de arreglos, y no se puede combinar con
        # `--jq` para aplanarlo: `gh` lo rechaza. Se aplana acá.
        orden += ["--paginate", "--slurp"]
    salida = subprocess.run(  # noqa: S603
        orden,
        capture_output=True,
        text=True,
        check=False,
    )
    if salida.returncode != 0:
        if "Resource not accessible" in salida.stderr or "403" in salida.stderr:
            raise SystemExit(
                f"La API de tráfico rechazó {ruta!r}. Exige permiso de escritura sobre el "
                "repositorio, que el token del workflow no tiene: hay que configurar el "
                "secreto TRAFICO_TOKEN con un token de grano fino que declare "
                "'Administration: read'.\n\n" + salida.stderr
            )
        raise SystemExit(f"La API falló en {ruta!r}:\n{salida.stderr}")
    datos = json.loads(salida.stdout)
    return [x for pagina in datos for x in pagina] if paginar else datos


def guardar(nombre: str, campos: list[str], filas: list[dict], claves: list[str]) -> int:
    """Mezcla `filas` en el CSV, reemplazando por `claves`. Devuelve cuántas quedaron."""
    archivo = DESTINO / nombre
    previas: dict[tuple, dict] = {}
    if archivo.exists():
        with archivo.open(encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                previas[tuple(fila[c] for c in claves)] = fila

    for fila in filas:
        previas[tuple(str(fila[c]) for c in claves)] = {k: str(v) for k, v in fila.items()}

    archivo.parent.mkdir(parents=True, exist_ok=True)
    with archivo.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        for clave in sorted(previas):
            escritor.writerow(previas[clave])
    return len(previas)


def _leer(nombre: str) -> list[dict[str, str]]:
    archivo = DESTINO / nombre
    if not archivo.exists():
        return []
    with archivo.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def resumen(hoy: str) -> None:
    """Arma el resumen que se lee en la rama, a partir de los CSV ya mezclados.

    Se llama `README.md` porque GitHub renderiza el README de la rama que uno esté mirando:
    es lo que aparece solo al abrir `estadisticas`, sin que nadie tenga que saber que hay CSV.

    Se arma desde los archivos y no desde la respuesta de la API a propósito. Los CSV son los
    que tienen el historial completo; la respuesta sólo trae catorce días, y un resumen que
    dijera "todo lo registrado" leyendo de ahí mentiría más cada día que pasa.
    """
    trafico = _leer("trafico.csv")
    con_datos = [f for f in trafico if any(int(f[c]) for c in f if c != "fecha")]
    ultimos = trafico[-14:]

    def suma(filas: list[dict[str, str]], campo: str) -> int:
        return sum(int(f[campo]) for f in filas)

    desde = con_datos[0]["fecha"] if con_datos else "todavía nada"
    lineas = [
        "# Estadísticas de mcp-pjud-cl",
        "",
        f"Foto del {hoy}. **Generado, no editar a mano**: lo reescribe el flujo",
        "`estadisticas` cada día, y cualquier cambio se pierde en la corrida siguiente.",
        "",
        "## Cómo leer esto antes de leerlo",
        "",
        "**Los clones NO son instalaciones.** A un repositorio público recién creado lo clonan",
        "decenas de servicios que leen el flujo de eventos de GitHub: espejos, escáneres de",
        "seguridad, indexadores. Se ve en la serie de más abajo: el día que este repositorio se",
        "hizo público hubo cientos de clones desde cientos de orígenes distintos, con **un**",
        "visitante único. Ninguna persona hizo eso.",
        "",
        "**Las descargas de archivos publicados van a marcar cero para siempre.** La",
        "instalación documentada es `uvx --from git+https://…`, que clona: nunca toca el",
        "`.whl` ni el `.tar.gz`. El contador de GitHub mide algo que este proyecto no usa.",
        "",
        "## General",
        "",
        "| Período | Vistas | Únicas | Clones | Únicos |",
        "|---|---|---|---|---|",
        f"| Últimos 14 días | {suma(ultimos, 'vistas')} | {suma(ultimos, 'vistas_unicas')} | "
        f"{suma(ultimos, 'clones')} | {suma(ultimos, 'clones_unicos')} |",
        f"| Todo lo registrado, desde el {desde} | {suma(trafico, 'vistas')} | "
        f"{suma(trafico, 'vistas_unicas')} | {suma(trafico, 'clones')} | "
        f"{suma(trafico, 'clones_unicos')} |",
        "",
        "Las columnas de únicos NO se suman entre días: quien vuelve mañana cuenta de nuevo.",
        "Sirven para comparar un día contra otro, no para saber cuánta gente distinta hubo.",
        "",
        "## Popularidad",
        "",
        "| Foto | Estrellas | Forks | Suscriptores | Incidencias abiertas |",
        "|---|---|---|---|---|",
        *(
            f"| {f['foto']} | {f['estrellas']} | {f['forks']} | {f['suscriptores']} | "
            f"{f['incidencias_abiertas']} |"
            for f in reversed(_leer("popularidad.csv"))
        ),
        "",
        "Estas cuatro no caducan, pero GitHub sólo entrega el número de hoy: la serie hay que",
        "construirla. Es la única parte de esto que no se puede recuperar mirando después.",
        "",
        "## Por versión",
        "",
        "| Versión | Archivo | Descargas |",
        "|---|---|---|",
    ]

    descargas = _leer("descargas.csv")
    foto_descargas = max((d["foto"] for d in descargas), default="")
    lineas += [
        f"| {d['version']} | `{d['archivo']}` | {d['descargas']} |"
        for d in sorted(
            (d for d in descargas if d["foto"] == foto_descargas),
            key=lambda d: (d["version"], d["archivo"]),
            reverse=True,
        )
    ]

    for titulo, nombre, columna in (
        ("De dónde llegan", "referentes.csv", "referente"),
        ("Qué miran", "rutas.csv", "ruta"),
    ):
        filas = _leer(nombre)
        foto = max((f["foto"] for f in filas), default="")
        lineas += [
            "",
            f"## {titulo}",
            "",
            f"Acumulado de los catorce días hasta el {foto}. GitHub no lo entrega por día, así",
            "que restar dos fotos para inferirlo daría un número inventado.",
            "",
            f"| {columna.capitalize()} | Vistas | Únicas |",
            "|---|---|---|",
        ]
        lineas += [
            f"| `{f[columna]}` | {f['vistas']} | {f['unicas']} |"
            for f in sorted(
                (f for f in filas if f["foto"] == foto),
                key=lambda f: int(f["vistas"]),
                reverse=True,
            )
        ]

    lineas += [
        "",
        "## La serie completa",
        "",
        "| Fecha | Vistas | Únicas | Clones | Únicos |",
        "|---|---|---|---|---|",
    ]
    lineas += [
        f"| {f['fecha']} | {f['vistas']} | {f['vistas_unicas']} | {f['clones']} | "
        f"{f['clones_unicos']} |"
        for f in reversed(con_datos)
    ]
    lineas += ["", "Los días sin nada no se listan. El dato crudo está en `trafico.csv`."]

    (DESTINO / "README.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> None:
    vistas = {d["timestamp"][:10]: d for d in api("traffic/views")["views"]}
    clones = {d["timestamp"][:10]: d for d in api("traffic/clones")["clones"]}

    # Un día puede traer clones y ninguna vista, o al revés, así que la unión y no una de las
    # dos: quedarse con las fechas de vistas perdía los días que sólo tuvieron clones, que en
    # este repositorio son la mayoría.
    filas = [
        {
            "fecha": fecha,
            "vistas": vistas.get(fecha, {}).get("count", 0),
            "vistas_unicas": vistas.get(fecha, {}).get("uniques", 0),
            "clones": clones.get(fecha, {}).get("count", 0),
            "clones_unicos": clones.get(fecha, {}).get("uniques", 0),
        }
        for fecha in sorted(set(vistas) | set(clones))
    ]
    dias = guardar(
        "trafico.csv",
        ["fecha", "vistas", "vistas_unicas", "clones", "clones_unicos"],
        filas,
        ["fecha"],
    )

    # Referentes y rutas NO vienen por día: son un acumulado de la ventana entera, así que
    # la clave lleva la fecha de la foto. Restarlos entre fotos para inferir el día daría un
    # número inventado, porque la ventana además pierde el día que se cae por atrás.
    # La fecha de la foto es hoy y no la última del tráfico: la ventana termina ayer, y
    # etiquetar la foto con ayer haría creer que estos acumulados son de ese día.
    hoy = datetime.datetime.now(datetime.UTC).date().isoformat()
    guardar(
        "referentes.csv",
        ["foto", "referente", "vistas", "unicas"],
        [
            {"foto": hoy, "referente": r["referrer"], "vistas": r["count"], "unicas": r["uniques"]}
            for r in api("traffic/popular/referrers")
        ],
        ["foto", "referente"],
    )
    guardar(
        "rutas.csv",
        ["foto", "ruta", "vistas", "unicas"],
        [
            {"foto": hoy, "ruta": r["path"], "vistas": r["count"], "unicas": r["uniques"]}
            for r in api("traffic/popular/paths")
        ],
        ["foto", "ruta"],
    )

    # Las descargas de los archivos publicados NO caducan: son un contador acumulado desde
    # que la versión salió. Se guardan igual porque el contador no dice cuándo se descargó,
    # y la diferencia entre dos fotos sí.
    descargas = [
        {
            "foto": hoy,
            "version": v["tag_name"],
            "archivo": a["name"],
            "descargas": a["download_count"],
        }
        for v in api("releases", paginar=True)
        for a in v["assets"]
    ]
    guardar(
        "descargas.csv",
        ["foto", "version", "archivo", "descargas"],
        descargas,
        ["foto", "version", "archivo"],
    )

    # Estrellas y forks NO caducan, pero GitHub sólo entrega el número de hoy: la serie hay
    # que construirla. Es la única parte de esto que no se puede recuperar mirando después.
    repo = api("")
    guardar(
        "popularidad.csv",
        ["foto", "estrellas", "forks", "suscriptores", "incidencias_abiertas"],
        [
            {
                "foto": hoy,
                "estrellas": repo["stargazers_count"],
                "forks": repo["forks_count"],
                "suscriptores": repo["subscribers_count"],
                "incidencias_abiertas": repo["open_issues_count"],
            }
        ],
        ["foto"],
    )

    total = sum(int(d["descargas"]) for d in descargas)
    resumen(hoy)
    print(f"{dias} días de tráfico guardados. Descargas de archivos publicados: {total}.")


if __name__ == "__main__":
    main()
