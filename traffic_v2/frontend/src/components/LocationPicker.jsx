import React from 'react';
import MapView from './MapView.jsx';

/** lat/lng inputs + clickable map. value: {lat, lng} as strings; onChange({lat, lng}). */
export default function LocationPicker({ value, onChange, markers = [], height = 240 }) {
  const lat = value.lat === '' || value.lat == null ? NaN : Number(value.lat);
  const lng = value.lng === '' || value.lng == null ? NaN : Number(value.lng);
  return (
    <div className="picker">
      <div className="row">
        <label className="grow">Latitude
          <input type="number" step="any" min="-90" max="90" value={value.lat ?? ''} placeholder="e.g. 28.6139"
            onChange={(e) => onChange({ ...value, lat: e.target.value })} />
        </label>
        <label className="grow">Longitude
          <input type="number" step="any" min="-180" max="180" value={value.lng ?? ''} placeholder="e.g. 77.2090"
            onChange={(e) => onChange({ ...value, lng: e.target.value })} />
        </label>
      </div>
      <div className="hint">Click the map to set the location.</div>
      <MapView height={height} markers={markers} pick={{ lat, lng }}
        onPick={(la, ln) => onChange({ lat: String(la), lng: String(ln) })} />
    </div>
  );
}
