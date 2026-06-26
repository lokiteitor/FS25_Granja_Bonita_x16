# Generador de Mapas para FS25 y OSM

Este proyecto contiene una suite de herramientas en Python diseñadas para generar mapas de zonificación y datos vectoriales OpenStreetMap (OSM) para **Farming Simulator 25 (FS25)**, utilizando un sistema de cuadrícula PLSS (Public Land Survey System) de 8x8 millas.

## Estructura del Proyecto

El proyecto se compone de dos herramientas principales:

| Script | Descripción | Entradas / Características | Salidas |
| :--- | :--- | :--- | :--- |
| [`genmap.py`](file:///home/ddelgado/git/osm_generator/genmap.py) | Generador de Mapas | Subdivisión PLSS recursiva de parcelas agrícolas, red de caminos, canales, zonas urbanas e industriales | Imagen PNG de alta resolución (8192x8192 px) |
| [`genosm.py`](file:///home/ddelgado/git/osm_generator/genosm.py) | Generador de Datos OSM | Exportación de la misma topología a formato XML de OpenStreetMap (.osm) georreferenciado | Archivo XML de OpenStreetMap (.osm) |

---

## Detalle de las Herramientas

### 2. Generador de Mapas (`genmap.py`)

Visualiza y renderiza el diseño catastral y de zonificación en una imagen PNG de alta resolución ($8192 \times 8192$ píxeles).

* **Estructura de Cuadrícula (PLSS)**: Define un área de 8x8 millas (secciones de 1x1 milla cada una).
* **Características**:
  * **Parcelas Agrícolas**: Subdivisión binaria recursiva de secciones en parcelas rectangulares. Los bloques cercanos al pueblo tienen más subdivisiones (campos pequeños) y los bordes tienen menos (campos grandes). Algunos campos adyacentes se fusionan aleatoriamente para crear formas en "L".
  * **Cuerpo de Agua y Canales**: Incluye un embalse artificial en el este del pueblo y canales de agua de 26 píxeles de ancho a lo largo de las carreteras principales.
  * **Pueblo (Town)**: Ocupa una sección completa de 1x1 milla, con una cuadrícula urbana interna de 8x8 bloques (7 calles internas en cada dirección).
  * **Bosques**: 3 grandes bosques rectangulares integrados en la cuadrícula de caminos.
  * **Granjas y Zonas Industriales**: 5 granjas (farmyards) ubicadas estratégicamente a lo largo de carreteras primarias y 2 zonas industriales con calles internas de servicio.
  * **Invernaderos**: Un sector especializado al noreste con 4 invernaderos de cristal detallados.
* **Salida generada**:
  * [`outputs/zoning_map.png`](file:///home/ddelgado/git/osm_generator/outputs/zoning_map.png)

### 3. Generador de Datos OSM (`genosm.py`)

Convierte y exporta la misma distribución espacial y topología definida en el generador de mapas directamente a un formato vectorial XML estándar de OpenStreetMap (`.osm`).

* **Georreferenciación**: Centrado en coordenadas GPS reales `(62.12422301, 90.81880494)`.
* **Características**:
  * **Recorte Geométrico Limpio**: Implementa un algoritmo de sustracción rectangular recursivo (`subtract_rects`) para recortar las parcelas de cultivo donde se solapan con otros elementos (pueblos, bosques, embalses, granjas, etc.), garantizando que no haya geometrías duplicadas o superpuestas.
  * **Conectividad Topológica**: Los caminos horizontales y verticales están conectados correctamente mediante nodos compartidos en las intersecciones.
  * **Etiquetado OSM Estándar**: Cada elemento exportado incluye sus etiquetas semánticas (`landuse=farmland`, `highway=primary`, `waterway=canal`, `building=greenhouse`, etc.).
* **Salida generada**:
  * [`outputs/zoning_map.osm`](file:///home/ddelgado/git/osm_generator/outputs/zoning_map.osm)

---

## Requisitos y Uso

### Requisitos

Asegúrate de tener instalado Python 3 y las siguientes dependencias:

```bash
pip install pillow numpy
```

### Ejecución

Puedes ejecutar los scripts para generar todos los mapas y datos:

1. **Generar la imagen de zonificación (Zoning Map)**:
   ```bash
   python genmap.py
   ```
2. **Generar los datos vectoriales OSM (OpenStreetMap XML)**:
   ```bash
   python genosm.py
   ```

Todos los resultados se guardarán automáticamente en el directorio [`outputs/`](file:///home/ddelgado/git/osm_generator/outputs).


## Coordenadas de Referencia (OSM):
Center coordinates: (62.12422301, 90.81880494)
Distance from center: 4096.0 meters (Map Size: 8192x8192m)
Computed Bounding Box (W, S, E, N): (90.74002036272485, 62.08738679702157, 90.89758951727516, 62.16105922297843)

