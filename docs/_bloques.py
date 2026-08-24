"""Los bloques que la documentación repite, en un solo lugar.

`cog` los ejecuta y deja el resultado ESCRITO en el `.md`, así que el archivo sigue siendo
legible en GitHub y el guardia sigue teniendo qué comparar. Es la diferencia con una
sustitución de plantilla, que vacía el archivo y de paso vacía el guardia.

Se eligió `cog` y no un mecanismo de Sphinx porque `README.md` no pasa por ningún build: es el
archivo con más copias de esto y ninguna extensión de Sphinx lo alcanza.
"""

import json

#: De dónde se instala. Estaba escrito cuatro veces, y cambiarlo era acordarse de las cuatro.
ORIGEN = "git+https://github.com/notluquis/mcp-pjud-cl@stable"

#: El ejecutable que el paquete declara en `[project.scripts]`.
COMANDO = "mcp-pjud"

#: Con qué nombre queda registrado en el cliente. No tiene por qué coincidir con el paquete ni
#: con el repositorio, y se elige el del repositorio porque es lo que alguien busca cuando
#: quiere saber qué es esto. Vive acá porque además va en los botones de un clic del README,
#: que no pasan por `cog`, y ahí es donde se desincronizaba.
ALIAS = "mcp-pjud-cl"

#: Un correo de ejemplo. No es de nadie: el dominio `estudio.cl` no existe como buzón real, y
#: la guía explica al lado que el valor tiene que ser uno al que de verdad se pueda escribir.
CONTACTO_EJEMPLO = "informatica@estudio.cl"


def configuracion(clave: str = "mcpServers", contacto: str = CONTACTO_EJEMPLO) -> str:
    """El bloque JSON que se pega en el cliente MCP.

    `clave` existe porque VS Code usa `servers` donde el resto usa `mcpServers`, y pegar el
    bloque equivocado no da un error claro: el servidor simplemente no aparece. Es la única
    diferencia entre las cuatro copias que había, y por eso es un parámetro y no otro bloque.
    """
    bloque = {
        clave: {
            ALIAS: {
                "command": "uvx",
                "args": ["--from", ORIGEN, COMANDO],
                "env": {"MCP_PJUD_CONTACTO": contacto},
            }
        }
    }
    # `separators` sin espacio antes de los dos puntos y `ensure_ascii` apagado: el resultado
    # se pega a mano en un archivo de configuración, así que tiene que leerse como lo escribiría
    # una persona.
    texto = json.dumps(bloque, indent=2, ensure_ascii=False)
    # `args` y `env` caben en una línea y se leen mejor así, que es como estaban escritos a
    # mano. Se colapsan con la convención de cada uno: la lista pegada a sus corchetes y el
    # objeto con espacio adentro, que es lo que hace un editor de JSON al formatear.
    for campo, cierre in (("args", "]"), ("env", "}")):
        inicio = texto.index(f'"{campo}": ')
        fin = texto.index("\n", texto.index(cierre, inicio))
        una_linea = " ".join(texto[inicio:fin].split())
        if campo == "args":
            una_linea = una_linea.replace("[ ", "[").replace(" ]", "]")
        texto = texto[:inicio] + una_linea + texto[fin:]
    return texto
