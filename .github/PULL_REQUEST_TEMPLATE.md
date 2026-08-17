# Pull request

## Acuerdo de contribución

> Conservas la propiedad de tu contribución: no cedes tu derecho de autor ni renuncias a tus
> derechos morales. Lo que otorgas es una autorización de uso, y a cambio recibes permiso para
> modificar el proyecto con el fin de contribuir. Ver [CLA.md](../CLA.md).

- [ ] **He leído y acepto el acuerdo de contribución ([CLA.md](../CLA.md)) versión 1.0.**
- [ ] La contribución es obra original mía, o tengo derecho a otorgar esa autorización.
- [ ] Si incluye código de terceros, lo identifico abajo con su licencia.

Código de terceros incluido (o "ninguno"):

## Qué cambia y por qué

<!-- Un párrafo. Qué problema resuelve, no qué archivos tocaste. -->

Cierra #

## Las cinco reglas que no se negocian

- [ ] **No agrega ninguna capacidad de escritura** sobre sistemas del Poder Judicial, ni
      siquiera desactivada o detrás de una bandera.
- [ ] **No relaja el ritmo**: régimen sostenido de una petición cada 5 segundos y ráfaga máxima de 4.
- [ ] **Mantiene la detención total** ante 403, 429 o captcha. Sin reintento, sin evasión.
- [ ] **El parser sigue fallando ruidosamente**: excepción ante estructura desconocida,
      nunca lista vacía.
- [ ] **No introduce persistencia** de datos de terceros.

## Verificación

- [ ] `uv run pytest` pasa
- [ ] `uv run ruff check .` pasa
- [ ] Los tests nuevos corren **sin red**, contra fixtures

### Vi el rojo

- [ ] Rompí a propósito la línea que arreglé, corrí la suite, **confirmé que el test se cae**,
      y restauré.

<!--
No es formalidad. Durante el desarrollo esto detectó que un test central seguía verde con el
bug puesto, porque otro camino del código tapaba la regresión. Un test que no puede fallar
imprime lo mismo que uno que sí protege.

Pega acá qué rompiste y qué test cayó:
-->

```
```

## Si tocaste fixtures

- [ ] La causa es pública y no reservada
- [ ] No agregué causas de familia, ni penal con imputados individualizados, ni VIF
- [ ] Revisé la fixture antes de agregarla

## Si tocaste algo con efecto jurídico

<!-- Cómputo de fechas, georreferencia, cuadernos, detección de discrepancias. -->

- [ ] Verifiqué el resultado contra el expediente real en la Oficina Judicial Virtual
- [ ] Si cambié una cita normativa, confirmé artículo y vigencia
