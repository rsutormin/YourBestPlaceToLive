import type { Feature, FeatureCollection, Geometry } from "geojson";

import worldGeoJson from "./world-countries.json";

export interface CountryProperties {
  name: string;
  iso_a3: string;
  iso_a2: string;
  continent: string;
}

export type CountryCollection = FeatureCollection<Geometry, CountryProperties>;

export const countries = worldGeoJson as CountryCollection;

export type CountryFeature = Feature<Geometry, CountryProperties>;
