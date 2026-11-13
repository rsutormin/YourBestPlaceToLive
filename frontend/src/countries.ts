// Copyright (c) 2026 Roman Sutormin. MIT License.

import type { Feature, FeatureCollection, Geometry, Polygon } from "geojson";

import countryPoints from "./country-points.json";
import worldGeoJson from "./world-countries.json";

export interface CountryProperties {
  name: string;
  iso_a3: string;
  iso_a2: string;
  continent: string;
}

export type CountryCollection = FeatureCollection<Geometry, CountryProperties>;

export type CountryFeature = Feature<Geometry, CountryProperties>;

interface CountryPointRecord {
  name: string;
  iso_a3: string;
  iso_a2: string;
  continent: string;
  latitude: number;
  longitude: number;
}

const outlinedCountries = worldGeoJson as CountryCollection;

// About one pixel across at the default world zoom.
const tinyCountrySpan = 0.18;

const pointFeatures: CountryFeature[] = (countryPoints as CountryPointRecord[]).map((point) => ({
  type: "Feature",
  properties: {
    name: point.name,
    iso_a3: point.iso_a3,
    iso_a2: point.iso_a2,
    continent: point.continent,
  },
  geometry: tinyCountryPolygon(point.latitude, point.longitude),
}));

export const countries: CountryCollection = {
  type: "FeatureCollection",
  features: [...outlinedCountries.features, ...pointFeatures],
};

function tinyCountryPolygon(latitude: number, longitude: number): Polygon {
  const south = latitude - tinyCountrySpan;
  const north = latitude + tinyCountrySpan;
  const west = longitude - tinyCountrySpan;
  const east = longitude + tinyCountrySpan;
  return {
    type: "Polygon",
    coordinates: [
      [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ],
    ],
  };
}
