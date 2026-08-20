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


def api(ruta: str):
    """Una lectura de la API. Sin reintento: si falla, la foto de hoy no sale y se ve.

    Fallar es lo correcto acá. Guardar una foto a medias la dejaría indistinguible de un día
    sin tráfico, y ese cero se arrastraría para siempre en el CSV sin que nada avise.
    """
    salida = subprocess.run(  # noqa: S603
        ["gh", "api", f"repos/{REPO}/{ruta}"],  # noqa: S607
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
    return json.loads(salida.stdout)


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
        for v in api("releases")
        for a in v["assets"]
    ]
    guardar(
        "descargas.csv",
        ["foto", "version", "archivo", "descargas"],
        descargas,
        ["foto", "version", "archivo"],
    )

    total = sum(int(d["descargas"]) for d in descargas)
    print(f"{dias} días de tráfico guardados. Descargas de archivos publicados: {total}.")


if __name__ == "__main__":
    main()
