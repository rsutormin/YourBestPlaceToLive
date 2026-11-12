import { beforeEach, describe, expect, it, vi } from "vitest";

const page = `
  <div id="map"></div>
  <button id="tab-best" type="button" role="tab" aria-selected="true" aria-controls="best-panel">Your Best List</button>
  <button id="tab-metrics" type="button" role="tab" aria-selected="false" aria-controls="metrics-panel" tabindex="-1">Metrics</button>
  <button id="tab-countries" type="button" role="tab" aria-selected="false" aria-controls="countries-panel" tabindex="-1">Countries</button>
  <div id="best-panel" class="tab-panel" role="tabpanel"></div>
  <div id="metrics-panel" class="tab-panel" role="tabpanel" hidden>
    <select id="metric-select"><option value="">Choose a metric</option></select>
    <div id="metric-detail"></div>
  </div>
  <div id="countries-panel" class="tab-panel" role="tabpanel" hidden></div>
  <button id="score-details-open" type="button">More details</button>
  <dialog id="score-details"><button class="dialog-close" type="button">Close</button><p>How the map score works</p></dialog>
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
    const bestTab = button("#tab-best");
    const metricsTab = button("#tab-metrics");
    const countriesTab = button("#tab-countries");

    expect(bestTab.getAttribute("aria-selected")).toBe("true");
    expect(panel("#best-panel").hidden).toBe(false);
    expect(panel("#metrics-panel").hidden).toBe(true);

    bestTab.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));

    expect(metricsTab.getAttribute("aria-selected")).toBe("true");
    expect(panel("#best-panel").hidden).toBe(true);
    expect(document.activeElement).toBe(metricsTab);

    countriesTab.click();

    expect(countriesTab.getAttribute("aria-selected")).toBe("true");
    expect(panel("#metrics-panel").hidden).toBe(true);
    expect(panel("#countries-panel").hidden).toBe(false);

    countriesTab.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));

    expect(metricsTab.getAttribute("aria-selected")).toBe("true");
    expect(panel("#countries-panel").hidden).toBe(true);
    expect(document.activeElement).toBe(metricsTab);
  });

  it("opens the score explanation from the header link and closes it", async () => {
    await import("./main");
    const dialog = document.querySelector<HTMLDialogElement>("#score-details");
    if (!dialog) {
      throw new Error("Score dialog missing");
    }

    button("#score-details-open").click();
    expect(dialog.open).toBe(true);

    button("#score-details .dialog-close").click();
    expect(dialog.open).toBe(false);

    button("#score-details-open").click();
    dialog.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(dialog.open).toBe(false);
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

    expect(document.querySelector("#metrics-panel .country-list-item[data-code='FRA']")?.classList.contains("is-selected")).toBe(true);
    expect(document.querySelector("#best-panel .country-list-item[data-code='FRA']")?.classList.contains("is-selected")).toBe(true);
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
