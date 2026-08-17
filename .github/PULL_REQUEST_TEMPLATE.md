# Pull request

## Permiso de licencia

> La [PolyForm Strict 1.0.0](../LICENSE.md) **no otorga derecho a modificar el software**.
> Un PR sin permiso previo no se puede aceptar, por mucho que el cambio sea bueno.
> Ver [CONTRIBUTING.md](../CONTRIBUTING.md).

- [ ] Tengo permiso escrito para este trabajo, otorgado en el issue #___

## Qué cambia y por qué

<!-- Un párrafo. Qué problema resuelve, no qué archivos tocaste. -->

Cierra #

## Las cinco reglas que no se negocian

- [ ] **No agrega ninguna capacidad de escritura** sobre sistemas del Poder Judicial, ni
      siquiera desactivada o detrás de una bandera.
- [ ] **No baja el intervalo mínimo** de 5 segundos entre peticiones.
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
