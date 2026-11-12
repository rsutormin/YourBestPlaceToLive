import { describe, expect, it } from "vitest";

import { colorsForScores, importanceLabel, importanceValue, scoreCountries } from "./best-list";
import { colorForScale, robustCountryScores, type WorldMetric } from "./metrics";

describe("importance levels", () => {
  it("snaps to the five importance scores", () => {
    expect(importanceValue(0)).toBe(0);
    expect(importanceValue(0.25)).toBe(0.25);
    expect(importanceValue(0.5)).toBe(0.5);
    expect(importanceValue(0.75)).toBe(0.75);
    expect(importanceValue(1)).toBe(1);
    expect(importanceValue(0.9)).toBe(1);
    expect(importanceValue(Number.NaN)).toBe(0.5);
    expect(importanceLabel(0)).toBe("Not important");
    expect(importanceLabel(0.25)).toBe("Slightly important");
    expect(importanceLabel(0.5)).toBe("Important");
    expect(importanceLabel(0.75)).toBe("Very important");
    expect(importanceLabel(1)).toBe("Extremely important");
  });
});

describe("scoreCountries", () => {
  const lower = metric("lower", false, [
    ["AAA", "Low", 0],
    ["BBB", "High", 10],
  ]);
  const higher = metric("higher", true, [
    ["BBB", "High", 10],
    ["CCC", "Other", 0],
  ]);

  it("averages robust scores by importance and skips metrics a country does not have", () => {
    const shared = metric("shared", false, [
      ["AAA", "Low", 1],
      ["BBB", "High", 1],
      ["CCC", "Other", 1],
    ]);
    const weights = new Map([
      ["lower", 0.25],
      ["higher", 0.75],
      ["shared", 0],
    ]);
    const scores = new Map(scoreCountries([lower, higher, shared], weights).map((row) => [row.code, row]));
    const lowOnly = robustCountryScores(lower).get("AAA");
    const highOnLower = robustCountryScores(lower).get("BBB");
    const highOnHigher = robustCountryScores(higher).get("BBB");

    expect(lowOnly).toBeTruthy();
    expect(scores.get("AAA")?.score).toBe(lowOnly?.score);
    expect(scores.get("BBB")?.score).toBeCloseTo(((highOnLower?.score ?? 0) * 0.25 + (highOnHigher?.score ?? 0) * 0.75) / 1);
    expect(scores.has("CCC")).toBe(true);
  });

  it("leaves out a metric whose importance is zero", () => {
    const scores = new Map(
      scoreCountries([lower, higher], new Map([["lower", 1], ["higher", 0]])).map((row) => [row.code, row]),
    );

    expect(scores.get("BBB")?.score).toBe(robustCountryScores(lower).get("BBB")?.score);
    expect(scores.has("CCC")).toBe(false);
  });

  it("leaves out countries with defined values for fewer than 66% of the metrics", () => {
    const metrics = [
      metric("one", false, [["AAA", "Sparse", 1], ["BBB", "Covered", 2]]),
      metric("two", false, [["BBB", "Covered", 3]]),
      metric("three", false, [["BBB", "Covered", 4], ["CCC", "Partial", 5]]),
      metric("four", false, [["CCC", "Partial", 6]]),
    ];
    const weights = new Map(metrics.map((item) => [item.metadata.key, 1]));
    const scores = new Map(scoreCountries(metrics, weights).map((row) => [row.code, row]));

    expect(scores.has("AAA")).toBe(false);
    expect(scores.has("BBB")).toBe(true);
    expect(scores.has("CCC")).toBe(false);
  });

  it("colors a weighted score from red through yellow to green", () => {
    const colors = colorsForScores([
      { country: "Low", code: "AAA", score: -1 },
      { country: "Mid", code: "BBB", score: 0 },
      { country: "High", code: "CCC", score: 1 },
      { country: "Beyond", code: "DDD", score: 2 },
    ]);

    expect(colors.get("AAA")).toBe(colorForScale(0));
    expect(colors.get("BBB")).toBe(colorForScale(0.5));
    expect(colors.get("CCC")).toBe(colorForScale(1));
    expect(colors.get("DDD")).toBe(colorForScale(1));
  });

  it("gives a reversed metric a worse robust score when the raw value is higher", () => {
    const scores = robustCountryScores(higher);

    expect(scores.get("BBB")?.score ?? 0).toBeLessThan(scores.get("CCC")?.score ?? 0);
  });
});

function metric(key: string, reversedScale: boolean, rows: Array<[string, string, number]>): WorldMetric {
  return {
    metadata: {
      source: "Test",
      scope: "World",
      database: "test",
      url: "https://example.com",
      code: key,
      key,
      description: key,
      summary: "Synthetic metric for score tests.",
      category: "Test",
      units: "units",
      reversedScale,
      importance: 0.5,
      dataSize: rows.length,
      retrievedAt: "2026-01-01T00:00:00Z",
    },
    data: rows.map(([code, country, value]) => ({ country, code, value, year: 2020 })),
  };
}
