import { describe, expect, it, vi } from "vitest";

import type { CountryProperties } from "./countries";
import type { CountryMap } from "./map";
import { worldMetrics } from "./metrics";
import { createMetricsPanel } from "./metrics-panel";

describe("createMetricsPanel", () => {
  it("lists metrics by title and waits for a choice before drawing the detail", () => {
    const { select, detail } = mount();

    const labels = [...select.options].slice(1).map((option) => option.textContent);
    expect(labels).toEqual([...labels].sort((left, right) => (left ?? "").localeCompare(right ?? "", "en")));
    expect(detail.querySelector(".hint")?.textContent).toContain("Choose a metric");
    expect(select.value).toBe("");
  });

  it("shows the title with units once and colors the map for the chosen metric", () => {
    const { select, detail, map } = mount();

    choose(select, "life_expectancy");

    const metric = metricByKey("life_expectancy");
    expect(detail.querySelector("h2")?.textContent).toBe(`${metric.metadata.description} (${metric.metadata.units})`);
    expect(detail.querySelector(".summary")?.textContent).toBe(metric.metadata.summary);
    expect(detail.querySelector(".scale-bar")?.getAttribute("aria-label")).toBe(
      "Low values are red, middle values are yellow, and high values are green.",
    );
    expect(map.setMetricColors).toHaveBeenCalledTimes(1);
    const colors = vi.mocked(map.setMetricColors).mock.calls[0][0];
    expect(colors?.get("FRA")).toMatch(/^rgb\(/);
    expect(listValues(detail).every((value) => !value.includes(metric.metadata.units))).toBe(true);
  });

  it("puts the worse end of a reversed metric on the red side and sorts low values first", () => {
    const { select, detail } = mount();
    const metric = metricByKey("homicide_rate");

    choose(select, "homicide_rate");

    const labels = [...detail.querySelectorAll(".scale-labels span")].map((label) => label.textContent ?? "");
    expect(labels[0]).toContain(formatNumber(extreme(metric, "max")));
    expect(labels[1]).toContain(formatNumber(extreme(metric, "min")));
    expect(detail.querySelector(".scale-bar")?.getAttribute("aria-label")).toContain("High values are red");
    expect(sortButton(detail, "value").dataset.sort).toBe("asc");
    expect(firstValue(detail)).toBe(formatNumber(extreme(metric, "min")));
  });

  it("sorts one column at a time", () => {
    const { select, detail } = mount();
    choose(select, "life_expectancy");

    expect(sortButton(detail, "value").dataset.sort).toBe("desc");
    expect(firstValue(detail)).toBe(formatNumber(extreme(metricByKey("life_expectancy"), "max")));

    sortButton(detail, "country").querySelector<HTMLElement>(".up")?.click();

    expect(sortButton(detail, "country").dataset.sort).toBe("asc");
    expect(sortButton(detail, "value").dataset.sort).toBe("none");
    const names = itemTexts(detail, ".name");
    expect(names).toEqual([...names].sort((left, right) => left.localeCompare(right, "en")));

    sortButton(detail, "year").querySelector<HTMLElement>(".down")?.click();

    expect(sortButton(detail, "year").dataset.sort).toBe("desc");
    expect(sortButton(detail, "country").dataset.sort).toBe("none");
    const years = itemTexts(detail, ".year").map(Number);
    expect(years).toEqual([...years].sort((left, right) => right - left));
  });

  it("opens the metric details from the button and closes them when the metric changes", () => {
    const { select, detail } = mount();
    choose(select, "life_expectancy");
    const metric = metricByKey("life_expectancy");

    detail.querySelector<HTMLButtonElement>(".details-button")?.click();
    const dialog = detail.querySelector("dialog");
    expect(dialog?.open).toBe(true);
    expect(dialog?.textContent).toContain(metric.metadata.key);
    expect(dialog?.textContent).toContain(formatNumber(extreme(metric, "min")));
    expect(dialog?.querySelector("a")?.target).toBe("_blank");

    dialog?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(dialog?.open).toBe(false);

    choose(select, "homicide_rate");
    expect(detail.querySelector("dialog")?.open).toBe(false);
    expect(detail.querySelector("h2")?.textContent).toContain("Intentional homicides");
  });

  it("highlights a hovered list row on the map and selects it on click", () => {
    const { select, detail, map, info } = mount();
    choose(select, "life_expectancy");
    const item = row(detail, "FRA");
    const pointer = {
      country: { name: "France", iso_a3: "FRA", iso_a2: "FR", continent: "Europe" },
      lat: 46,
      lng: 2,
      clientX: Number.NaN,
      clientY: Number.NaN,
    };
    vi.mocked(map.highlightCountry).mockReturnValue(pointer);
    vi.mocked(map.selectCountry).mockReturnValue(pointer);

    item.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true, clientX: 5, clientY: 6 }));

    expect(item.classList.contains("is-hover")).toBe(true);
    expect(map.highlightCountry).toHaveBeenCalledWith("FRA");
    expect(info.onHover).toHaveBeenCalledWith(pointer.country);

    item.click();

    expect(item.classList.contains("is-hover")).toBe(false);
    expect(item.classList.contains("is-selected")).toBe(true);
    expect(map.selectCountry).toHaveBeenCalledWith("FRA");
    expect(info.onSelect).toHaveBeenCalledWith(pointer.country);
  });

  it("uses the list row when the country is missing from the map", () => {
    const { select, detail, map, info } = mount();
    choose(select, "life_expectancy");
    vi.mocked(map.highlightCountry).mockReturnValue(null);
    vi.mocked(map.selectCountry).mockReturnValue(null);
    const item = row(detail, "FRA");

    item.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    item.click();

    expect(info.onHover).toHaveBeenCalledWith(expect.objectContaining({ iso_a3: "FRA", continent: "" }));
    expect(info.onSelect).toHaveBeenCalledWith(expect.objectContaining({ iso_a3: "FRA", continent: "" }));
  });

  it("shows the selected and hovered rows together, with hover winning on the same row", () => {
    const { select, detail, panel } = mount();
    choose(select, "life_expectancy");

    panel.setSelectedCountry("FRA");
    panel.setHoveredCountry("DEU");

    expect(row(detail, "FRA").classList.contains("is-selected")).toBe(true);
    expect(row(detail, "DEU").classList.contains("is-hover")).toBe(true);

    panel.setHoveredCountry("FRA");

    expect(row(detail, "FRA").classList.contains("is-hover")).toBe(true);
    expect(row(detail, "FRA").classList.contains("is-selected")).toBe(false);
    expect(row(detail, "DEU").classList.contains("is-hover")).toBe(false);
  });

  it("clears a list hover when the pointer leaves and scrolls the selection back", () => {
    const { select, detail, map, info, panel } = mount();
    choose(select, "life_expectancy");
    panel.setSelectedCountry("FRA");
    const items = detail.querySelector(".country-list-items");
    if (!(items instanceof HTMLUListElement)) {
      throw new Error("Country list missing");
    }
    const france = row(detail, "FRA");
    const germany = row(detail, "DEU");
    let scrollTop = 400;
    Object.defineProperty(items, "clientHeight", { configurable: true, value: 40 });
    Object.defineProperty(items, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = value;
      },
    });
    Object.defineProperty(france, "offsetTop", { configurable: true, value: 200 });
    Object.defineProperty(france, "offsetHeight", { configurable: true, value: 20 });

    germany.dispatchEvent(new MouseEvent("mouseenter"));
    items.dispatchEvent(new MouseEvent("mouseleave"));

    expect(germany.classList.contains("is-hover")).toBe(false);
    expect(france.classList.contains("is-selected")).toBe(true);
    expect(map.highlightCountry).toHaveBeenCalledWith(null);
    expect(info.onHover).toHaveBeenCalledWith(null);
    expect(scrollTop).toBe(200);
  });

  it("moves the hover to the row under the pointer while the list scrolls", () => {
    const { select, detail, map } = mount();
    choose(select, "life_expectancy");
    const items = detail.querySelector(".country-list-items");
    if (!(items instanceof HTMLUListElement)) {
      throw new Error("Country list missing");
    }
    const france = row(detail, "FRA");
    const germany = row(detail, "DEU");
    vi.spyOn(document, "elementFromPoint").mockReturnValue(germany.querySelector(".name"));

    france.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true, clientX: 4, clientY: 8 }));
    items.dispatchEvent(new Event("scroll"));

    expect(germany.classList.contains("is-hover")).toBe(true);
    expect(france.classList.contains("is-hover")).toBe(false);
    expect(map.highlightCountry).toHaveBeenLastCalledWith("DEU");
  });

  it("retargets a hover when the pointer leaves onto another row", () => {
    const { select, detail, map } = mount();
    choose(select, "life_expectancy");
    const items = detail.querySelector(".country-list-items");
    const france = row(detail, "FRA");
    const germany = row(detail, "DEU");
    if (!(items instanceof HTMLUListElement)) {
      throw new Error("Country list missing");
    }
    vi.spyOn(document, "elementFromPoint").mockReturnValue(germany);

    france.dispatchEvent(new MouseEvent("mouseenter"));
    france.dispatchEvent(new MouseEvent("mouseleave", { relatedTarget: document.body }));

    expect(map.highlightCountry).toHaveBeenLastCalledWith("DEU");

    germany.dispatchEvent(new MouseEvent("mouseenter"));
    const calls = vi.mocked(map.highlightCountry).mock.calls.length;
    germany.dispatchEvent(new MouseEvent("mouseleave", { relatedTarget: france }));

    expect(vi.mocked(map.highlightCountry).mock.calls.length).toBe(calls);
    expect(items.contains(france)).toBe(true);
  });
});

