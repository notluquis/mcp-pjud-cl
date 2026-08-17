"""Aislamiento entre tests.

El semáforo y la detención viven en el módulo, no en el cliente, porque el Poder Judicial es
uno solo aunque `server.py` abra un `PjudClient` por llamada de herramienta. Eso los vuelve
estado compartido entre tests: sin limpiarlos, el primer test que reciba un 403 dejaría al
proceso detenido y todos los siguientes fallarían por un bloqueo que nunca ocurrió.
"""

import pytest

from mcp_pjud import client


@pytest.fixture(autouse=True)
def _reiniciar_estado_del_proceso():
    client._ULTIMA = 0.0
    client._FICHAS = float(client.RAFAGA_MAXIMA)
    client._BLOQUEADO = None
    yield
    client._ULTIMA = 0.0
    client._FICHAS = float(client.RAFAGA_MAXIMA)
    client._BLOQUEADO = None
