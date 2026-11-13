// Copyright (c) 2026 Roman Sutormin. MIT License.

import { countries, type CountryProperties } from "./countries";
import { worldMetrics } from "./metrics";

export interface CountriesPanel {
  setHoveredCountry(country: CountryProperties | null): void;
  setSelectedCountry(country: CountryProperties | null): void;
}

export interface CountriesPanelHandlers {
  onSelect(country: CountryProperties | null): void;
}

interface CountryMetric {
  name: string;
  value: string;
  year: number;
}

const catalog = new Map<string, CountryProperties>();
for (const feature of countries.features) {
  const properties = feature.properties;
  if (properties?.iso_a3) {
    catalog.set(properties.iso_a3, properties);
  }
}

const metricsByCountry = new Map<string, CountryMetric[]>();
for (const metric of worldMetrics) {
  for (const row of metric.data) {
    if (!row.code || !Number.isFinite(row.value)) {
      continue;
    }
    if (!catalog.has(row.code)) {
      catalog.set(row.code, {
        name: row.country,
        iso_a3: row.code,
        iso_a2: "",
        continent: "",
      });
    }
    const values = metricsByCountry.get(row.code) ?? [];
    values.push({
      name: metric.metadata.description,
      value: `${formatNumber(row.value)} (${metric.metadata.units})`,
      year: row.year,
    });
    metricsByCountry.set(row.code, values);
  }
}
for (const values of metricsByCountry.values()) {
  values.sort((left, right) => left.name.localeCompare(right.name, "en"));
}

const countryOptions = [...catalog.values()].sort((left, right) => left.name.localeCompare(right.name, "en"));

export function createCountriesPanel(host: HTMLElement, handlers: CountriesPanelHandlers): CountriesPanel {
  let hovered: CountryProperties | null = null;
  let selected: CountryProperties | null = null;
  let shownCode: string | null | undefined;
  let applying = false;

  const view = document.createElement("div");
  view.className = "country-view";

  const facts = document.createElement("dl");
  facts.className = "country-facts";
  const countrySelect = document.createElement("select");
  countrySelect.className = "country-select";
  countrySelect.setAttribute("aria-label", "Country");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a country";
  countrySelect.append(placeholder);
  for (const country of countryOptions) {
    const option = document.createElement("option");
    option.value = country.iso_a3;
    option.textContent = country.name;
    countrySelect.append(option);
  }
  fact(facts, "Country", countrySelect);
  const continentValue = fact(facts, "Continent");

  const table = document.createElement("div");
  table.className = "country-metrics";
  const header = document.createElement("div");
  header.className = "country-metrics-header";
  for (const label of ["Metric", "Value", "Year"]) {
    const cell = document.createElement("span");
    cell.textContent = label;
    header.append(cell);
  }
  const items = document.createElement("ul");
  items.className = "country-metrics-items";
  table.append(header, items);
  view.append(facts, table);
  host.replaceChildren(view);
  render();

  countrySelect.addEventListener("change", () => {
    if (applying) {
      return;
    }
    const country = catalog.get(countrySelect.value) ?? null;
    hovered = null;
    selected = country;
    render();
    handlers.onSelect(country);
  });

  return {
    setHoveredCountry(country) {
      if ((hovered?.iso_a3 || null) === (country?.iso_a3 || null)) {
        return;
      }
      hovered = country;
      render();
    },
    setSelectedCountry(country) {
      if ((selected?.iso_a3 || null) === (country?.iso_a3 || null)) {
        return;
      }
      selected = country;
      render();
    },
  };

  function render(): void {
    const country = hovered ?? selected;
    const code = country?.iso_a3 || null;
    if (code === shownCode) {
      return;
    }
    shownCode = code;
    applying = true;
    countrySelect.value = code && catalog.has(code) ? code : "";
    applying = false;
    const known = code ? catalog.get(code) : undefined;
    continentValue.textContent = country?.continent || known?.continent || "—";
    items.replaceChildren();
    if (!code) {
      const empty = document.createElement("li");
      empty.className = "country-metrics-empty";
      empty.textContent = "Choose a country to see its metrics.";
      items.append(empty);
      return;
    }
    const metrics = metricsByCountry.get(code) ?? [];
    if (metrics.length === 0) {
      const empty = document.createElement("li");
      empty.className = "country-metrics-empty";
      empty.textContent = "No metrics for this country.";
      items.append(empty);
      return;
    }
    for (const metric of metrics) {
      const item = document.createElement("li");
      item.className = "country-metric";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = metric.name;
      name.title = metric.name;
      const value = document.createElement("span");
      value.className = "value";
      value.textContent = metric.value;
      const year = document.createElement("span");
      year.className = "year";
      year.textContent = String(metric.year);
      item.append(name, value, year);
      items.append(item);
    }
  }
}

function fact(list: HTMLDListElement, label: string, value?: HTMLElement): HTMLElement {
  const term = document.createElement("dt");
  term.textContent = label;
  const definition = document.createElement("dd");
  list.append(term, definition);
  if (value) {
    definition.append(value);
    return value;
  }
  return definition;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 4 }).format(value);
}
