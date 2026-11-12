import type { CountryProperties } from "./countries";
import type { CountryMap } from "./map";
import { colorsForMetric, worldMetrics, type MetricRow, type WorldMetric } from "./metrics";

export interface MetricsPanel {
  setHoveredCountry(code: string | null): void;
  setSelectedCountry(code: string | null): void;
}

export interface MetricsPanelInfo {
  onHover(country: CountryProperties | null): void;
  onSelect(country: CountryProperties | null): void;
  onColors(colors: ReadonlyMap<string, string> | null): void;
}

export function createMetricsPanel(
  select: HTMLSelectElement,
  detail: HTMLElement,
  map: CountryMap,
  info: MetricsPanelInfo,
): MetricsPanel {
  const metricsByKey = new Map(worldMetrics.map((metric) => [metric.metadata.key, metric]));
  let hoveredCode: string | null = null;
  let selectedCode: string | null = null;
  let hoveredItem: HTMLLIElement | null = null;
  let selectedItem: HTMLLIElement | null = null;
  let countryItems = new Map<string, HTMLLIElement>();
  let countryListItems: HTMLUListElement | null = null;

  fillMetricSelect(select);
  renderMetricDetail(null);
  select.addEventListener("change", () => {
    const metric = metricsByKey.get(select.value) ?? null;
    renderMetricDetail(metric);
    info.onColors(metric ? colorsForMetric(metric) : null);
  });

  return {
    setHoveredCountry(code) {
      hoveredCode = code;
      applyCountryHighlight(true);
    },
    setSelectedCountry(code) {
      selectedCode = code;
      applyCountryHighlight(true);
    },
  };

  function renderMetricDetail(metric: WorldMetric | null): void {
    detail.querySelector("dialog")?.close();
    detail.replaceChildren();
    countryItems = new Map();
    countryListItems = null;
    hoveredItem = null;
    selectedItem = null;
    if (!metric) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent =
        "Choose a metric to color countries from red through yellow to green. Worse values are red.";
      detail.append(hint);
      return;
    }

    const { metadata } = metric;
    const rows = metric.data.filter((row) => Number.isFinite(row.value));
    const lowest = extremeRows(rows, "min");
    const highest = extremeRows(rows, "max");
    const view = document.createElement("div");
    view.className = "metric-detail";
    const fields: Array<[string, string | HTMLElement]> = [
      ["Key", metadata.key],
      ["Units", metadata.units],
      ["Source", metadata.source],
      ["Database", metadata.database],
      ["Code", metadata.code],
      ["Scope", metadata.scope],
      ["Countries", String(rows.length)],
      ["Lowest", lowest ? formatExtreme(lowest, metadata.units) : "—"],
      ["Highest", highest ? formatExtreme(highest, metadata.units) : "—"],
      ["Retrieved", metadata.retrievedAt.replace("T", " ").replace("Z", " UTC")],
      ["URL", link(metadata.url)],
    ];
    view.append(renderMetricHeading(`${metadata.description} (${metadata.units})`, fields));

    const category = document.createElement("p");
    category.className = "hint";
    category.textContent = metadata.category;
    view.append(category);

    const summary = document.createElement("p");
    summary.className = "summary";
    summary.textContent = metadata.summary;
    view.append(summary);

    if (lowest && highest) {
      view.append(renderScale(lowest, highest, metadata.units, metadata.reversedScale));
    }

    view.append(renderCountryList(rows, metadata.reversedScale));
    detail.append(view);
    hoveredItem = null;
    selectedItem = null;
    applyCountryHighlight(true);
  }

  function renderCountryList(rows: MetricRow[], reversedScale: boolean): HTMLElement {
    const list = document.createElement("div");
    list.className = "country-list";
    let pointerX = 0;
    let pointerY = 0;
    let pointerInsideList = false;
    const sort: { column: SortColumn; direction: SortDirection } = {
      column: "value",
      direction: reversedScale ? "asc" : "desc",
    };

    const header = document.createElement("div");
    header.className = "country-list-header";
    const sortButtons = new Map<SortColumn, HTMLButtonElement>();
    const columns: Array<[SortColumn, string]> = [
      ["country", "Country"],
      ["value", "Value"],
      ["year", "Year"],
    ];
    for (const [column, label] of columns) {
      const cell = document.createElement("span");
      cell.className = `column ${column}`;
      const title = document.createElement("span");
      title.textContent = label;
      const button = renderSortButton(label);
      button.addEventListener("click", (event) => {
        const target = event.target;
        const chosen = target instanceof HTMLElement ? target.dataset.direction : undefined;
        sort.column = column;
        sort.direction = chosen === "desc" ? "desc" : "asc";
        reorderCountries();
      });
      sortButtons.set(column, button);
      cell.append(title, button);
      header.append(cell);
    }

    const items = document.createElement("ul");
    items.className = "country-list-items";
    const byCode = new Map<string, HTMLLIElement>();
    const entries: Array<{ row: MetricRow; item: HTMLLIElement }> = [];
    for (const row of rows) {
      const item = document.createElement("li");
      item.className = "country-list-item";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = row.country;
      name.title = row.country;
      const value = document.createElement("span");
      value.className = "value";
      value.textContent = formatNumber(row.value);
      const year = document.createElement("span");
      year.className = "year";
      year.textContent = String(row.year);
      item.append(name, value, year);
      if (row.code) {
        item.dataset.code = row.code;
      }
      item.addEventListener("mouseenter", (event) => {
        pointerX = event.clientX;
        pointerY = event.clientY;
        pointerInsideList = true;
        if (row.code) {
          hoverListCountry(row.code);
        }
      });
      item.addEventListener("mouseleave", (event) => {
        if (!row.code || hoveredCode !== row.code) {
          return;
        }
        const next = event.relatedTarget;
        if (next instanceof Node && items.contains(next)) {
          return;
        }
        pointerX = event.clientX;
        pointerY = event.clientY;
        const underPointer = rowUnderPointer();
        if (underPointer && underPointer !== row.code) {
          hoverListCountry(underPointer);
        }
      });
      item.addEventListener("click", () => {
        if (!row.code) {
          return;
        }
        selectedCode = row.code;
        hoveredCode = null;
        applyCountryHighlight(false);
        info.onSelect(map.selectCountry(row.code)?.country ?? countryFromRow(row));
      });
      entries.push({ row, item });
      if (row.code) {
        byCode.set(row.code, item);
      }
    }

    const reorderCountries = () => {
      const factor = sort.direction === "asc" ? 1 : -1;
      entries.sort((left, right) => {
        const primary =
          sort.column === "country"
            ? left.row.country.localeCompare(right.row.country, "en")
            : sort.column === "value"
              ? left.row.value - right.row.value
              : left.row.year - right.row.year;
        if (primary !== 0) {
          return primary * factor;
        }
        return left.row.country.localeCompare(right.row.country, "en");
      });
      for (const entry of entries) {
        items.append(entry.item);
      }
      for (const [column, button] of sortButtons) {
        const active = column === sort.column;
        button.dataset.sort = active ? sort.direction : "none";
        button.setAttribute(
          "aria-label",
          active
            ? `Sorted by ${column} ${sort.direction === "asc" ? "ascending" : "descending"}`
            : `Sort by ${column}`,
        );
      }
      const focusCode = hoveredCode ?? selectedCode;
      const focused = focusCode ? byCode.get(focusCode) : undefined;
      if (focused) {
        revealCountry(items, focused);
      }
    };

    const hoverListCountry = (code: string) => {
      if (hoveredCode === code) {
        return;
      }
      hoveredCode = code;
      applyCountryHighlight(false);
      info.onHover(map.highlightCountry(code)?.country ?? listedCountry(code));
    };

    const listedCountry = (code: string): CountryProperties | null => {
      const entry = entries.find((item) => item.row.code === code);
      return entry ? countryFromRow(entry.row) : null;
    };

    const rowUnderPointer = (): string | null => {
      if (!pointerInsideList) {
        return null;
      }
      const target = document.elementFromPoint(pointerX, pointerY);
      const row = target instanceof Element ? target.closest(".country-list-item") : null;
      if (!(row instanceof HTMLLIElement) || !items.contains(row)) {
        return null;
      }
      return row.dataset.code || null;
    };

    items.addEventListener("mousemove", (event) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      pointerInsideList = true;
    });
    items.addEventListener("mouseleave", () => {
      pointerInsideList = false;
      if (hoveredCode !== null) {
        hoveredCode = null;
        map.highlightCountry(null);
        info.onHover(null);
      }
      applyCountryHighlight(true);
    });
    items.addEventListener("scroll", () => {
      if (!pointerInsideList) {
        return;
      }
      const code = rowUnderPointer();
      if (code) {
        hoverListCountry(code);
      }
    });

    list.append(header, items);
    countryItems = byCode;
    countryListItems = items;
    reorderCountries();
    return list;
  }

  function applyCountryHighlight(reveal: boolean): void {
    const nextHover = hoveredCode ? (countryItems.get(hoveredCode) ?? null) : null;
    const nextSelected = selectedCode ? (countryItems.get(selectedCode) ?? null) : null;
    if (nextHover === hoveredItem && nextSelected === selectedItem) {
      return;
    }
    const previousReveal = hoveredItem ?? selectedItem;
    hoveredItem?.classList.remove("is-hover");
    hoveredItem?.removeAttribute("aria-current");
    selectedItem?.classList.remove("is-selected");
    selectedItem?.removeAttribute("aria-current");
    hoveredItem = nextHover;
    selectedItem = nextSelected;
    if (selectedItem && selectedItem !== hoveredItem) {
      selectedItem.classList.add("is-selected");
    }
    if (hoveredItem) {
      hoveredItem.classList.add("is-hover");
    }
    const revealTarget = hoveredItem ?? selectedItem;
    revealTarget?.setAttribute("aria-current", "true");
    if (reveal && revealTarget && revealTarget !== previousReveal && countryListItems) {
      revealCountry(countryListItems, revealTarget);
    }
  }
}

