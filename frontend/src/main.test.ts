import { beforeEach, describe, expect, it, vi } from "vitest";

const page = `
  <div id="map"></div>
  <button id="tab-metrics" type="button" role="tab" aria-selected="true" aria-controls="metrics-panel">Metrics</button>
  <button id="tab-countries" type="button" role="tab" aria-selected="false" aria-controls="countries-panel" tabindex="-1">Countries</button>
  <div id="metrics-panel" class="tab-panel" role="tabpanel">
    <select id="metric-select"><option value="">Choose a metric</option></select>
    <div id="metric-detail"></div>
  </div>
  <div id="countries-panel" class="tab-panel" role="tabpanel" hidden></div>
`;

describe("app wiring", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = page;
    const map = document.querySelector<HTMLElement>("#map");
    if (!map) {
      throw new Error("Map element missing");
    }
    Object.defineProperty(map, "clientWidth", { configurable: true, value: 800 });
    Object.defineProperty(map, "clientHeight", { configurable: true, value: 600 });
  });

  it("switches the visible tab from the tab buttons and arrow keys", async () => {
    await import("./main");
    const metricsTab = button("#tab-metrics");
    const countriesTab = button("#tab-countries");

    countriesTab.click();

    expect(countriesTab.getAttribute("aria-selected")).toBe("true");
    expect(metricsTab.getAttribute("aria-selected")).toBe("false");
    expect(panel("#metrics-panel").hidden).toBe(true);
    expect(panel("#countries-panel").hidden).toBe(false);

    countriesTab.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));

    expect(metricsTab.getAttribute("aria-selected")).toBe("true");
    expect(panel("#countries-panel").hidden).toBe(true);
    expect(document.activeElement).toBe(metricsTab);
  });

  it("selects the combo country in the metrics list", async () => {
    await import("./main");
    const metricSelect = document.querySelector<HTMLSelectElement>("#metric-select");
    const countrySelect = document.querySelector<HTMLSelectElement>(".country-select");
    if (!metricSelect || !countrySelect) {
      throw new Error("Selectors missing");
    }

    metricSelect.value = "life_expectancy";
    metricSelect.dispatchEvent(new Event("change"));
    countrySelect.value = "FRA";
    countrySelect.dispatchEvent(new Event("change"));

    const row = document.querySelector('.country-list-item[data-code="FRA"]');
    expect(row?.classList.contains("is-selected")).toBe(true);
  });
});

function button(selector: string): HTMLButtonElement {
  const element = document.querySelector(selector);
  if (!(element instanceof HTMLButtonElement)) {
    throw new Error(`Missing button ${selector}`);
  }
  return element;
}

function panel(selector: string): HTMLElement {
  const element = document.querySelector(selector);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Missing panel ${selector}`);
  }
  return element;
}
