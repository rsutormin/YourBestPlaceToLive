import { colorForScale, robustCountryScores, type WorldMetric } from "./metrics";

export interface CountryScoreRow {
  country: string;
  code: string;
  score: number;
}

export const IMPORTANCE_LEVELS = [
  { value: 0, label: "Not important" },
  { value: 0.25, label: "Slightly important" },
  { value: 0.5, label: "Important" },
  { value: 0.75, label: "Very important" },
  { value: 1, label: "Extremely important" },
] as const;

export const DEFAULT_IMPORTANCE = 0.5;

export function importanceValue(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_IMPORTANCE;
  }
  let closest: number = IMPORTANCE_LEVELS[0].value;
  for (const level of IMPORTANCE_LEVELS) {
    if (Math.abs(level.value - value) < Math.abs(closest - value)) {
      closest = level.value;
    }
  }
  return closest;
}

export function importanceLabel(value: number): string {
  const snapped = importanceValue(value);
  return IMPORTANCE_LEVELS.find((level) => level.value === snapped)?.label ?? "Important";
}

/**
 * Weighted average of robust scores. A metric the country does not report is left
 * out of both the total and the weight, and a weight of 0 does not count.
 * Countries with defined values for fewer than 66% of the metrics are left out.
 */
export function scoreCountries(
  metrics: readonly WorldMetric[],
  weights: ReadonlyMap<string, number>,
): CountryScoreRow[] {
  const coverage = new Map<string, number>();
  const totals = new Map<string, { country: string; weighted: number; weight: number }>();
  for (const metric of metrics) {
    const weight = weights.get(metric.metadata.key) ?? 0;
    for (const [code, row] of robustCountryScores(metric)) {
      coverage.set(code, (coverage.get(code) ?? 0) + 1);
      if (!(weight > 0)) {
        continue;
      }
      const current = totals.get(code) ?? { country: row.country, weighted: 0, weight: 0 };
      current.country = row.country;
      current.weighted += weight * row.score;
      current.weight += weight;
      totals.set(code, current);
    }
  }
  const scores: CountryScoreRow[] = [];
  for (const [code, total] of totals) {
    const covered = coverage.get(code) ?? 0;
    if (covered * 100 < metrics.length * 66 || !(total.weight > 0)) {
      continue;
    }
    scores.push({
      country: total.country,
      code,
      score: total.weighted / total.weight,
    });
  }
  return scores;
}

/** Map a weighted score from [-1, 1] onto the red–yellow–green scale. */
export function colorsForScores(rows: readonly CountryScoreRow[]): Map<string, string> {
  const colors = new Map<string, string>();
  for (const row of rows) {
    colors.set(row.code, colorForScale((row.score + 1) / 2));
  }
  return colors;
}
