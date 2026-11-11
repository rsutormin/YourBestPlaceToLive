import { describe, expect, it } from "vitest";

import {
  colorForScale,
  colorsForMetric,
  robustScale,
  scaleValue,
  worldMetrics,
  type WorldMetric,
} from "./metrics";

describe("robustScale", () => {
  it("returns zero when the interquartile range is not positive", () => {
    expect(robustScale(10, 5, 0)).toBe(0);
    expect(robustScale(10, 5, -1)).toBe(0);
  });

  it("compresses a typical value with tanh and flips reversed metrics", () => {
    expect(robustScale(5, 5, 2)).toBe(0);
    expect(robustScale(7, 5, 2)).toBeCloseTo(Math.tanh(1));
    expect(robustScale(7, 5, 2, true)).toBeCloseTo(Math.tanh(-1));
  });

  it("lets outliers continue past the tanh fence on a straight line", () => {
    const edge = Math.tanh(2);
    const slope = 1 - edge * edge;
    const expected = edge + slope;

    expect(robustScale(8, 5, 1)).toBeCloseTo(expected);
    expect(expected).toBeGreaterThan(1);
    expect(robustScale(2, 5, 1)).toBeCloseTo(-expected);
  });
});

describe("scaleValue", () => {
  it("maps the robust score onto the color range and clamps the ends", () => {
    expect(scaleValue(5, 5, 2)).toBe(0.5);
    expect(scaleValue(7, 5, 2)).toBeCloseTo((Math.tanh(1) + 1) / 2);
    expect(scaleValue(8, 5, 1)).toBe(1);
    expect(scaleValue(2, 5, 1)).toBe(0);
    expect(scaleValue(7, 5, 2, true)).toBeCloseTo((Math.tanh(-1) + 1) / 2);
  });
});

describe("colorForScale", () => {
  it("blends red through yellow to green", () => {
    expect(colorForScale(0)).toBe("rgb(255, 0, 0)");
    expect(colorForScale(0.25)).toBe("rgb(255, 128, 0)");
    expect(colorForScale(0.5)).toBe("rgb(255, 255, 0)");
    expect(colorForScale(0.75)).toBe("rgb(128, 255, 0)");
    expect(colorForScale(1)).toBe("rgb(0, 255, 0)");
  });

  it("clamps positions outside the color range", () => {
    expect(colorForScale(-1)).toBe("rgb(255, 0, 0)");
    expect(colorForScale(2)).toBe("rgb(0, 255, 0)");
  });
});

describe("colorsForMetric", () => {
  it("colors finite country values from their median and interquartile range", () => {
    const metric = sampleMetric([1, 2, 3, 4, 5], false);
    const colors = colorsForMetric(metric);

    expect(colors.size).toBe(5);
    expect(colors.get("C3")).toBe(colorForScale(0.5));
    expect(colors.get("C5")).toBe(colorForScale(scaleValue(5, 3, 2, false)));
    expect(colors.get("C1")).toBe(colorForScale(scaleValue(1, 3, 2, false)));
  });

  it("reverses the color when a higher value is worse", () => {
    const metric = sampleMetric([1, 2, 3, 4, 5], true);

    expect(colorsForMetric(metric).get("C5")).toBe(colorForScale(scaleValue(5, 3, 2, true)));
  });

  it("skips blank codes and non-finite values", () => {
    const metric = sampleMetric([1], false);
    metric.data.push(
      { country: "Blank", code: "", value: 2, year: 2021 },
      { country: "Missing", code: "MIS", value: Number.NaN, year: 2021 },
    );

    const colors = colorsForMetric(metric);

    expect([...colors.keys()]).toEqual(["C1"]);
    expect(colors.get("C1")).toBe(colorForScale(0.5));
  });

  it("returns no colors when every value is missing", () => {
    expect(colorsForMetric(sampleMetric([], false)).size).toBe(0);
  });
});

describe("worldMetrics", () => {
  it("gives every metric one title, one units field, and a world scope", () => {
    const keys = worldMetrics.map((metric) => metric.metadata.key);

    expect(new Set(keys).size).toBe(keys.length);
    for (const metric of worldMetrics) {
      expect(metric.metadata.scope).toBe("World");
      expect(metric.metadata.description).not.toContain("(");
      expect(metric.metadata.summary.length).toBeGreaterThan(0);
      expect(typeof metric.metadata.reversedScale).toBe("boolean");
    }
  });
});

function sampleMetric(values: number[], reversedScale: boolean): WorldMetric {
  return {
    metadata: {
      source: "Test",
      scope: "World",
      database: "test",
      url: "https://example.com",
      code: "TEST",
      key: "test",
      description: "Test metric",
      summary: "A synthetic metric used to check scaling.",
      category: "Test",
      units: "units",
      reversedScale,
      dataSize: values.length,
      retrievedAt: "2026-01-01T00:00:00Z",
    },
    data: values.map((value, index) => ({
      country: `Country ${index + 1}`,
      code: `C${index + 1}`,
      value,
      year: 2021,
    })),
  };
}
