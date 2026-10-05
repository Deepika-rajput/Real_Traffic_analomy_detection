import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

/**
 * Small Leaflet wrapper (OpenStreetMap tiles, needs internet for the tiles only).
 * markers: [{lat, lng, title, color, radius}]   lines: [{from:[lat,lng], to:[lat,lng], color}]
 * onPick(lat, lng): makes the map clickable (used to choose a camera/authority location).
 * pick: {lat, lng} marker for the currently picked location.
 */
export default function MapView({ markers = [], lines = [], pick, onPick, height = 300, center }) {
  const el = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  const pickCb = useRef(onPick);
  pickCb.current = onPick;

  useEffect(() => {
    const m = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(center || [20.5, 78.9], center ? 12 : 4);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
    }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.on('click', (e) => pickCb.current && pickCb.current(+e.latlng.lat.toFixed(6), +e.latlng.lng.toFixed(6)));
    map.current = m;
    setTimeout(() => m.invalidateSize(), 50);
    return () => { m.remove(); map.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = map.current, g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const pts = [];
    lines.forEach((l) => {
      L.polyline([l.from, l.to], { color: l.color || '#64748b', weight: 2, dashArray: '6 6' }).addTo(g);
    });
    markers.forEach((mk) => {
      if (mk.lat == null || mk.lng == null) return;
      L.circleMarker([mk.lat, mk.lng], {
        radius: mk.radius || 8, color: '#fff', weight: 2, fillColor: mk.color || '#ef4444', fillOpacity: 0.95,
      }).bindTooltip(mk.title || '').addTo(g);
      pts.push([mk.lat, mk.lng]);
    });
    if (pick && pick.lat != null && pick.lng != null && !isNaN(pick.lat) && !isNaN(pick.lng)) {
      L.circleMarker([pick.lat, pick.lng], { radius: 9, color: '#0f172a', weight: 3, fillColor: '#facc15', fillOpacity: 1 })
        .bindTooltip('selected location').addTo(g);
      pts.push([pick.lat, pick.lng]);
    }
    if (pts.length === 1) m.setView(pts[0], Math.max(m.getZoom(), 13));
    else if (pts.length > 1) m.fitBounds(pts, { padding: [30, 30], maxZoom: 15 });
  }, [markers, lines, pick]);

  return <div ref={el} className="map" style={{ height, cursor: onPick ? 'crosshair' : undefined }} />;
}
