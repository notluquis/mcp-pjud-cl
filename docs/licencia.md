# Licencia: qué se eligió y qué se descartó

El proyecto usa [PolyForm Strict 1.0.0](https://polyformproject.org/licenses/strict/1.0.0).
Esta página registra por qué, para que la decisión se pueda discutir en vez de heredarse.

## Lo que se buscaba

1. Que nadie pueda publicar su propia versión del proyecto.
2. Que los pull requests sí sean posibles.
3. Que el titular sepa quién lo usa y para qué.
4. Que sirva en Chile y fuera de Chile.

## Familias evaluadas

### Licencias libres (MIT, Apache 2.0, GPL, AGPL)

Descartadas por el punto 1. Todas permiten redistribuir, y la AGPL, que es la más exigente,
obliga a publicar el código derivado pero no impide que alguien mantenga su propio fork.

### Licencias no comerciales (PolyForm Noncommercial, Prosperity, CC BY-NC)

Descartadas, y por una razón que conviene explicar porque es contraintuitiva: **le prohibirían
el uso a los destinatarios del proyecto**.

PolyForm Noncommercial enumera los propósitos permitidos, y son dos: uso personal sin
aplicación comercial prevista, y uso por organizaciones benéficas, educacionales, de
investigación pública, salud, seguridad pública, medio ambiente o instituciones del Estado.

Un estudio jurídico que factura a sus clientes no está en ninguna de las dos listas. Con una
licencia de esa familia, un abogado revisando plazos de una causa por la que cobra estaría
infringiéndola. Cualquier licencia "no comercial" produce el mismo resultado.

### Licencias anti competencia (PolyForm Shield, Elastic License 2.0, SSPL)

Permiten casi todo salvo competir con el licenciante u ofrecer el software como servicio
gestionado. Resuelven el punto 1 sólo a medias: permiten redistribuir y modificar, así que
alguien puede mantener y difundir su propio fork mientras no compita comercialmente.

### Licencias con conversión a plazo (BUSL 1.1, Functional Source License)

Restringen el uso comercial por un período y después el código pasa a una licencia libre. La
FSL, por ejemplo, convierte a Apache 2.0 o MIT a los dos años.

Descartadas porque la conversión automática entrega el punto 1 en una fecha futura, sin que
nadie revise el contexto de ese momento. En un proyecto que toca plazos procesales y que
depende del HTML de un tercero, no parece buena idea programar hoy una apertura para dentro de
dos años.

### Cláusulas añadidas (Commons Clause)

Se agregan sobre una licencia libre para prohibir la venta. Descartadas por producir un texto
compuesto que los departamentos legales revisan mal, sin ventaja sobre usar una licencia
estándar completa.

### Licencias éticas (Hippocratic License)

Prohíben usos que violen derechos humanos. Descartadas como licencia, porque "usos indebidos"
es difícil de definir con precisión exigible, y una licencia poco precisa se cumple mal.

Los usos que el proyecto rechaza están igualmente declarados, pero en
[ACCEPTABLE_USE.md](https://github.com/notluquis/mcp-pjud-cl/blob/main/ACCEPTABLE_USE.md), y
ese documento dice de sí mismo que es declarativo y no contractual. Es más honesto que
esconderlo dentro de una licencia y suponer que se puede exigir.

## Lo elegido

**PolyForm Strict 1.0.0** permite ejecutar el software con fines no comerciales, y nada más.
Sin modificar, sin distribuir, sin uso comercial.

Cumple los cuatro objetivos, incluido el tercero de una manera poco habitual: como
prácticamente cualquier uso profesional requiere permiso, **todo el mundo tiene que pedirlo**,
y así el titular sabe quién usa la herramienta. Los permisos se otorgan caso a caso y sin
costo.

El punto 2 lo resuelve el [acuerdo de contribución](https://github.com/notluquis/mcp-pjud-cl/blob/main/CLA.md),
que otorga un permiso adicional acotado a preparar contribuciones. La licencia queda intacta,
sin una coma cambiada, que es lo que importa cuando el área legal de una organización tiene que
revisarla.

## Lo que esta elección cuesta

Se dice porque toda elección de licencia tiene un costo, y ocultarlo sería vender humo:

- **No es open source.** No cumple la definición de la OSI. El término correcto es
  *source-available*.
- **Genera fricción real.** Un abogado que quiere probarlo debe pedir permiso primero. Se
  asume a cambio de saber quién lo usa.
- **Los forks no se pueden impedir técnicamente.** GitHub no permite deshabilitarlos en
  repositorios públicos. Lo que ata es la licencia, no una casilla de configuración.
- **La insignia de OpenSSF Best Practices queda fuera de alcance.** Su criterio obligatorio
  `floss_license` exige que el software se publique como FLOSS, y esta licencia no lo es. El
  hallazgo `CII-Best-Practices` de Scorecard queda abierto de forma permanente.
