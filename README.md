# Radar IA

Diario automático de IA para desarrolladores: los **10 proyectos de GitHub que más crecen** y las **10 noticias más relevantes**, resumidos en español con IA. Se actualiza solo lunes, miércoles y viernes.

- **Coste: 0 €.** Usa GitHub Actions (ejecución), GitHub Pages (alojamiento) y GitHub Models (resúmenes con IA). No necesitas ninguna clave de API.
- **Sin mantenimiento:** si algo falla, se abre un *issue* en el repositorio y GitHub te avisa por email.

## Puesta en marcha (unos 10 minutos, sin instalar nada)

1. **Crea el repositorio.** En GitHub, pulsa **New repository**, ponle de nombre `radar-ia`, márcalo como **Public** (Pages es gratis en repos públicos) y créalo vacío.
2. **Activa Pages.** En el repo, ve a **Settings → Pages** y en *Source* elige **GitHub Actions**.
3. **Sube los archivos.** En la pestaña *Code*, pulsa **uploading an existing file** y arrastra **todo el contenido** de esta carpeta: `config.json`, `README.md`, `.gitignore` y las carpetas `scripts`, `static` y `.github` (la carpeta `data` se crea sola en la primera ejecución). Pulsa **Commit changes**.
   - Comprueba que se haya subido `.github/workflows/actualizar.yml`. Si no aparece, créalo con **Add file → Create new file**, escribe como nombre `.github/workflows/actualizar.yml` y pega su contenido.
4. **Primera edición.** Al subir los archivos se lanza solo. Puedes seguirlo en la pestaña **Actions**, o lanzarlo a mano desde **Actions → Actualizar Radar IA → Run workflow**. Tarda unos 3-5 minutos.
5. **Tu web** estará en `https://TU-USUARIO.github.io/radar-ia/`. Ese es el enlace para compartir con tu comunidad.

### Avisos si algo falla
- Si una actualización falla, se crea un *issue* titulado «Falló la actualización…» con el enlace al registro. Como dueño del repo te llega por email (revisa que en el repo tengas **Watch → All activity** o, como mínimo, *Issues*).
- GitHub además envía un email cuando falla una ejecución programada.
- Si la IA no está disponible (por ejemplo por límite de uso), **la edición se publica igual** con las descripciones originales en inglés. No cuenta como fallo.

## Personalizar

Todo se ajusta en `config.json`, sin tocar código:

| Qué | Dónde |
|---|---|
| Nombre, lema y descripción de la web | `sitio` |
| Temas de GitHub que se vigilan | `github.temas` |
| Cuántos proyectos y noticias por edición | `github.cantidad`, `noticias.cantidad` |
| Mínimo de estrellas al día para entrar | `github.min_estrellas_por_dia` |
| Blogs oficiales que se siguen (RSS) | `noticias.feeds` |
| Palabras vetadas | `lista_negra` |
| Modelo de IA | `ia.modelo` |

Para cambiar los días u horas de actualización, edita la línea `cron` de `.github/workflows/actualizar.yml`. La hora está en UTC: `0 11 * * 1,3,5` = lunes, miércoles y viernes a las 11:00 UTC.

## Cómo funciona

```
GitHub Actions (L-X-V)
  ├─ scripts/collect.py → busca repos en GitHub, noticias en Hacker News y blogs oficiales,
  │                       los ordena, los resume con IA y guarda data/ediciones/AAAA-MM-DD.json
  ├─ commit de data/   → el historial queda en el repo (esto también evita que GitHub pause el cron)
  └─ scripts/build.py  → genera la web estática en site/ y la publica en GitHub Pages
```

**Ranking de proyectos:** se ordenan por *estrellas ganadas al día*, no por el total de estrellas (así no salen siempre los mismos gigantes). En los repos nuevos se usan las estrellas divididas entre los días de vida; en los veteranos, la diferencia con la revisión anterior (`data/historial_estrellas.json`). No se repite nada de las últimas 3 ediciones.

**Ranking de noticias:** puntos en Hacker News más un peso fijo para los blogs oficiales. Si una noticia aparece en varias fuentes, sube.

## Probar en tu ordenador (opcional)

Con Python 3.10 o superior:

```
python scripts/collect.py
python scripts/build.py
python -m http.server 8000 --directory site
```

Sin la variable `GITHUB_TOKEN` funciona igual, pero más lento y sin resúmenes con IA.
