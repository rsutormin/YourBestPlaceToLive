import "./style.css";

import { createBestListPanel, type BestListPanel } from "./best-list-panel";
import { createCountriesPanel, type CountriesPanel } from "./countries-panel";
import { createCountryMap, type CountryPointer } from "./map";
import { createMetricsPanel, type MetricsPanel } from "./metrics-panel";

const mapElement = document.querySelector<HTMLElement>("#map");
const metricSelect = document.querySelector<HTMLSelectElement>("#metric-select");
const metricDetail = document.querySelector<HTMLElement>("#metric-detail");
const bestTab = document.querySelector<HTMLButtonElement>("#tab-best");
const metricsTab = document.querySelector<HTMLButtonElement>("#tab-metrics");
const countriesTab = document.querySelector<HTMLButtonElement>("#tab-countries");
const bestPanelElement = document.querySelector<HTMLElement>("#best-panel");
const metricsPanelElement = document.querySelector<HTMLElement>("#metrics-panel");
const countriesPanelElement = document.querySelector<HTMLElement>("#countries-panel");

if (
  !mapElement ||
  !metricSelect ||
  !metricDetail ||
  !bestTab ||
  !metricsTab ||
  !countriesTab ||
  !bestPanelElement ||
  !metricsPanelElement ||
  !countriesPanelElement
) {
  throw new Error("Map page is missing the map, tabs, or metric controls.");
}

type PanelTab = "best" | "metrics" | "countries";

let metricsPanel: MetricsPanel;
let countriesPanel: CountriesPanel;
let bestList: BestListPanel;
let activeTab: PanelTab = "best";
let metricColors: ReadonlyMap<string, string> | null = null;
let scoreColors: ReadonlyMap<string, string> | null = null;
const countryMap = createCountryMap(mapElement, {
  onHover: (pointer) => {
    const code = countryCode(pointer);
    bestList.setHoveredCountry(code);
    metricsPanel.setHoveredCountry(code);
    countriesPanel.setHoveredCountry(pointer?.country ?? null);
  },
  onClick: (pointer) => {
    const code = countryCode(pointer);
    bestList.setSelectedCountry(code);
    metricsPanel.setSelectedCountry(code);
    countriesPanel.setSelectedCountry(pointer?.country ?? null);
  },
});

countriesPanel = createCountriesPanel(countriesPanelElement, {
  onSelect(country) {
    const code = country?.iso_a3 || null;
    bestList.setSelectedCountry(code);
    metricsPanel.setSelectedCountry(code);
    countryMap.selectCountry(code);
  },
});

bestList = createBestListPanel(bestPanelElement, countryMap, {
  onHover(country) {
    metricsPanel.setHoveredCountry(country?.iso_a3 ?? null);
    countriesPanel.setHoveredCountry(country);
  },
  onSelect(country) {
    metricsPanel.setSelectedCountry(country?.iso_a3 ?? null);
    countriesPanel.setSelectedCountry(country);
  },
  onScores(colors) {
    scoreColors = colors;
    applyMapColors();
  },
});

metricsPanel = createMetricsPanel(metricSelect, metricDetail, countryMap, {
  onHover(country) {
    bestList.setHoveredCountry(country?.iso_a3 ?? null);
    countriesPanel.setHoveredCountry(country);
  },
  onSelect(country) {
    bestList.setSelectedCountry(country?.iso_a3 ?? null);
    countriesPanel.setSelectedCountry(country);
  },
  onColors(colors) {
    metricColors = colors;
    applyMapColors();
  },
});

wireTabs([
  { button: bestTab, panel: bestPanelElement },
  { button: metricsTab, panel: metricsPanelElement },
  { button: countriesTab, panel: countriesPanelElement },
]);

function countryCode(pointer: CountryPointer | null): string | null {
  const code = pointer?.country.iso_a3;
  return code ? code : null;
}

function applyMapColors(): void {
  countryMap.setMetricColors(activeTab === "metrics" ? metricColors : scoreColors);
}

function wireTabs(tabs: Array<{ button: HTMLButtonElement; panel: HTMLElement }>): void {
  const names: PanelTab[] = ["best", "metrics", "countries"];
  const show = (active: number) => {
    activeTab = names[active] ?? "best";
    tabs.forEach((tab, index) => {
      const selected = index === active;
      tab.button.setAttribute("aria-selected", String(selected));
      tab.button.tabIndex = selected ? 0 : -1;
      tab.panel.hidden = !selected;
    });
    applyMapColors();
  };

  tabs.forEach((tab, index) => {
    tab.button.addEventListener("click", () => show(index));
    tab.button.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
        return;
      }
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const next = tabs[(index + direction + tabs.length) % tabs.length];
      next.button.focus();
      next.button.click();
    });
  });
}
