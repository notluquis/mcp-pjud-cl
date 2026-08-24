"""Aislamiento entre tests.

El semáforo y la detención viven en el módulo, no en el cliente, porque el Poder Judicial es
uno solo aunque `server.py` abra un `PjudClient` por llamada de herramienta. Eso los vuelve
estado compartido entre tests: sin limpiarlos, el primer test que reciba un 403 dejaría al
proceso detenido y todos los siguientes fallarían por un bloqueo que nunca ocurrió.
"""

import os
from pathlib import Path

import pytest

from mcp_pjud import client

# `httpx.Client()` pregunta por el proxy del sistema, y en macOS eso entra a CoreFoundation.
# `mutmut` corre cada mutante en un proceso hijo por `fork()`, y CoreFoundation después de un
# fork en un proceso con hilos revienta: el 24 de agosto de 2026 eso convirtió 2.071 de 3.862
# mutantes en `💥`, o sea la mitad de la medición era del corredor y no del código.
#
# Con cualquier variable `*_proxy` puesta, `urllib.request.getproxies()` responde desde el
# entorno y no llega a preguntarle al sistema. El puerto es el descarte de TCP: ningún test
# sale a la red, así que esto es inerte, y si alguno lo intentara fallaría acá en vez de
# consultar de verdad al Poder Judicial.
os.environ.setdefault("http_proxy", "http://127.0.0.1:9")
os.environ.setdefault("https_proxy", "http://127.0.0.1:9")


def raiz_del_repo() -> Path:
    """La raíz del repositorio, también cuando los tests corren desde otro lado.

    `mutmut` copia `src/` y `tests/` a `mutants/` y corre la suite desde ahí, sin la
    documentación ni el repositorio git. Los guardias que comparan documentación contra código
    tienen que leer la documentación de VERDAD: lo que se muta es el código, y que un mutante
    ponga en rojo un guardia de documentación es justamente lo que se quiere ver.
    """
    raiz = Path(__file__).parents[1]
    # Por lo que hay dentro y no por el nombre: un clon en un directorio llamado `mutants`
    # haría subir un nivel de más y ahí no habría `docs/` tampoco.
    return raiz if (raiz / "docs").is_dir() else raiz.parent


#: Lo que mide la sentencia de trece páginas con la que se decidió separar el texto de la
#: búsqueda: `obtener_texto_sentencia` existe porque devolver diez con cada búsqueda serían
#: más de doscientos cincuenta mil caracteres.
#:
#: Vive acá y no en el paquete porque es una medición y el código no la usa para nada: la
#: usan la documentación, que la cita, y `test_juris`, que arma un texto de ese largo. Tenerla
#: en dos archivos de test era la misma clase de dato repetido que estos guardias persiguen.
CARACTERES_DE_UNA_SENTENCIA = 25_473


@pytest.fixture(autouse=True)
def _reiniciar_estado_del_proceso():
    client._ULTIMA = 0.0
    client._FICHAS = float(client.RAFAGA_MAXIMA)
    client._BLOQUEADO = None
    yield
    client._ULTIMA = 0.0
    client._FICHAS = float(client.RAFAGA_MAXIMA)
    client._BLOQUEADO = None
