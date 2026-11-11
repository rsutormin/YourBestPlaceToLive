import worldMetricsJson from "./world-metrics.json";

export interface MetricMetadata {
  source: string;
  scope: string;
  database: string;
  url: string;
  code: string;
  key: string;
  description: string;
  summary: string;
  category: string;
  units: string;
  reversedScale: boolean;
  dataSize: number;
  retrievedAt: string;
}

export interface MetricRow {
  country: string;
  code: string;
  value: number;
  year: number;
}

export interface WorldMetric {
  metadata: MetricMetadata;
  data: MetricRow[];
}

export const worldMetrics = worldMetricsJson as unknown as WorldMetric[];

/**
 * Robust z at the Tukey fence: 1.5 IQR past the quartile, which is 2 IQR from
 * the median. Values inside this fence stay within [-1, 1] after compression.
 */
const OUTLIER_Z = 2;

/**
 * Step 1. Median/IQR score with a smooth tanh core. Most countries land strictly
 * inside [-1, 1]. Past the outlier fence the curve continues in a straight line,
 * so rare extremes can pass those bounds. A reversed metric flips the sign here.
 */
export function robustScale(
  value: number,
  median: number,
  iqr: number,
  reversedScale = false,
): number {
  if (!(iqr > 0)) {
    return 0;
  }
  const direction = reversedScale ? -1 : 1;
  return compress(((value - median) / iqr) * direction);
}

/**
 * Color position in [0, 1]. Step 1 produces the comparable score, then step 2
 * maps that score from [-1, 1] onto [0, 1]. Scores outside [-1, 1] sit on the
 * ends of the color range.
 */
export function scaleValue(
  value: number,
  median: number,
  iqr: number,
  reversedScale = false,
): number {
  const robust = robustScale(value, median, iqr, reversedScale);
  return Math.min(1, Math.max(0, (robust + 1) / 2));
}

/** 0 is red, 0.5 is yellow, and 1 is green. */
export function colorForScale(scale: number): string {
  const t = Math.min(1, Math.max(0, scale));
  const [red, green, blue] =
    t <= 0.5
      ? lerp([255, 0, 0], [255, 255, 0], t / 0.5)
      : lerp([255, 255, 0], [0, 255, 0], (t - 0.5) / 0.5);
  return `rgb(${red}, ${green}, ${blue})`;
}

export function colorsForMetric(metric: WorldMetric): Map<string, string> {
  const rows = metric.data.filter((row) => Number.isFinite(row.value) && row.code);
  const colors = new Map<string, string>();
  if (rows.length === 0) {
    return colors;
  }
  const { median, iqr } = robustCenter(rows.map((row) => row.value));
  for (const row of rows) {
    colors.set(
      row.code,
      colorForScale(scaleValue(row.value, median, iqr, metric.metadata.reversedScale)),
    );
  }
  return colors;
}

function robustCenter(values: number[]): { median: number; iqr: number } {
  const sorted = [...values].sort((left, right) => left - right);
  const quartile1 = quantile(sorted, 0.25);
  const median = quantile(sorted, 0.5);
  const quartile3 = quantile(sorted, 0.75);
  return { median, iqr: quartile3 - quartile1 };
}

function quantile(sorted: readonly number[], probability: number): number {
  if (sorted.length === 1) {
    return sorted[0];
  }
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) {
    return sorted[lower];
  }
  const weight = position - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function compress(z: number): number {
  const magnitude = Math.abs(z);
  if (magnitude <= OUTLIER_Z) {
    return Math.tanh(z);
  }
  const edge = Math.tanh(OUTLIER_Z);
  const slope = 1 - edge * edge;
  return Math.sign(z) * edge + (z - Math.sign(z) * OUTLIER_Z) * slope;
}

function lerp(from: readonly [number, number, number], to: readonly [number, number, number], t: number): [number, number, number] {
  return [
    Math.round(from[0] + (to[0] - from[0]) * t),
    Math.round(from[1] + (to[1] - from[1]) * t),
    Math.round(from[2] + (to[2] - from[2]) * t),
  ];
}
