import "./style.css";

import { createCountriesPanel, type CountriesPanel } from "./countries-panel";
import { createCountryMap, type CountryPointer } from "./map";
import { createMetricsPanel, type MetricsPanel } from "./metrics-panel";

const mapElement = document.querySelector<HTMLElement>("#map");
const metricSelect = document.querySelector<HTMLSelectElement>("#metric-select");
const metricDetail = document.querySelector<HTMLElement>("#metric-detail");
const metricsTab = document.querySelector<HTMLButtonElement>("#tab-metrics");
const countriesTab = document.querySelector<HTMLButtonElement>("#tab-countries");
const metricsPanelElement = document.querySelector<HTMLElement>("#metrics-panel");
const countriesPanelElement = document.querySelector<HTMLElement>("#countries-panel");

if (
  !mapElement ||
  !metricSelect ||
  !metricDetail ||
  !metricsTab ||
  !countriesTab ||
  !metricsPanelElement ||
  !countriesPanelElement
) {
  throw new Error("Map page is missing the map, tabs, or metric controls.");
}

let metricsPanel: MetricsPanel;
let countriesPanel: CountriesPanel;
const countryMap = createCountryMap(mapElement, {
  onHover: (pointer) => {
    metricsPanel.setHoveredCountry(countryCode(pointer));
    countriesPanel.setHoveredCountry(pointer?.country ?? null);
  },
  onClick: (pointer) => {
    metricsPanel.setSelectedCountry(countryCode(pointer));
    countriesPanel.setSelectedCountry(pointer?.country ?? null);
  },
});

countriesPanel = createCountriesPanel(countriesPanelElement, {
  onSelect(country) {
    metricsPanel.setSelectedCountry(country?.iso_a3 || null);
    countryMap.selectCountry(country?.iso_a3 || null);
  },
});

metricsPanel = createMetricsPanel(metricSelect, metricDetail, countryMap, {
  onHover(country) {
    countriesPanel.setHoveredCountry(country);
  },
  onSelect(country) {
    countriesPanel.setSelectedCountry(country);
  },
});

wireTabs(metricsTab, countriesTab, metricsPanelElement, countriesPanelElement);

function countryCode(pointer: CountryPointer | null): string | null {
  const code = pointer?.country.iso_a3;
  return code ? code : null;
}

function wireTabs(
  metricsButton: HTMLButtonElement,
  countriesButton: HTMLButtonElement,
  metricsPane: HTMLElement,
  countriesPane: HTMLElement,
): void {
  const tabs = [metricsButton, countriesButton];
  const show = (name: "metrics" | "countries") => {
    const metricsActive = name === "metrics";
    metricsButton.setAttribute("aria-selected", String(metricsActive));
    countriesButton.setAttribute("aria-selected", String(!metricsActive));
    metricsButton.tabIndex = metricsActive ? 0 : -1;
    countriesButton.tabIndex = metricsActive ? -1 : 0;
    metricsPane.hidden = !metricsActive;
    countriesPane.hidden = metricsActive;
  };

  metricsButton.addEventListener("click", () => show("metrics"));
  countriesButton.addEventListener("click", () => show("countries"));
  for (const tab of tabs) {
    tab.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
        return;
      }
      event.preventDefault();
      const next = tab === metricsButton ? countriesButton : metricsButton;
      next.focus();
      next.click();
    });
  }
}
