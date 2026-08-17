# Uso aceptable

## Qué es este documento y qué no

**Esto no es la licencia.** Lo que te obliga legalmente está en [LICENSE.md](LICENSE.md)
(PolyForm Strict 1.0.0). Este archivo declara los usos que el autor rechaza, y sirve para que
nadie diga después que no sabía.

Se mantiene separado a propósito. Meter cláusulas éticas dentro de la licencia produce un
texto a medida que ningún departamento legal aprueba y que, por vaguedad, tampoco resulta
exigible: "no usar para cosas malas" no es un estándar jurídico. La licencia hace el trabajo
legal; este documento hace el trabajo de decir en voz alta para qué no.

## Lo que la licencia sí prohíbe, y es exigible

- Modificar el software
- Distribuirlo
- Usarlo con fines comerciales, incluido el ejercicio profesional remunerado

Todo eso requiere permiso escrito. Se pide en un issue con la plantilla correspondiente, se
otorga caso a caso y sin costo.

## Usos que el autor rechaza

Aunque tengas permiso de uso, estos usos son contrarios al propósito del proyecto:

**Sobrecargar la plataforma.** Correr varias instancias en paralelo, bajar el intervalo entre
peticiones, o barrer roles masivamente. En julio de 2026 un ingreso automatizado masivo hizo
colapsar la Oficina Judicial Virtual y terminó con una IP bloqueada y una solicitud de
informe sobre responsabilidades disciplinarias y penales. Ese antecedente define el tono de
todo este proyecto.

**Construir perfiles de personas.** Cruzar el campo `Institución` para reconstruir la cartera
de un abogado, armar bases de datos de litigantes, o perfilar a personas naturales por su
historial judicial.

**Vigilancia, acoso o discriminación.** Usar información de causas para hostigar a una
contraparte, para discriminar en contratación, arriendo, crédito o seguros, o para exponer
públicamente a una persona.

**Suplantar a la institución.** Presentar la salida de esta herramienta como información
oficial del Poder Judicial, o usar sus logos, colores o tipografía.

**Reemplazar el criterio profesional.** Esto acerca la fuente oficial. No reemplaza la
revisión de un abogado ni la lectura del expediente. Un plazo no se computa desde una
salida de software sin verificar.

## Datos personales: Ley 21.719

La Ley 21.719 sobre protección de datos personales fue publicada el 13 de diciembre de 2024 y
**entra en vigencia el 1 de diciembre de 2026**. Crea la Agencia de Protección de Datos
Personales, con potestad para investigar de oficio, sancionar y publicar un registro de
sanciones. Las multas llegan a 20.000 UTM, o 4% de los ingresos anuales en caso de
reincidencia.

Los datos que devuelve esta herramienta —nombres, RUT, roles, actuaciones— son **datos
personales de terceros**, aunque provengan de una fuente pública. Que sean públicos no los
saca del ámbito de la ley.

Por eso el software **no persiste nada**. Si tú decides guardar lo que devuelve, el
responsable del tratamiento pasas a ser tú, con todo lo que eso implica: base de licitud,
principio de finalidad, minimización, plazos de conservación, derechos ARCO del titular, y
notificación de brechas dentro de 72 horas.

Si vas a almacenar resultados, asesórate antes. No es una formalidad: faltan menos de cuatro
meses para que la ley rija.

## Causas reservadas

No aparecen en la consulta pública. Si accedes a información de una causa reservada por
cualquier vía, esta herramienta no es el camino y su uso no te ampara.

Un resultado vacío **no prueba** que la causa no exista: puede estar reservada.

## Cómo reportar un uso indebido

Abre un issue, o escribe por el canal de contacto del repositorio si prefieres no hacerlo en
público.
