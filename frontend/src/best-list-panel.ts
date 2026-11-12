import type { CountryProperties } from "./countries";
import type { CountryMap } from "./map";
import { worldMetrics } from "./metrics";
import {
  colorsForScores,
  DEFAULT_IMPORTANCE,
  importanceLabel,
  importanceValue,
  scoreCountries,
  type CountryScoreRow,
} from "./best-list";

export interface BestListPanel {
  setHoveredCountry(code: string | null): void;
  setSelectedCountry(code: string | null): void;
}

export interface BestListHandlers {
  onHover(country: CountryProperties | null): void;
  onSelect(country: CountryProperties | null): void;
  onScores(colors: ReadonlyMap<string, string>): void;
}

interface ScoreEntry {
  row: CountryScoreRow;
  item: HTMLLIElement;
  score: HTMLElement;
}

type SortColumn = "country" | "score";
type SortDirection = "asc" | "desc";

export function createBestListPanel(
  host: HTMLElement,
  map: CountryMap,
  handlers: BestListHandlers,
): BestListPanel {
  const weights = new Map(
    worldMetrics.map((metric) => [metric.metadata.key, importanceValue(metric.metadata.importance)]),
  );
  const entries = new Map<string, ScoreEntry>();
  let hoveredCode: string | null = null;
  let selectedCode: string | null = null;
  let hoveredItem: HTMLLIElement | null = null;
  let selectedItem: HTMLLIElement | null = null;
  let pointerX = 0;
  let pointerY = 0;
  let pointerInsideList = false;
  const sort: { column: SortColumn; direction: SortDirection } = { column: "score", direction: "desc" };

  const weightList = document.createElement("ul");
  weightList.className = "weight-list";
  const metrics = [...worldMetrics].sort((left, right) =>
    left.metadata.description.localeCompare(right.metadata.description, "en"),
  );
  for (const metric of metrics) {
    weightList.append(renderWeight(metric.metadata.key, metric.metadata.description));
  }

  const scale = document.createElement("div");
  scale.className = "scale";
  const scaleBar = document.createElement("div");
  scaleBar.className = "scale-bar";
  scaleBar.setAttribute("role", "img");
  scaleBar.setAttribute(
    "aria-label",
    "Low scores are red, middle scores are yellow, and high scores are green.",
  );
  const scaleLabels = document.createElement("div");
  scaleLabels.className = "scale-labels";
  const lowScore = document.createElement("span");
  const highScore = document.createElement("span");
  scaleLabels.append(lowScore, highScore);
  scale.append(scaleBar, scaleLabels);

  const scoreList = document.createElement("div");
  scoreList.className = "country-list";
  const header = document.createElement("div");
  header.className = "country-list-header";
  const sortButtons = new Map<SortColumn, HTMLButtonElement>();
  const columns: Array<[SortColumn, string]> = [
    ["country", "Country"],
    ["score", "Score"],
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
      reorder(true);
    });
    sortButtons.set(column, button);
    cell.append(title, button);
    header.append(cell);
  }
  const items = document.createElement("ul");
  items.className = "country-list-items";
  scoreList.append(header, items);
  host.replaceChildren(weightList, scale, scoreList);
  refreshScores();

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
      handlers.onHover(null);
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

  function renderWeight(key: string, description: string): HTMLLIElement {
    const row = document.createElement("li");
    row.className = "weight-row";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = description;
    name.title = description;
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "1";
    slider.step = "0.25";
    const importance = weights.get(key) ?? DEFAULT_IMPORTANCE;
    slider.value = String(importance);
    slider.dataset.key = key;
    slider.setAttribute("aria-label", `Importance of ${description}`);
    slider.setAttribute("aria-valuetext", importanceLabel(importance));
    const level = document.createElement("span");
    level.className = "weight-label";
    level.textContent = importanceLabel(importance);
    slider.addEventListener("input", () => {
      const weight = importanceValue(slider.valueAsNumber);
      weights.set(key, weight);
      const label = importanceLabel(weight);
      level.textContent = label;
      slider.setAttribute("aria-valuetext", label);
      refreshScores();
    });
    const control = document.createElement("div");
    control.className = "weight-control";
    control.append(slider, level);
    row.append(name, control);
    return row;
  }

  function refreshScores(): void {
    const scores = scoreCountries(worldMetrics, weights);
    updateScale(scores);
    handlers.onScores(colorsForScores(scores));
    const seen = new Set<string>();
    for (const score of scores) {
      seen.add(score.code);
      const existing = entries.get(score.code);
      if (existing) {
        existing.row = score;
        existing.score.textContent = formatNumber(score.score);
        continue;
      }
      entries.set(score.code, createEntry(score));
    }
    for (const code of [...entries.keys()]) {
      if (seen.has(code)) {
        continue;
      }
      entries.get(code)?.item.remove();
      entries.delete(code);
    }
    if (entries.size === 0) {
      items.replaceChildren(emptyScores());
      applyCountryHighlight(false);
      return;
    }
    items.querySelector(".country-metrics-empty")?.remove();
    reorder(false);
    applyCountryHighlight(false);
  }

  function updateScale(scores: readonly CountryScoreRow[]): void {
    if (scores.length === 0) {
      lowScore.textContent = "—";
      highScore.textContent = "—";
      return;
    }
    let lowest = scores[0].score;
    let highest = scores[0].score;
    for (const row of scores) {
      lowest = Math.min(lowest, row.score);
      highest = Math.max(highest, row.score);
    }
    lowScore.textContent = formatNumber(lowest);
    highScore.textContent = formatNumber(highest);
  }

  function createEntry(score: CountryScoreRow): ScoreEntry {
    const item = document.createElement("li");
    item.className = "country-list-item";
    item.dataset.code = score.code;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = score.country;
    name.title = score.country;
    const value = document.createElement("span");
    value.className = "value";
    value.textContent = formatNumber(score.score);
    item.append(name, value);
    item.addEventListener("mouseenter", (event) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      pointerInsideList = true;
      hoverListCountry(score.code);
    });
    item.addEventListener("mouseleave", (event) => {
      if (hoveredCode !== score.code) {
        return;
      }
      const next = event.relatedTarget;
      if (next instanceof Node && items.contains(next)) {
        return;
      }
      pointerX = event.clientX;
      pointerY = event.clientY;
      const underPointer = rowUnderPointer();
      if (underPointer && underPointer !== score.code) {
        hoverListCountry(underPointer);
      }
    });
    item.addEventListener("click", () => {
      const entry = entries.get(score.code);
      if (!entry) {
        return;
      }
      selectedCode = score.code;
      hoveredCode = null;
      applyCountryHighlight(false);
      handlers.onSelect(map.selectCountry(score.code)?.country ?? countryFromScore(entry.row));
    });
    return { row: score, item, score: value };
  }

  function reorder(revealFocus: boolean): void {
    const factor = sort.direction === "asc" ? 1 : -1;
    const ordered = [...entries.values()].sort((left, right) => {
      const primary =
        sort.column === "country"
          ? left.row.country.localeCompare(right.row.country, "en")
          : left.row.score - right.row.score;
      if (primary !== 0) {
        return primary * factor;
      }
      return left.row.country.localeCompare(right.row.country, "en");
    });
    for (const entry of ordered) {
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
    if (!revealFocus) {
      return;
    }
    const focusCode = hoveredCode ?? selectedCode;
    const focused = focusCode ? entries.get(focusCode)?.item : undefined;
    if (focused) {
      revealCountry(items, focused);
    }
  }

  function hoverListCountry(code: string): void {
    if (hoveredCode === code) {
      return;
    }
    hoveredCode = code;
    applyCountryHighlight(false);
    const entry = entries.get(code);
    handlers.onHover(map.highlightCountry(code)?.country ?? (entry ? countryFromScore(entry.row) : null));
  }

  function rowUnderPointer(): string | null {
    if (!pointerInsideList) {
      return null;
    }
    const target = document.elementFromPoint(pointerX, pointerY);
    const row = target instanceof Element ? target.closest(".country-list-item") : null;
    if (!(row instanceof HTMLLIElement) || !items.contains(row)) {
      return null;
    }
    return row.dataset.code || null;
  }

  function applyCountryHighlight(reveal: boolean): void {
    const nextHover = hoveredCode ? (entries.get(hoveredCode)?.item ?? null) : null;
    const nextSelected = selectedCode ? (entries.get(selectedCode)?.item ?? null) : null;
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
    if (reveal && revealTarget && revealTarget !== previousReveal) {
      revealCountry(items, revealTarget);
    }
  }
}

function countryFromScore(row: CountryScoreRow): CountryProperties {
  return {
    name: row.country,
    iso_a3: row.code,
    iso_a2: "",
    continent: "",
  };
}

function emptyScores(): HTMLLIElement {
  const empty = document.createElement("li");
  empty.className = "country-metrics-empty";
  empty.textContent = "Set a metric above Not important to score countries.";
  return empty;
}

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

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 4 }).format(value);
}
