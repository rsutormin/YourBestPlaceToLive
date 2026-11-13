// Copyright (c) 2026 Roman Sutormin. MIT License.

import { describe, expect, it, vi } from "vitest";

import { importanceLabel, scoreCountries } from "./best-list";
import { createBestListPanel } from "./best-list-panel";
import type { CountryMap } from "./map";
import { worldMetrics } from "./metrics";

describe("createBestListPanel", () => {
  it("lists every metric at its saved importance", () => {
    const { host } = mount();
    const names = texts(host, ".weight-row .name");
    const sliders = [...host.querySelectorAll<HTMLInputElement>("input[type=range]")];

    expect(names).toEqual([...worldMetrics].map((metric) => metric.metadata.description).sort((left, right) => left.localeCompare(right, "en")));
    expect(sliders).toHaveLength(worldMetrics.length);
    expect(sliders.every((slider) => slider.step === "0.25")).toBe(true);
    for (const slider of sliders) {
      const metric = worldMetrics.find((item) => item.metadata.key === slider.dataset.key);
      expect(slider.value).toBe(String(metric?.metadata.importance));
      expect(slider.nextElementSibling?.textContent).toBe(importanceLabel(metric?.metadata.importance ?? 0.5));
    }
    expect(host.querySelector(".column.score .sort-button")?.getAttribute("data-sort")).toBe("desc");
    expect([...host.children].map((child) => child.className)).toEqual(["weight-list", "scale", "country-list"]);
    expect(host.querySelector(".scale-bar")?.getAttribute("aria-label")).toBe(
      "Low scores are red, middle scores are yellow, and high scores are green.",
    );
    expect(codes(host)).toEqual(ranked(defaultWeights(), "desc").map((row) => row.code));
  });

  it("recalculates scores and resorts when the score column is sorted", () => {
    const { host } = mount();
    const weights = new Map(worldMetrics.map((metric) => [metric.metadata.key, metric.metadata.key === "homicide_rate" ? 1 : 0]));

    setImportance(host, (key) => weights.get(key) ?? 0);

    expect(host.querySelector('input[data-key="homicide_rate"]')?.nextElementSibling?.textContent).toBe("Extremely important");
    expect(host.querySelector('input[data-key="life_expectancy"]')?.nextElementSibling?.textContent).toBe("Not important");
    expect(codes(host)).toEqual(ranked(weights, "desc").map((row) => row.code));

    host.querySelector<HTMLElement>(".column.score .up")?.click();

    expect(host.querySelector(".column.score .sort-button")?.getAttribute("data-sort")).toBe("asc");
    expect(codes(host)).toEqual(ranked(weights, "asc").map((row) => row.code));
  });

  it("keeps the country order when another column is sorted", () => {
    const { host } = mount();
    host.querySelector<HTMLElement>(".column.country .up")?.click();
    const names = texts(host, ".country-list-item .name");
    const before = host.querySelector('.country-list-item[data-code="FRA"] .value')?.textContent;

    setImportance(host, (key) => (key === "life_expectancy" ? 1 : 0.25));

    expect(texts(host, ".country-list-item .name")).toEqual(names);
    expect(host.querySelector('.country-list-item[data-code="FRA"] .value')?.textContent).not.toBe(before);
    expect(host.querySelector(".column.score .sort-button")?.getAttribute("data-sort")).toBe("none");
  });

  it("clears the country scores when every metric is not important", () => {
    const { host } = mount();

    setImportance(host, () => 0);

    expect(host.querySelector(".country-list-item")).toBeNull();
    expect(host.querySelector(".country-metrics-empty")?.textContent).toBe(
      "Set a metric above Not important to score countries.",
    );
    expect([...host.querySelectorAll(".scale-labels span")].map((label) => label.textContent)).toEqual(["—", "—"]);
  });

  it("highlights a hovered country on the map and selects it on click", () => {
    const { host, map, handlers } = mount();
    const france = host.querySelector<HTMLLIElement>('.country-list-item[data-code="FRA"]');
    if (!france) {
      throw new Error("France missing from the best list");
    }

    france.dispatchEvent(new MouseEvent("mouseenter"));
    expect(france.classList.contains("is-hover")).toBe(true);
    expect(map.highlightCountry).toHaveBeenCalledWith("FRA");
    expect(handlers.onHover).toHaveBeenCalledWith(expect.objectContaining({ iso_a3: "FRA" }));

    france.click();
    expect(france.classList.contains("is-selected")).toBe(true);
    expect(france.classList.contains("is-hover")).toBe(false);
    expect(map.selectCountry).toHaveBeenCalledWith("FRA");
    expect(handlers.onSelect).toHaveBeenCalledWith(expect.objectContaining({ iso_a3: "FRA" }));
  });
});

function mount() {
  const host = document.createElement("div");
  const map = fakeMap();
  const handlers = { onHover: vi.fn(), onSelect: vi.fn(), onScores: vi.fn() };
  createBestListPanel(host, map, handlers);
  return { host, map, handlers };
}

function fakeMap(): CountryMap {
  return {
    map: {} as CountryMap["map"],
    setMetricColors: vi.fn(),
    highlightCountry: vi.fn((code: string | null) => (code ? pointer(code) : null)),
    selectCountry: vi.fn((code: string | null) => (code ? pointer(code) : null)),
  };
}

function pointer(code: string) {
  return {
    country: { name: code, iso_a3: code, iso_a2: "", continent: "" },
    lat: 0,
    lng: 0,
    clientX: Number.NaN,
    clientY: Number.NaN,
  };
}

function setImportance(host: HTMLElement, valueFor: (key: string) => number): void {
  for (const slider of host.querySelectorAll<HTMLInputElement>("input[type=range]")) {
    slider.value = String(valueFor(slider.dataset.key ?? ""));
    slider.dispatchEvent(new Event("input"));
  }
}

function defaultWeights(): Map<string, number> {
  return new Map(worldMetrics.map((metric) => [metric.metadata.key, metric.metadata.importance]));
}

function ranked(weights: ReadonlyMap<string, number>, direction: "asc" | "desc") {
  const factor = direction === "asc" ? 1 : -1;
  return scoreCountries(worldMetrics, weights).sort((left, right) => {
    const primary = left.score - right.score;
    if (primary !== 0) {
      return primary * factor;
    }
    return left.country.localeCompare(right.country, "en");
  });
}

function codes(host: HTMLElement): string[] {
  return [...host.querySelectorAll<HTMLElement>(".country-list-item")].map((item) => item.dataset.code ?? "");
}

function texts(host: HTMLElement, selector: string): string[] {
  return [...host.querySelectorAll(selector)].map((item) => item.textContent ?? "");
}
