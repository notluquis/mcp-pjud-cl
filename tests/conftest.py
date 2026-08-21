"""Aislamiento entre tests.

El semáforo y la detención viven en el módulo, no en el cliente, porque el Poder Judicial es
uno solo aunque `server.py` abra un `PjudClient` por llamada de herramienta. Eso los vuelve
estado compartido entre tests: sin limpiarlos, el primer test que reciba un 403 dejaría al
proceso detenido y todos los siguientes fallarían por un bloqueo que nunca ocurrió.
"""

import pytest

from mcp_pjud import client

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
