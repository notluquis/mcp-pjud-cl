# Cómo contribuir

## Antes que nada: la licencia condiciona esto

Este proyecto usa la [PolyForm Strict 1.0.0](LICENSE.md), que **no otorga derecho a modificar
el software**. No es un descuido: es deliberado.

Eso significa que **no puedes preparar un pull request sin permiso previo**. No es que no
queramos aportes; es que la licencia, tal como está, no te da el derecho a hacer la
modificación en primer lugar, y un PR enviado sin ese permiso pone a ambas partes en una
posición incómoda.

El camino correcto:

1. **Abre primero un issue** describiendo qué quieres cambiar y por qué.
2. Si el cambio tiene sentido, se te otorga **permiso escrito y acotado a ese trabajo**, en
   el mismo issue.
3. Recién ahí preparas el PR.

Los permisos se dan caso a caso y sin costo. La fricción existe para saber quién toca esto y
con qué fin, no para desalentar.

## Lo que más sirve, y no requiere permiso de licencia

Reportar cosas no es modificar el software, así que esto lo puedes hacer directamente:

| Aporte | Por qué vale |
|---|---|
| **La Oficina Judicial Virtual cambió y algo se rompió** | Es lo más valioso que puedes reportar. Ver la plantilla correspondiente |
| **Una causa donde el resultado no calza con el expediente** | Un dato mal leído acá puede costar un plazo |
| **Errores en la documentación jurídica** | Si citamos mal una norma, hay que corregirlo rápido |
| **Competencias sin cubrir** | Sólo civil está verificada; laboral, cobranza y las demás faltan |

## Si vas a tocar código (con permiso ya otorgado)

### Reglas que no se negocian

Estas salen de para qué existe el proyecto, no de gusto personal:

1. **Nada que escriba en los sistemas del Poder Judicial.** Ni ingreso de escritos, ni
   modificación, ni eliminación. No debe existir el código, ni siquiera desactivado ni
   detrás de una bandera. Un PR que agregue capacidad de escritura se rechaza sin discusión.

2. **El intervalo mínimo entre peticiones no se baja.** Está en 5 segundos y es la
   implementación de la cláusula CUARTA de las condiciones de uso de la OJV, que prohíbe
   sobrecargar el portal. No es una constante de rendimiento.

3. **Ante 403, 429 o captcha: detención total.** Sin reintento, sin rotación de IP, sin
   evasión. Si el sistema bloquea, la respuesta correcta es parar y avisar.

4. **Fallo ruidoso, nunca vacío.** Si el parser no encuentra lo que espera, levanta
   excepción. Una lista vacía se lee como "no hubo actuaciones", y eso hace perder plazos.
   Este es el error que el proyecto entero existe para evitar.

5. **Sin persistencia por defecto.** Se consulta y se devuelve. Ver
   [ACCEPTABLE_USE.md](ACCEPTABLE_USE.md) sobre datos de terceros.

### Todo cambio de lógica deja un test que puede fallar

No basta escribir el test: hay que **verlo en rojo**. Rompe a propósito la línea que
arreglaste, corre la suite, confirma que se cae, restaura.

Un test que no puede fallar imprime exactamente lo mismo que uno que sí protege. Durante el
desarrollo esto detectó que un test central seguía verde con el bug puesto, porque otro
camino del código tapaba la regresión.

```bash
uv run pytest              # 34 tests, sin red
uv run ruff check .
```

Los tests corren contra HTML real guardado en `tests/fixtures/`. Nunca agregues un test que
consulte al Poder Judicial: si necesitas un caso nuevo, captura la respuesta una vez,
revísala, y guárdala como fixture.

### Fixtures y datos personales

Las fixtures traen nombres y roles de causas **públicas**. Antes de agregar una:

- Confirma que la causa no es reservada.
- No incluyas RUT completos de personas naturales si puedes evitarlo.
- No agregues causas de familia, penal con imputados individualizados, ni violencia
  intrafamiliar.

Ver [ACCEPTABLE_USE.md](ACCEPTABLE_USE.md).

### Idioma

Código, comentarios, commits, issues y documentación en **español de Chile**. Los nombres de
campo del modelo también: quien lee la salida es un abogado chileno.

Sin voseo (`tienes`, no `tenés`).

## Commits

Formato [Conventional Commits](https://www.conventionalcommits.org/es/):

```
fix(parser): leer la fecha de diligencia del cuaderno de apremio
docs: aclarar que la licencia no cubre el ejercicio remunerado
```

Prefijos: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.

## Reportar un problema de seguridad

No abras un issue público. Ver [SECURITY.md](SECURITY.md).
