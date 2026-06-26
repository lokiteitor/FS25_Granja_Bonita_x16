# Visualizador y Editor de Regiones para Farming Simulator 25 (FS25)

Esta es una aplicación web interactiva de una sola página diseñada para definir, visualizar y ajustar los límites geográficos y outbounds (cajas delimitadoras) para la creación de mapas, especialmente optimizada para los formatos de Farming Simulator 25 (4096 m y 8192 m).

## Características principales

- 📍 **Ingreso Manual de Coordenadas:** Permite escribir o pegar de forma manual las coordenadas (Latitud y Longitud) del centro de tu mapa en los campos de entrada del panel HUD.
- 📐 **Selección de Tamaños Estándar (4096m y 8192m):** 
  - **4096 m (4x):** Cuadrícula de 4.1 km de lado.
  - **8192 m (16x):** Cuadrícula de 8.2 km de lado.
- 🗺️ **Arrastre Interactivo de Región:** Haz clic y arrastra el área resaltada directamente en el mapa mundial. Al arrastrarla, **las coordenadas del centro de la zona y los límites cardinales en el panel HUD se actualizan de forma continua e instantánea**.
- 🌐 **Cálculo Preciso de Outbounds (Límites):** Utiliza fórmulas de proyección geodésica basadas en el coseno de la latitud para calcular las coordenadas límite Norte, Sur, Este y Oeste reales.
- 📐 **Métricas de Área Físicas:** Calcula en tiempo real las dimensiones y área exacta de la región (en kilómetros cuadrados, hectáreas o metros cuadrados) mediante la fórmula de Haversine.
- 🗺️ **Múltiples Capas Base:** Selector flotante para alternar entre mapa oscuro (CartoDB Dark Matter), mapa claro (CartoDB Voyager), fotos de satélite (Esri World Imagery) e OpenStreetMap oficial.
- ⚡ **Copiado Rápido al Portapapeles:** Botones de copia integrados para:
  - Coordenadas de centro (`lat,lng`).
  - Caja delimitadora en formato JSON.
  - String BBox estándar (`minlon,minlat,maxlon,maxlat`) para Overpass API.

## Archivos de la Aplicación

- [index.html](file:///home/ddelgado/git/lab/FS25_Granja_Bonita_x16/osm_visualizer/index.html) - Interfaz de usuario con campos de entrada de texto y selector de tamaños segmentado.
- [style.css](file:///home/ddelgado/git/lab/FS25_Granja_Bonita_x16/osm_visualizer/style.css) - Estilos del panel de control en modo oscuro, inputs de texto, botones segmentados y elementos Leaflet.
- [app.js](file:///home/ddelgado/git/lab/FS25_Granja_Bonita_x16/osm_visualizer/app.js) - Inicialización de Leaflet, geocalculador, proyección del coseno de latitud, Haversine y listeners del arrastre global.

## Cómo ejecutarlo

Abre el archivo [index.html](file:///home/ddelgado/git/lab/FS25_Granja_Bonita_x16/osm_visualizer/index.html) en cualquier navegador web moderno (directamente haciendo doble clic o mediante un servidor web local).

1. Ingresa la latitud y longitud central de tu mapa por teclado (por defecto inicia en `27.079910`, `-109.707070` Sonora, México).
2. Selecciona la opción **4096 m** o **8192 m** en el selector.
3. El mapa se centrará en el área y la dibujará de inmediato.
4. Si necesitas reubicarla, arrastra el recuadro brillante en el mapa y copia las coordenadas resultantes.
