// Bounding Box Map Generator Logic (Manual Coordinates & Sizes)
document.addEventListener('DOMContentLoaded', () => {
    // ----------------------------------------------------
    // 1. Map Initialization
    // ----------------------------------------------------
    const map = L.map('map', {
        zoomControl: true,
        center: [62.12422301, 90.81880494],
        zoom: 12
    });

    // Define Tile Layers
    const layers = {
        dark: L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            maxZoom: 20,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
        }),
        light: L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            maxZoom: 20,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
        }),
        satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
        }),
        osm: L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        })
    };

    // Set Default Layer
    layers.dark.addTo(map);

    // Layer Controls Logic
    const layerButtons = {
        dark: document.getElementById('layer-dark'),
        light: document.getElementById('layer-light'),
        satellite: document.getElementById('layer-satellite'),
        osm: document.getElementById('layer-osm')
    };

    function switchLayer(selectedKey) {
        Object.keys(layers).forEach(key => {
            map.removeLayer(layers[key]);
            layerButtons[key].classList.remove('active');
        });
        
        layers[selectedKey].addTo(map);
        layerButtons[selectedKey].classList.add('active');
        
        // Force Leaflet to recalculate container size and realign tiles
        setTimeout(() => {
            map.invalidateSize();
        }, 50);
    }

    Object.keys(layerButtons).forEach(key => {
        layerButtons[key].addEventListener('click', () => switchLayer(key));
    });

    // Update live status bar coordinates
    function updateLiveCoordinates() {
        const center = map.getCenter();
        const zoom = map.getZoom();
        document.getElementById('map-center-live').innerText = `Lat: ${center.lat.toFixed(5)}, Lng: ${center.lng.toFixed(5)}`;
        document.getElementById('map-zoom-live').innerText = zoom;
    }

    map.on('move', updateLiveCoordinates);
    map.on('zoomend', updateLiveCoordinates);
    updateLiveCoordinates();

    // ----------------------------------------------------
    // 2. Global State & DOM elements
    // ----------------------------------------------------
    let currentBounds = null; // { minlat, minlon, maxlat, maxlon, centerLat, centerLng, size, widthKm, heightKm, areaKm2 }
    let mapOverlayGroup = L.featureGroup().addTo(map);

    // Inputs
    const inputLat = document.getElementById('input-lat');
    const inputLng = document.getElementById('input-lng');
    const size4096 = document.getElementById('size-4096');
    const size8192 = document.getElementById('size-8192');

    // Outbound text nodes
    const elMinLat = document.getElementById('bound-minlat');
    const elMinLon = document.getElementById('bound-minlon');
    const elMaxLat = document.getElementById('bound-maxlat');
    const elMaxLon = document.getElementById('bound-maxlon');
    
    const elSpanWidth = document.getElementById('span-width');
    const elSpanHeight = document.getElementById('span-height');
    const elSpanArea = document.getElementById('span-area');
    const elPlayableWidth = document.getElementById('playable-width');
    const elPlayableArea = document.getElementById('playable-area');

    // Leaflet Layers references
    let rect = null;
    let innerRect = null;
    let centerMarker = null;
    let cornerMarkers = [];

    // ----------------------------------------------------
    // 3. Helper calculations
    // ----------------------------------------------------
    // Haversine formula to compute distance in km
    function getHaversineDistance(lat1, lon1, lat2, lon2) {
        const R = 6371; // Earth Radius in km
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = 
            Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
            Math.sin(dLon/2) * Math.sin(dLon/2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        return R * c;
    }

    // Format dimension spans
    function formatDimension(valKm, degDiff) {
        let physicalStr = '';
        if (valKm >= 1) {
            physicalStr = `${valKm.toFixed(2)} km`;
        } else {
            physicalStr = `${(valKm * 1000).toFixed(0)} m`;
        }
        return `${physicalStr} (~${degDiff.toFixed(4)}°)`;
    }

    function formatArea(areaKm2) {
        if (areaKm2 >= 1) {
            return `${areaKm2.toFixed(3)} km²`;
        } else {
            const hectares = areaKm2 * 100;
            if (hectares >= 1) {
                return `${hectares.toFixed(2)} ha`;
            } else {
                const m2 = areaKm2 * 1000000;
                return `${m2.toFixed(0)} m²`;
            }
        }
    }

    // Recalculate bounds coordinates from inputs
    function recalculateBounds() {
        const lat = parseFloat(inputLat.value);
        const lng = parseFloat(inputLng.value);

        if (isNaN(lat) || isNaN(lng)) return false;

        const size = size4096.checked ? 4096 : 8192;

        // Bounding box formulas based on latitude-cosine projection
        const deltaLat = (size / 2) / 111111;
        const deltaLon = (size / 2) / (111111 * Math.cos(lat * Math.PI / 180));

        const minlat = lat - deltaLat;
        const maxlat = lat + deltaLat;
        const minlon = lng - deltaLon;
        const maxlon = lng + deltaLon;

        const widthKm = getHaversineDistance(lat, minlon, lat, maxlon);
        const heightKm = getHaversineDistance(minlat, lng, maxlat, lng);
        const areaKm2 = widthKm * heightKm;

        // Calculate inner playable dimensions (2046m inwards from borders)
        const playableSize = Math.max(0, size - (2046 * 2));
        const borderDeltaLat = 2046 / 111111;
        const borderDeltaLon = 2046 / (111111 * Math.cos(lat * Math.PI / 180));

        const innerWidthKm = Math.max(0, widthKm - (2046 * 2 / 1000));
        const innerHeightKm = Math.max(0, heightKm - (2046 * 2 / 1000));
        const innerAreaKm2 = innerWidthKm * innerHeightKm;

        currentBounds = {
            minlat,
            minlon,
            maxlat,
            maxlon,
            centerLat: lat,
            centerLng: lng,
            size,
            widthKm,
            heightKm,
            areaKm2,
            // Playable limits
            playableSize,
            borderDeltaLat,
            borderDeltaLon,
            innerWidthKm,
            innerHeightKm,
            innerAreaKm2
        };
        return true;
    }

    // Update HUD display values
    function updateHUDTextOnly() {
        if (!currentBounds) return;

        // Update inputs only if they differ significantly from current values, to preserve selection/cursor
        const currentLatVal = parseFloat(inputLat.value);
        const currentLngVal = parseFloat(inputLng.value);
        if (isNaN(currentLatVal) || Math.abs(currentLatVal - currentBounds.centerLat) > 0.000001) {
            inputLat.value = currentBounds.centerLat.toFixed(6);
        }
        if (isNaN(currentLngVal) || Math.abs(currentLngVal - currentBounds.centerLng) > 0.000001) {
            inputLng.value = currentBounds.centerLng.toFixed(6);
        }

        // Update card coordinates
        elMinLat.innerText = currentBounds.minlat.toFixed(6);
        elMinLon.innerText = currentBounds.minlon.toFixed(6);
        elMaxLat.innerText = currentBounds.maxlat.toFixed(6);
        elMaxLon.innerText = currentBounds.maxlon.toFixed(6);

        // Update physical metrics
        const latSpan = currentBounds.maxlat - currentBounds.minlat;
        const lonSpan = currentBounds.maxlon - currentBounds.minlon;

        // Outer BBox Spans
        elSpanWidth.innerText = formatDimension(currentBounds.widthKm, lonSpan);
        elSpanHeight.innerText = formatDimension(currentBounds.heightKm, latSpan);
        elSpanArea.innerText = formatArea(currentBounds.areaKm2);

        // Playable Spans (Inner BBox)
        const playableLatSpan = Math.max(0, latSpan - (currentBounds.borderDeltaLat * 2));
        const playableLonSpan = Math.max(0, lonSpan - (currentBounds.borderDeltaLon * 2));
        elPlayableWidth.innerText = formatDimension(currentBounds.innerWidthKm, playableLonSpan);
        elPlayableArea.innerText = formatArea(currentBounds.innerAreaKm2);
    }

    // ----------------------------------------------------
    // 4. Drawing & Dragging
    // ----------------------------------------------------
    function drawBoundsOnMap(shouldRecenter = false) {
        mapOverlayGroup.clearLayers();
        cornerMarkers = [];

        if (!currentBounds) return;

        const { minlat, minlon, maxlat, maxlon, centerLat, centerLng } = currentBounds;
        const bounds = [[minlat, minlon], [maxlat, maxlon]];

        // 1. Rectangle BBox (Outer boundary)
        rect = L.rectangle(bounds, {
            color: '#06b6d4',
            weight: 3,
            fillColor: '#06b6d4',
            fillOpacity: 0.04,
            dashArray: '5, 5',
            className: 'glowing-bounds'
        }).addTo(mapOverlayGroup);

        // 1b. Rectangle BBox (Inner Playable Boundary - 2046m offset)
        const innerMinLat = minlat + currentBounds.borderDeltaLat;
        const innerMaxLat = maxlat - currentBounds.borderDeltaLat;
        const innerMinLon = minlon + currentBounds.borderDeltaLon;
        const innerMaxLon = maxlon - currentBounds.borderDeltaLon;

        const innerBounds = [
            [Math.min(innerMinLat, innerMaxLat), Math.min(innerMinLon, innerMaxLon)],
            [Math.max(innerMinLat, innerMaxLat), Math.max(innerMinLon, innerMaxLon)]
        ];

        innerRect = L.rectangle(innerBounds, {
            color: '#f97316',          // Coral / Orange
            weight: 2,
            fillColor: '#f97316',
            fillOpacity: 0.08,
            dashArray: '3, 4',
            className: 'playable-bounds'
        }).addTo(mapOverlayGroup);

        if (rect.getElement()) {
            rect.getElement().style.cursor = 'grab';
        }
        rect.on('add', () => {
            if (rect.getElement()) rect.getElement().style.cursor = 'grab';
        });

        // Function to update popups contents dynamically
        const updatePopups = () => {
            rect.setPopupContent(`
                <div class="popup-title"><i class="fa-solid fa-expand"></i> Límite Total del Mapa (${currentBounds.size}m)</div>
                <div class="popup-coords">
                    <strong>Norte:</strong> ${currentBounds.maxlat.toFixed(5)}<br>
                    <strong>Sur:</strong> ${currentBounds.minlat.toFixed(5)}<br>
                    <strong>Este:</strong> ${currentBounds.maxlon.toFixed(5)}<br>
                    <strong>Oeste:</strong> ${currentBounds.minlon.toFixed(5)}
                </div>
            `);

            const curInnerMinLat = currentBounds.minlat + currentBounds.borderDeltaLat;
            const curInnerMaxLat = currentBounds.maxlat - currentBounds.borderDeltaLat;
            const curInnerMinLon = currentBounds.minlon + currentBounds.borderDeltaLon;
            const curInnerMaxLon = currentBounds.maxlon - currentBounds.borderDeltaLon;

            innerRect.setPopupContent(`
                <div class="popup-title" style="color:#f97316;"><i class="fa-solid fa-gamepad"></i> Área Jugable (${currentBounds.playableSize}m)</div>
                <div class="popup-coords">
                    <strong>Norte:</strong> ${curInnerMaxLat.toFixed(5)}<br>
                    <strong>Sur:</strong> ${curInnerMinLat.toFixed(5)}<br>
                    <strong>Este:</strong> ${curInnerMaxLon.toFixed(5)}<br>
                    <strong>Oeste:</strong> ${curInnerMinLon.toFixed(5)}<br>
                    <span style="color:#94a3b8; font-size:10px;">Borde no jugable: 2046m desde el límite</span>
                </div>
            `);

            centerMarker.setPopupContent(`
                <div class="popup-title" style="color:#ec4899;"><i class="fa-solid fa-crosshairs"></i> Centro de Región</div>
                <div class="popup-coords">
                    <strong>Lat:</strong> ${currentBounds.centerLat.toFixed(6)}<br>
                    <strong>Lng:</strong> ${currentBounds.centerLng.toFixed(6)}
                </div>
            `);
        };

        // 2. Corner Circles
        const corners = [
            { key: 'nw', pos: [maxlat, minlon], label: 'Nor-Oeste' },
            { key: 'ne', pos: [maxlat, maxlon], label: 'Nor-Este' },
            { key: 'sw', pos: [minlat, minlon], label: 'Sur-Oeste' },
            { key: 'se', pos: [minlat, maxlon], label: 'Sur-Este' }
        ];

        corners.forEach(corner => {
            const marker = L.circleMarker(corner.pos, {
                radius: 4,
                color: '#6366f1',
                fillColor: '#ffffff',
                fillOpacity: 1,
                weight: 2
            })
            .addTo(mapOverlayGroup)
            .bindTooltip(corner.label, { direction: 'top', className: 'corner-tooltip' });
            
            cornerMarkers.push(marker);
        });

        // 3. Center Marker
        centerMarker = L.circleMarker([centerLat, centerLng], {
            radius: 8,
            color: '#ec4899',
            fillColor: '#ec4899',
            fillOpacity: 0.7,
            weight: 2
        }).addTo(mapOverlayGroup);

        rect.bindPopup('');
        innerRect.bindPopup('');
        centerMarker.bindPopup('');
        updatePopups();

        // 4. Center map view if requested
        if (shouldRecenter) {
            map.fitBounds(bounds, {
                padding: [60, 60],
                maxZoom: 16,
                animate: true,
                duration: 1.2
            });
        }

        // ----------------------------------------------------
        // Dragging event handlers
        // ----------------------------------------------------
        let isDragging = false;
        let dragStartLatLng = null;
        let originalCenter = null;

        const onDragStart = (e) => {
            isDragging = true;
            dragStartLatLng = e.latlng;
            originalCenter = {
                lat: currentBounds.centerLat,
                lng: currentBounds.centerLng
            };
            map.dragging.disable();
            if (rect.getElement()) {
                rect.getElement().style.cursor = 'grabbing';
            }
            L.DomEvent.stopPropagation(e);
        };

        const onDragMove = (e) => {
            if (!isDragging) return;

            let clientEvent = e;
            if (e.touches && e.touches.length > 0) {
                clientEvent = e.touches[0];
            } else if (e.changedTouches && e.changedTouches.length > 0) {
                clientEvent = e.changedTouches[0];
            }

            const currentLatLng = map.mouseEventToLatLng(clientEvent);
            if (!currentLatLng) return;

            const latDelta = currentLatLng.lat - dragStartLatLng.lat;
            const lonDelta = currentLatLng.lng - dragStartLatLng.lng;

            const newCenterLat = originalCenter.lat + latDelta;
            const newCenterLng = originalCenter.lng + lonDelta;

            // Shift active bounds values
            currentBounds.centerLat = newCenterLat;
            currentBounds.centerLng = newCenterLng;

            // Recalculate bounds with lat-cosine at new center coordinate
            const deltaLat = (currentBounds.size / 2) / 111111;
            const deltaLon = (currentBounds.size / 2) / (111111 * Math.cos(newCenterLat * Math.PI / 180));

            currentBounds.minlat = newCenterLat - deltaLat;
            currentBounds.maxlat = newCenterLat + deltaLat;
            currentBounds.minlon = newCenterLng - deltaLon;
            currentBounds.maxlon = newCenterLng + deltaLon;

            // Recalculate inner bounds offset at new center
            currentBounds.borderDeltaLat = 2046 / 111111;
            currentBounds.borderDeltaLon = 2046 / (111111 * Math.cos(newCenterLat * Math.PI / 180));

            const curInnerMinLat = currentBounds.minlat + currentBounds.borderDeltaLat;
            const curInnerMaxLat = currentBounds.maxlat - currentBounds.borderDeltaLat;
            const curInnerMinLon = currentBounds.minlon + currentBounds.borderDeltaLon;
            const curInnerMaxLon = currentBounds.maxlon - currentBounds.borderDeltaLon;

            // Recalculate dimensions at new latitude
            const widthKm = getHaversineDistance(newCenterLat, currentBounds.minlon, newCenterLat, currentBounds.maxlon);
            const heightKm = getHaversineDistance(currentBounds.minlat, newCenterLng, currentBounds.maxlat, newCenterLng);
            currentBounds.widthKm = widthKm;
            currentBounds.heightKm = heightKm;
            currentBounds.areaKm2 = widthKm * heightKm;

            // Recalculate inner dimensions at new latitude
            currentBounds.innerWidthKm = Math.max(0, widthKm - (2046 * 2 / 1000));
            currentBounds.innerHeightKm = Math.max(0, heightKm - (2046 * 2 / 1000));
            currentBounds.innerAreaKm2 = currentBounds.innerWidthKm * currentBounds.innerHeightKm;

            // Move shapes in map
            rect.setBounds([[currentBounds.minlat, currentBounds.minlon], [currentBounds.maxlat, currentBounds.maxlon]]);
            
            const adjInnerMinLat = Math.min(curInnerMinLat, curInnerMaxLat);
            const adjInnerMaxLat = Math.max(curInnerMinLat, curInnerMaxLat);
            const adjInnerMinLon = Math.min(curInnerMinLon, curInnerMaxLon);
            const adjInnerMaxLon = Math.max(curInnerMinLon, curInnerMaxLon);
            
            innerRect.setBounds([[adjInnerMinLat, adjInnerMinLon], [adjInnerMaxLat, adjInnerMaxLon]]);

            centerMarker.setLatLng([newCenterLat, newCenterLng]);
            cornerMarkers[0].setLatLng([currentBounds.maxlat, currentBounds.minlon]); // NW
            cornerMarkers[1].setLatLng([currentBounds.maxlat, currentBounds.maxlon]); // NE
            cornerMarkers[2].setLatLng([currentBounds.minlat, currentBounds.minlon]); // SW
            cornerMarkers[3].setLatLng([currentBounds.minlat, currentBounds.maxlon]); // SE

            // Update display values in HUD inputs and compass
            updateHUDTextOnly();

            if (e.cancelable) {
                e.preventDefault();
            }
        };

        const onDragEnd = () => {
            if (!isDragging) return;
            isDragging = false;
            map.dragging.enable();
            if (rect.getElement()) {
                rect.getElement().style.cursor = 'grab';
            }
            updatePopups();
        };

        rect.on('mousedown', onDragStart);
        rect.on('touchstart', onDragStart);

        window.addEventListener('mousemove', onDragMove);
        window.addEventListener('touchmove', onDragMove, { passive: false });
        window.addEventListener('mouseup', onDragEnd);
        window.addEventListener('touchend', onDragEnd);

        rect.on('remove', () => {
            window.removeEventListener('mouseup', onDragEnd);
            window.removeEventListener('touchend', onDragEnd);
            window.removeEventListener('mousemove', onDragMove);
            window.removeEventListener('touchmove', onDragMove);
        });
    }

    // ----------------------------------------------------
    // 5. Input Listeners
    // ----------------------------------------------------
    function handleManualInput() {
        if (recalculateBounds()) {
            drawBoundsOnMap(false); // Update bounds geometry but don't force viewport reset (allows typing smoothly)
            updateHUDTextOnly();
        }
    }

    function handleManualInputWithRecenter() {
        if (recalculateBounds()) {
            drawBoundsOnMap(true); // Recenter map on new coordinate
            updateHUDTextOnly();
        }
    }

    inputLat.addEventListener('input', handleManualInput);
    inputLng.addEventListener('input', handleManualInput);
    
    // Recenter map on change/blur of coordinate boxes
    inputLat.addEventListener('change', handleManualInputWithRecenter);
    inputLng.addEventListener('change', handleManualInputWithRecenter);

    // Size Selection Change Listeners
    size4096.addEventListener('change', handleManualInputWithRecenter);
    size8192.addEventListener('change', handleManualInputWithRecenter);

    // Recenter Button click
    document.getElementById('btn-recenter').addEventListener('click', () => {
        if (currentBounds) {
            const bounds = [[currentBounds.minlat, currentBounds.minlon], [currentBounds.maxlat, currentBounds.maxlon]];
            map.fitBounds(bounds, {
                padding: [60, 60],
                maxZoom: 16,
                animate: true
            });
        }
    });

    // ----------------------------------------------------
    // 6. Export/Copy Listeners
    // ----------------------------------------------------
    function copyTextToClipboard(text, successMessage, buttonElement) {
        navigator.clipboard.writeText(text).then(() => {
            const originalHTML = buttonElement.innerHTML;
            buttonElement.innerHTML = `<i class="fa-solid fa-check" style="color:var(--accent-emerald)"></i> ¡Copiado!`;
            buttonElement.style.borderColor = 'var(--accent-emerald)';
            setTimeout(() => {
                buttonElement.innerHTML = originalHTML;
                buttonElement.style.borderColor = '';
            }, 2000);
        }).catch(err => {
            console.error('Error copying text:', err);
            alert('Error al copiar al portapapeles.');
        });
    }

    document.getElementById('btn-copy-center').addEventListener('click', function() {
        if (currentBounds) {
            const text = `${currentBounds.centerLat.toFixed(8)},${currentBounds.centerLng.toFixed(8)}`;
            copyTextToClipboard(text, 'Centro copiado', this);
        }
    });

    document.getElementById('btn-copy-bounds').addEventListener('click', function() {
        if (currentBounds) {
            const jsonText = JSON.stringify({
                minlat: currentBounds.minlat,
                minlon: currentBounds.minlon,
                maxlat: currentBounds.maxlat,
                maxlon: currentBounds.maxlon,
                center: {
                    lat: currentBounds.centerLat,
                    lng: currentBounds.centerLng
                },
                size: currentBounds.size,
                dimensions: {
                    widthKm: currentBounds.widthKm,
                    heightKm: currentBounds.heightKm,
                    areaKm2: currentBounds.areaKm2
                }
            }, null, 2);
            copyTextToClipboard(jsonText, 'JSON copiado', this);
        }
    });

    document.getElementById('btn-copy-bbox').addEventListener('click', function() {
        if (currentBounds) {
            const text = `${currentBounds.minlon.toFixed(8)},${currentBounds.minlat.toFixed(8)},${currentBounds.maxlon.toFixed(8)},${currentBounds.maxlat.toFixed(8)}`;
            copyTextToClipboard(text, 'BBox copiado', this);
        }
    });

    // ----------------------------------------------------
    // 7. Initial Load Setup
    // ----------------------------------------------------
    recalculateBounds();
    drawBoundsOnMap(true);
    updateHUDTextOnly();
});
