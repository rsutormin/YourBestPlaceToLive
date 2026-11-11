import type { Feature } from "geojson";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { countries, type CountryProperties } from "./countries";

export interface CountryPointer {
  country: CountryProperties;
  lat: number;
  lng: number;
  clientX: number;
  clientY: number;
}

export interface CountryMapHandlers {
  onHover: (pointer: CountryPointer | null) => void;
  onClick: (pointer: CountryPointer | null) => void;
}

export interface CountryMap {
  map: L.Map;
  setMetricColors(colors: ReadonlyMap<string, string> | null): void;
  highlightCountry(code: string | null): CountryPointer | null;
  selectCountry(code: string | null): CountryPointer | null;
}

const baseStyle: L.PathOptions = {
  fillColor: "#3388ff",
  weight: 1,
  opacity: 1,
  color: "white",
  fillOpacity: 0.2,
};

const metricFillOpacity = 0.8;

const hoverStyle: L.PathOptions = {
  weight: 2,
  color: "#7c3aed",
  fillColor: "#3388ff",
  fillOpacity: 0.5,
};

const selectedStyle: L.PathOptions = {
  weight: 2,
  color: "#1d4e89",
  fillColor: "#1d4e89",
  fillOpacity: 0.45,
};

export function createCountryMap(
  element: HTMLElement,
  handlers: CountryMapHandlers,
): CountryMap {
  const map = L.map(element, {
    worldCopyJump: true,
    minZoom: 2,
  }).setView([20, 0], 2);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  let selected: L.Polygon | null = null;
  let highlighted: L.Polygon | null = null;
  let metricColors: ReadonlyMap<string, string> | null = null;
  let layer: L.GeoJSON;
  const pathsByCode = new Map<string, L.Polygon>();

  const colorFor = (properties: CountryProperties | undefined): string | null => {
    if (!metricColors || !properties?.iso_a3) {
      return null;
    }
    return metricColors.get(properties.iso_a3) ?? null;
  };

  const featureStyle = (feature?: Feature): L.PathOptions => {
    const color = colorFor(feature?.properties as CountryProperties | undefined);
    if (!color) {
      return baseStyle;
    }
    return {
      ...baseStyle,
      fillColor: color,
      fillOpacity: metricFillOpacity,
    };
  };

  const hoverStyleFor = (properties: CountryProperties): L.PathOptions => {
    const color = colorFor(properties);
    if (!color) {
      return hoverStyle;
    }
    return {
      ...hoverStyle,
      fillColor: color,
      fillOpacity: 0.95,
    };
  };

  const selectedStyleFor = (properties: CountryProperties): L.PathOptions => {
    const color = colorFor(properties);
    if (!color) {
      return selectedStyle;
    }
    return {
      weight: 3,
      color: "#1d4e89",
      fillColor: color,
      fillOpacity: 0.95,
    };
  };

  const clearHighlight = (country: L.Polygon) => {
    layer.resetStyle(country);
    const properties = countryProperties(selected);
    if (country === selected && properties) {
      country.setStyle(selectedStyleFor(properties));
    }
  };

  const pointerFromPath = (path: L.Polygon, country: CountryProperties): CountryPointer => {
    const center = path.getBounds().getCenter();
    return {
      country,
      lat: center.lat,
      lng: center.lng,
      clientX: Number.NaN,
      clientY: Number.NaN,
    };
  };

  layer = L.geoJSON(countries, {
    style: featureStyle,
    onEachFeature: (feature, countryLayer) => {
      const path = countryLayer as L.Polygon;
      if (!feature.properties) {
        return;
      }
      const properties = feature.properties as CountryProperties;
      if (properties.iso_a3) {
        pathsByCode.set(properties.iso_a3, path);
      }

      path.on({
        mouseover: (event) => {
          if (highlighted && highlighted !== path) {
            clearHighlight(highlighted);
          }
          highlighted = path;
          path.setStyle(hoverStyleFor(properties));
          path.bringToFront();
          handlers.onHover(pointerFrom(event, properties));
        },
        mousemove: (event) => {
          handlers.onHover(pointerFrom(event, properties));
        },
        mouseout: () => {
          if (highlighted !== path) {
            return;
          }
          clearHighlight(path);
          highlighted = null;
          handlers.onHover(null);
        },
        click: (event) => {
          L.DomEvent.stopPropagation(event);
          if (highlighted && highlighted !== path) {
            clearHighlight(highlighted);
            highlighted = null;
          }
          if (selected && selected !== path) {
            layer.resetStyle(selected);
          }
          selected = path;
          path.setStyle(selectedStyleFor(properties));
          path.bringToFront();
          handlers.onClick(pointerFrom(event, properties));
        },
      });
    },
  }).addTo(map);

  map.on("click", () => {
    if (!selected) {
      return;
    }
    const country = selected;
    selected = null;
    layer.resetStyle(country);
    if (highlighted === country) {
      const properties = countryProperties(country);
      if (properties) {
        country.setStyle(hoverStyleFor(properties));
        country.bringToFront();
      }
    }
    handlers.onClick(null);
  });

  const repaintInteraction = () => {
    const selectedProperties = countryProperties(selected);
    if (selected && selectedProperties) {
      selected.setStyle(selectedStyleFor(selectedProperties));
      selected.bringToFront();
    }
    const highlightedProperties = countryProperties(highlighted);
    if (highlighted && highlightedProperties) {
      highlighted.setStyle(hoverStyleFor(highlightedProperties));
      highlighted.bringToFront();
    }
  };

  window.addEventListener("resize", () => {
    map.invalidateSize();
  });

  return {
    map,
    setMetricColors(colors) {
      metricColors = colors;
      layer.setStyle(featureStyle);
      repaintInteraction();
    },
    highlightCountry(code) {
      const path = code ? (pathsByCode.get(code) ?? null) : null;
      if (highlighted && highlighted !== path) {
        clearHighlight(highlighted);
      }
      highlighted = path;
      const properties = countryProperties(path);
      if (!path || !properties) {
        return null;
      }
      path.setStyle(hoverStyleFor(properties));
      path.bringToFront();
      return pointerFromPath(path, properties);
    },
    selectCountry(code) {
      const path = code ? (pathsByCode.get(code) ?? null) : null;
      if (highlighted && highlighted !== path) {
        clearHighlight(highlighted);
      }
      highlighted = null;
      if (selected && selected !== path) {
        layer.resetStyle(selected);
      }
      selected = path;
      const properties = countryProperties(path);
      if (!path || !properties) {
        return null;
      }
      path.setStyle(selectedStyleFor(properties));
      path.bringToFront();
      return pointerFromPath(path, properties);
    },
  };
}

function countryProperties(path: L.Polygon | null): CountryProperties | null {
  const properties = path?.feature?.properties;
  if (!properties) {
    return null;
  }
  return properties as CountryProperties;
}

function pointerFrom(
  event: L.LeafletMouseEvent,
  country: CountryProperties,
): CountryPointer {
  return {
    country,
    lat: event.latlng.lat,
    lng: event.latlng.lng,
    clientX: event.originalEvent.clientX,
    clientY: event.originalEvent.clientY,
  };
}
