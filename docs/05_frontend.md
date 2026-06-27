# 05 — Frontend web de búsqueda semántica

## Descripción

Interfaz web standalone (`chatbot/frontend/index.html`) para demostrar el pipeline RAG
sin necesidad de WhatsApp. Cero dependencias externas — HTML + CSS + JS vanilla.

## Características

### Búsqueda
- Input de texto libre con debounce 380ms
- 5 chips de búsqueda predefinidos (camioneta familiar, SUV automática, pickup diésel...)
- Detección automática de filtros en el texto (`marca:`, `precio ≤`, `km <`)

### Visualización de resultados
- Grid de tarjetas con SVG de silueta de vehículo
- **`sim-bar`**: barra de 4px en la parte superior de cada tarjeta que se llena proporcionalmente al score de similitud coseno (0-100%)
- Badge de porcentaje de similitud por tarjeta
- Ordenamiento por similitud / precio / kilometraje

### Sidebar de filtros
- Marca (Mazda, Toyota, Chevrolet, Renault)
- Tipo de carrocería (SUV, Pickup, Sedán, Hatchback)
- Combustible (Gasolina, Híbrido, Diésel, Eléctrico)
- Precio máximo (slider $20M-$120M)
- Los filtros se concatenan al texto de búsqueda y `extract_sql_filters()` los procesa en el backend

### Sección experimento
- Toggle que muestra los resultados reales del experimento de chunking
- Tabla con las 3 estrategias y sus métricas
- La estrategia ganadora se resalta con CSS `best-row`

### UX
- Skeleton loading durante fetch
- Estado de error con el comando uvicorn si el servidor no responde
- Smart API base: `file://` → `http://localhost:8000`, servidor → URL relativa

## Cómo servir el frontend

El bot FastAPI sirve el HTML en `GET /ui`:

```python
_FRONTEND = pathlib.Path(__file__).parent / "frontend" / "index.html"

@app.get("/ui")
async def frontend():
    return FileResponse(str(_FRONTEND))
```

Un solo proceso:

```bash
cd chatbot
uvicorn chat_whatsapp:app --reload
# Abrir: http://localhost:8000/ui
```

## Tema visual
- Color principal: `#1D9E75` (verde Trébol)
- Logo SVG inline: 4 elipses + círculo + tallo
- Fuente del sistema: `-apple-system, BlinkMacSystemFont, Segoe UI`
- Sin frameworks CSS — todo en `<style>` con CSS custom properties