function countryFromRow(row: MetricRow): CountryProperties {
  return {
    name: row.country,
    iso_a3: row.code,
    iso_a2: "",
    continent: "",
  };
}

function fillMetricSelect(select: HTMLSelectElement): void {
  const options = [...worldMetrics].sort((left, right) =>
    left.metadata.description.localeCompare(right.metadata.description),
  );
  for (const metric of options) {
    const option = document.createElement("option");
    option.value = metric.metadata.key;
    option.textContent = metric.metadata.description;
    select.append(option);
  }
}

function renderMetricHeading(
  description: string,
  fields: Array<[string, string | HTMLElement]>,
): HTMLElement {
  const heading = document.createElement("div");
  heading.className = "metric-heading";

  const title = document.createElement("h2");
  title.textContent = description;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "details-button";
  button.textContent = "Details";

  const dialog = document.createElement("dialog");
  dialog.className = "metric-dialog";
  const dialogTitle = document.createElement("h2");
  dialogTitle.textContent = description;
  dialog.setAttribute("aria-labelledby", "metric-dialog-title");
  dialogTitle.id = "metric-dialog-title";

  const close = document.createElement("button");
  close.type = "button";
  close.className = "dialog-close";
  close.textContent = "Close";
  close.addEventListener("click", () => dialog.close());

  const dialogHeading = document.createElement("div");
  dialogHeading.className = "dialog-heading";
  dialogHeading.append(dialogTitle, close);
  dialog.append(dialogHeading, renderFields(fields));
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close();
    }
  });
  button.addEventListener("click", () => dialog.showModal());

  heading.append(title, button, dialog);
  return heading;
}

