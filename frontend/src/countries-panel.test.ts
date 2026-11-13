// Copyright (c) 2026 Roman Sutormin. MIT License.

import { describe, expect, it, vi } from "vitest";

import { countries, type CountryProperties } from "./countries";
import { createCountriesPanel } from "./countries-panel";
import { worldMetrics } from "./metrics";

const france = country("FRA");
const germany = country("DEU");

describe("createCountriesPanel", () => {
  it("keeps the country selector in place and fills it with every country", () => {
    const { host, panel } = createPanel();
    const select = selector(host);
    const label = term(host, "Country");

    panel.setSelectedCountry(france);
    panel.setHoveredCountry(germany);
    panel.setHoveredCountry(null);

    expect(host.querySelector("select")).toBe(select);
    expect(host.contains(label)).toBe(true);
    expect(select.options.length).toBeGreaterThan(countries.features.length);
    expect(optionNames(select)).toEqual([...optionNames(select)].sort((left, right) => left.localeCompare(right, "en")));
    expect(select.value).toBe("FRA");
  });

  it("shows the hovered country until the pointer leaves, then the selected one", () => {
    const { host, panel } = createPanel();

    panel.setSelectedCountry(france);
    const selectedRows = [...host.querySelectorAll(".country-metric")];

    panel.setHoveredCountry(germany);

    expect(selector(host).value).toBe("DEU");
    expect(definition(host, "Continent").textContent).toBe(germany.continent);
    expect(host.querySelector(".country-metric")).not.toBe(selectedRows[0]);

    panel.setHoveredCountry(france);

    expect(selector(host).value).toBe("FRA");
    expect(host.querySelector(".country-metric")).not.toBe(selectedRows[0]);
    expect(metricRows(host)).toEqual(expectedMetrics("FRA"));
  });

  it("does not rebuild the metric rows when the shown country stays the same", () => {
    const { host, panel } = createPanel();

    panel.setSelectedCountry(france);
    const row = host.querySelector(".country-metric");

    panel.setHoveredCountry(france);

    expect(host.querySelector(".country-metric")).toBe(row);
  });

  it("selects a country from the combo and reports that choice", () => {
    const onSelect = vi.fn();
    const { host, panel } = createPanel(onSelect);

    panel.setSelectedCountry(france);
    expect(onSelect).not.toHaveBeenCalled();

    const select = selector(host);
    select.value = "DEU";
    select.dispatchEvent(new Event("change"));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ iso_a3: "DEU", name: germany.name }));
    expect(definition(host, "Continent").textContent).toBe(germany.continent);
    expect(metricRows(host)).toEqual(expectedMetrics("DEU"));
  });

  it("clears the selection when the empty combo entry is chosen", () => {
    const onSelect = vi.fn();
    const { host, panel } = createPanel(onSelect);
    panel.setSelectedCountry(france);

    const select = selector(host);
    select.value = "";
    select.dispatchEvent(new Event("change"));

    expect(onSelect).toHaveBeenCalledWith(null);
    expect(select.value).toBe("");
    expect(definition(host, "Continent").textContent).toBe("—");
    expect(host.querySelector(".country-metrics-empty")?.textContent).toBe("Choose a country to see its metrics.");
  });

  it("says when a country has no loaded metrics", () => {
    const uncovered = countries.features.find((feature) => {
      const code = feature.properties?.iso_a3;
      return code !== "" && code !== "-99" && !worldMetrics.some((metric) => metric.data.some((row) => row.code === code));
    })?.properties;
    const missing: CountryProperties = uncovered ?? {
      name: "Nowhere",
      iso_a3: "ZZZ",
      iso_a2: "",
      continent: "",
    };

    const { host, panel } = createPanel();
    panel.setSelectedCountry(missing);

    expect(selector(host).value).toBe(uncovered ? missing.iso_a3 : "");
    expect(host.querySelector(".country-metrics-empty")?.textContent).toBe("No metrics for this country.");
  });
});

function createPanel(onSelect: (country: CountryProperties | null) => void = () => {}) {
  const host = document.createElement("div");
  const panel = createCountriesPanel(host, { onSelect });
  return { host, panel };
}

function country(code: string): CountryProperties {
  const properties = countries.features.find((feature) => feature.properties?.iso_a3 === code)?.properties;
  if (!properties) {
    throw new Error(`Missing country ${code}`);
  }
  return properties;
}

function selector(host: HTMLElement): HTMLSelectElement {
  const select = host.querySelector("select");
  if (!(select instanceof HTMLSelectElement)) {
    throw new Error("Country selector missing");
  }
  return select;
}

function term(host: HTMLElement, label: string): HTMLElement {
  const found = [...host.querySelectorAll("dt")].find((item) => item.textContent === label);
  if (!found) {
    throw new Error(`Missing term ${label}`);
  }
  return found;
}

function definition(host: HTMLElement, label: string): HTMLElement {
  const terms = [...host.querySelectorAll("dt")];
  const index = terms.findIndex((item) => item.textContent === label);
  const value = host.querySelectorAll("dd")[index];
  if (!value) {
    throw new Error(`Missing value ${label}`);
  }
  return value;
}

function optionNames(select: HTMLSelectElement): string[] {
  return [...select.options].slice(1).map((option) => option.textContent ?? "");
}

function metricRows(host: HTMLElement): Array<{ name: string; value: string; year: string }> {
  return [...host.querySelectorAll(".country-metric")].map((item) => ({
    name: item.querySelector(".name")?.textContent ?? "",
    value: item.querySelector(".value")?.textContent ?? "",
    year: item.querySelector(".year")?.textContent ?? "",
  }));
}

function expectedMetrics(code: string): Array<{ name: string; value: string; year: string }> {
  const formatter = new Intl.NumberFormat("en", { maximumFractionDigits: 4 });
  return worldMetrics
    .flatMap((metric) =>
      metric.data
        .filter((row) => row.code === code && Number.isFinite(row.value))
        .map((row) => ({
          name: metric.metadata.description,
          value: `${formatter.format(row.value)} (${metric.metadata.units})`,
          year: String(row.year),
        })),
    )
    .sort((left, right) => left.name.localeCompare(right.name, "en"));
}
