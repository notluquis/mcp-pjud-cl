"""Aislamiento entre tests.

El semáforo y la detención viven en el módulo, no en el cliente, porque el Poder Judicial es
uno solo aunque `server.py` abra un `PjudClient` por llamada de herramienta. Eso los vuelve
estado compartido entre tests: sin limpiarlos, el primer test que reciba un 403 dejaría al
proceso detenido y todos los siguientes fallarían por un bloqueo que nunca ocurrió.
"""

from pathlib import Path

import pytest

from mcp_pjud import client


def raiz_del_repo() -> Path:
    """La raíz del repositorio, también cuando los tests corren desde otro lado.

    `mutmut` copia `src/` y `tests/` a `mutants/` y corre la suite desde ahí, sin la
    documentación ni el repositorio git. Los guardias que comparan documentación contra código
    tienen que leer la documentación de VERDAD: lo que se muta es el código, y que un mutante
    ponga en rojo un guardia de documentación es justamente lo que se quiere ver.
    """
    raiz = Path(__file__).parents[1]
    return raiz.parent if raiz.name == "mutants" else raiz


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