function renderScale(
  lowest: MetricRow[],
  highest: MetricRow[],
  units: string,
  reversedScale: boolean,
): HTMLElement {
  const scale = document.createElement("div");
  scale.className = "scale";
  const bar = document.createElement("div");
  bar.className = "scale-bar";
  bar.setAttribute("role", "img");
  bar.setAttribute(
    "aria-label",
    reversedScale
      ? "High values are red, middle values are yellow, and low values are green."
      : "Low values are red, middle values are yellow, and high values are green.",
  );
  const labels = document.createElement("div");
  labels.className = "scale-labels";
  const low = document.createElement("span");
  low.textContent = formatValue((reversedScale ? highest : lowest)[0].value, units, true);
  const high = document.createElement("span");
  high.textContent = formatValue((reversedScale ? lowest : highest)[0].value, units, true);
  labels.append(low, high);
  scale.append(bar, labels);
  return scale;
}

type SortColumn = "country" | "value" | "year";
type SortDirection = "asc" | "desc";

function renderSortButton(label: string): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "sort-button";
  button.dataset.sort = "none";
  button.setAttribute("aria-label", `Sort by ${label}`);
  const up = document.createElement("span");
  up.className = "up";
  up.dataset.direction = "asc";
  const down = document.createElement("span");
  down.className = "down";
  down.dataset.direction = "desc";
  button.append(up, down);
  return button;
}

function revealCountry(list: HTMLElement, item: HTMLElement): void {
  const top = item.offsetTop;
  const bottom = top + item.offsetHeight;
  const viewTop = list.scrollTop;
  const viewBottom = viewTop + list.clientHeight;
  if (top < viewTop) {
    list.scrollTop = top;
  } else if (bottom > viewBottom) {
    list.scrollTop = bottom - list.clientHeight;
  }
}

function renderFields(fields: Array<[string, string | HTMLElement]>): HTMLDListElement {
  const list = document.createElement("dl");
  for (const [label, value] of fields) {
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    if (typeof value === "string") {
      definition.textContent = value;
    } else {
      definition.append(value);
    }
    list.append(term, definition);
  }
  return list;
}

function extremeRows(rows: MetricRow[], which: "min" | "max"): MetricRow[] | null {
  if (rows.length === 0) {
    return null;
  }
  const target = which === "min" ? Math.min(...rows.map((row) => row.value)) : Math.max(...rows.map((row) => row.value));
  return rows.filter((row) => row.value === target);
}

function formatExtreme(rows: MetricRow[], units: string): string {
  const sample = rows[0];
  const names = rows.length === 1 ? sample.country : `${sample.country} and ${rows.length - 1} more`;
  return `${names} · ${formatValue(sample.value, units)} · ${sample.year}`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 4 }).format(value);
}

function formatValue(value: number, units: string, parentheses = false): string {
  return `${formatNumber(value)} ${parentheses ? ` (${units})` : units}`;
}

function link(url: string): HTMLAnchorElement {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.textContent = url;
  anchor.target = "_blank";
  anchor.rel = "noreferrer";
  return anchor;
}