function mount() {
  const select = document.createElement("select");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a metric";
  select.append(placeholder);
  const detail = document.createElement("div");
  const map = fakeMap();
  const info = {
    onHover: vi.fn(),
    onSelect: vi.fn(),
  };
  const panel = createMetricsPanel(select, detail, map, info);
  return { select, detail, map, info, panel };
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
    country: { name: code, iso_a3: code, iso_a2: "", continent: "" } satisfies CountryProperties,
    lat: 0,
    lng: 0,
    clientX: Number.NaN,
    clientY: Number.NaN,
  };
}

function choose(select: HTMLSelectElement, key: string): void {
  select.value = key;
  select.dispatchEvent(new Event("change"));
}

function metricByKey(key: string) {
  const metric = worldMetrics.find((item) => item.metadata.key === key);
  if (!metric) {
    throw new Error(`Missing metric ${key}`);
  }
  return metric;
}

function extreme(metric: ReturnType<typeof metricByKey>, which: "min" | "max"): number {
  const values = metric.data.filter((row) => Number.isFinite(row.value)).map((row) => row.value);
  return which === "min" ? Math.min(...values) : Math.max(...values);
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 4 }).format(value);
}

function listValues(detail: HTMLElement): string[] {
  return itemTexts(detail, ".country-list-item .value");
}

function itemTexts(detail: HTMLElement, selector: string): string[] {
  return [...detail.querySelectorAll(selector)].map((item) => item.textContent ?? "");
}

function firstValue(detail: HTMLElement): string {
  return detail.querySelector(".country-list-item .value")?.textContent ?? "";
}

function sortButton(detail: HTMLElement, column: string): HTMLButtonElement {
  const button = detail.querySelector(`.column.${column} .sort-button`);
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Missing sort button ${column}`);
  }
  return button;
}

function row(detail: HTMLElement, code: string): HTMLLIElement {
  const item = detail.querySelector(`.country-list-item[data-code="${code}"]`);
  if (!(item instanceof HTMLLIElement)) {
    throw new Error(`Missing country row ${code}`);
  }
  return item;
}
