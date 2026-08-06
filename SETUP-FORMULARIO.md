# Puesta en marcha: publicación de piezas por formulario

El código ya está en el repo (`scripts/sync_piezas.py` + `.github/workflows/sync-piezas.yml`).
Falta la parte de Google y dos secretos, que solo se hacen una vez. Sigue este orden.

## 1. Crear el formulario de Google

En [forms.google.com](https://forms.google.com), formulario nuevo titulado **"Añadir pieza a la web"**.
Preguntas, en este orden:

| # | Pregunta | Tipo | Obligatoria |
|---|---|---|---|
| 1 | Nombre de la pieza | Respuesta corta | Sí |
| 2 | Descripción | Párrafo | Sí |
| 3 | Foto | Subir archivo · 1 archivo · solo imágenes · máx 10 MB | Sí |
| 4 | Descripción de la foto (para personas con discapacidad visual) | Respuesta corta | Sí |
| 5 | Estado | Varias opciones: `Pieza única` / `Por encargo` / `Vendido` | Sí |
| 6 | Precio en euros (deja vacío si es a consultar) | Respuesta corta | No |
| 7 | Enlace al post de Instagram | Respuesta corta | No |

En Configuración → Presentación, mensaje de confirmación:
*"Recibido. La pieza aparecerá en la web dentro de una hora."*

> La subida de archivos exige que quien responde tenga sesión de Google iniciada.
> Confirma que la clienta está conectada a Gmail en su móvil antes de entregar.

## 2. Compartir la carpeta de fotos de Drive

Las fotos del formulario caen en `Respuestas de Añadir pieza a la web / Foto` en tu Drive.
Clic derecho en esa carpeta → Compartir → **Cualquier persona con el enlace, Lector**.

## 3. Publicar la hoja de respuestas como CSV

En el formulario → Respuestas → icono de Sheets (crea la hoja vinculada). Después, en la hoja:
`Archivo → Compartir → Publicar en la web → pestaña de respuestas → Valores separados por comas (.csv) → Publicar`.

Copia la URL resultante (`https://docs.google.com/spreadsheets/d/e/2PACX-…&output=csv`).

## 4. Columnas extra en la hoja

A la derecha de las columnas del formulario, añade a mano estos encabezados
(las filas nuevas los dejan en blanco, que es el valor por defecto deseado):

| Columna | Valores | Efecto |
|---|---|---|
| `Ocultar` | `SI` o vacío | `SI` quita la pieza de la web sin borrar la fila |
| `Orden` | número o vacío | Fuerza la posición (menor primero); vacío = más reciente arriba |
| `Nombre EN` | texto o vacío | Traducción del nombre para el botón EN de la web |
| `Descripción EN` | texto o vacío | Traducción de la descripción |

## 5. Migrar las 13 piezas actuales

Abre `scripts/migracion_piezas.csv` (este repo) y pega sus 13 filas en la hoja de
respuestas, bajo los mismos encabezados. Las celdas de Foto contienen rutas
`img/post-XX.jpg`: el script las usa tal cual, sin tocar Drive. Las traducciones EN
ya van incluidas.

## 6. Secretos del repositorio

En GitHub → repo → Settings → Secrets and variables → Actions → New repository secret:

| Nombre | Valor |
|---|---|
| `SHEET_CSV_URL` | La URL del CSV publicada en el paso 3 |
| `PAT_COMMIT` | Un fine-grained PAT con permiso Contents: Read & write **solo sobre este repo** |

El PAT se crea en github.com → Settings (perfil) → Developer settings → Fine-grained tokens.
Se usa en lugar del token automático para que los commits del bot cuenten como actividad
y GitHub no desactive el cron a los 60 días.

## 7. Primera ejecución y pruebas

Actions → "Sincronizar piezas" → Run workflow. Comprueba:

1. Formulario completo → la pieza sale la primera de la parrilla, foto derecha, < 300 KB.
2. Sin precio ni Instagram → tarjeta sin precio y sin "Ver el post", sin huecos.
3. Reenviar con el mismo nombre y otra foto → una sola tarjeta actualizada, sin duplicados.
4. `Ocultar = SI` → la tarjeta desaparece; la fila y la foto siguen existiendo.
5. `Orden = 1` en una pieza vieja → pasa a la primera posición.
6. Romper `SHEET_CSV_URL` a propósito → el workflow falla y la web no cambia.
7. Ejecutar sin cambios en la hoja → no se crea ningún commit.
8. Foto de móvil en vertical/apaisado → sale derecha.
9. Nombre con tildes y comillas → slug limpio, texto intacto en la tarjeta.

## 8. Tarjeta para la clienta (imprimir o WhatsApp)

> **Para añadir una pieza a la web**
> 1. Abre el enlace del formulario (guárdalo en la pantalla de inicio del móvil).
> 2. Rellena los datos, sube UNA foto y pulsa Enviar.
> 3. La pieza aparece en la web en menos de una hora.
> 4. ¿Te equivocaste? Vuelve a enviar el formulario con **exactamente el mismo nombre**
>    y la versión nueva sustituye a la antigua.
> Para cualquier otra cosa (quitar una pieza, cambiar el orden): escríbeme.

No le menciones la hoja de cálculo, GitHub ni la palabra "deploy".

## Mejora opcional: publicación al instante

En la hoja → Extensiones → Apps Script, añade un trigger `onFormSubmit` que llame a la
API `repository_dispatch` de GitHub con un PAT guardado en Script Properties, y añade
`repository_dispatch: types: [nueva-pieza]` a los triggers del workflow. Resultado:
la pieza está en la web ~90 segundos después de enviar, con el cron de respaldo.
