import L from "leaflet";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createCountryMap, type CountryMap } from "./map";

describe("createCountryMap", () => {
  let countryMap: CountryMap;

  afterEach(() => {
    countryMap?.map.remove();
    document.body.replaceChildren();
  });

  it("paints a hovered country purple and clears the previous hover", () => {
    const { map, onHover } = mount();
    const france = countryLayer(map, "FRA");
    const germany = countryLayer(map, "DEU");

    hover(france);
    hover(germany);

    expect(france.options.color).toBe("white");
    expect(germany.options.color).toBe("#7c3aed");
    expect(onHover).toHaveBeenLastCalledWith(expect.objectContaining({ country: expect.objectContaining({ iso_a3: "DEU" }) }));
  });

  it("ignores a late mouseout from a country that is no longer highlighted", () => {
    const { map, onHover } = mount();
    const france = countryLayer(map, "FRA");
    const germany = countryLayer(map, "DEU");

    hover(france);
    hover(germany);
    france.fire("mouseout");

    expect(germany.options.color).toBe("#7c3aed");
    expect(onHover).toHaveBeenLastCalledWith(expect.objectContaining({ country: expect.objectContaining({ iso_a3: "DEU" }) }));
  });

  it("selects a country without changing the zoom", () => {
    const { map, onClick } = mount();
    const france = countryLayer(map, "FRA");
    const zoom = map.map.getZoom();
    const stop = vi.spyOn(L.DomEvent, "stopPropagation");

    click(france);

    expect(map.map.getZoom()).toBe(zoom);
    expect(france.options.color).toBe("#1d4e89");
    expect(stop).toHaveBeenCalled();
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ country: expect.objectContaining({ iso_a3: "FRA" }) }));
  });

  it("clears the selection when the map is clicked outside a country", () => {
    const { map, onClick } = mount();
    const france = countryLayer(map, "FRA");
    click(france);

    map.map.fire("click");

    expect(france.options.color).toBe("white");
    expect(onClick).toHaveBeenLastCalledWith(null);
  });

  it("draws a tiny border for a small country and clears that selection from a map click", () => {
    const { map, onClick } = mount();
    const singapore = countryLayer(map, "SGP") as L.Polygon;
    const bounds = singapore.getBounds();

    expect(singapore).toBeInstanceOf(L.Polygon);
    expect(singapore.options.color).toBe("white");
    expect(singapore.options.weight).toBe(1);
    expect(bounds.getNorth() - bounds.getSouth()).toBeLessThan(0.5);
    expect(bounds.getEast() - bounds.getWest()).toBeLessThan(0.5);

    const selected = map.selectCountry("SGP");

    expect(selected?.country).toMatchObject({ iso_a3: "SGP", name: "Singapore" });
    expect(singapore.options.color).toBe("#1d4e89");
    expect(singapore.options.weight).toBe(2);

    map.map.fire("click");

    expect(singapore.options.color).toBe("white");
    expect(singapore.options.weight).toBe(1);
    expect(onClick).toHaveBeenLastCalledWith(null);
  });

  it("clears a list selection that has no country shape when the map is clicked", () => {
    const { map, onClick } = mount();
    const france = countryLayer(map, "FRA");
    map.selectCountry("FRA");

    expect(map.selectCountry("ZZZ")).toBeNull();
    expect(france.options.color).toBe("white");

    map.map.fire("click");

    expect(onClick).toHaveBeenLastCalledWith(null);
  });

  it("drives hover and selection from country codes without calling the map handlers", () => {
    const { map, onHover, onClick } = mount();

    const hovered = map.highlightCountry("FRA");
    const selected = map.selectCountry("DEU");

    expect(hovered?.country.iso_a3).toBe("FRA");
    expect(countryLayer(map, "FRA").options.color).toBe("white");
    expect(selected?.country.iso_a3).toBe("DEU");
    expect(countryLayer(map, "DEU").options.color).toBe("#1d4e89");
    expect(onHover).not.toHaveBeenCalled();
    expect(onClick).not.toHaveBeenCalled();
    expect(map.highlightCountry("ZZZ")).toBeNull();
    expect(map.selectCountry(null)).toBeNull();
    expect(countryLayer(map, "DEU").options.color).toBe("white");
  });

  it("keeps a metric color under the hover and selection strokes", () => {
    const { map } = mount();
    map.setMetricColors(new Map([["FRA", "rgb(1, 2, 3)"]]));
    const france = countryLayer(map, "FRA");
    const germany = countryLayer(map, "DEU");

    expect(france.options.fillColor).toBe("rgb(1, 2, 3)");
    expect(germany.options.fillColor).toBe("#3388ff");

    map.highlightCountry("FRA");
    expect(france.options.color).toBe("#7c3aed");
    expect(france.options.fillColor).toBe("rgb(1, 2, 3)");

    map.selectCountry("FRA");
    expect(france.options.color).toBe("#1d4e89");
    expect(france.options.fillColor).toBe("rgb(1, 2, 3)");
  });

  function mount(): { map: CountryMap; onHover: ReturnType<typeof vi.fn>; onClick: ReturnType<typeof vi.fn> } {
    const element = document.createElement("div");
    Object.defineProperty(element, "clientWidth", { configurable: true, value: 800 });
    Object.defineProperty(element, "clientHeight", { configurable: true, value: 600 });
    document.body.append(element);
    const onHover = vi.fn();
    const onClick = vi.fn();
    countryMap = createCountryMap(element, { onHover, onClick });
    return { map: countryMap, onHover, onClick };
  }
});

function countryLayer(countryMap: CountryMap, code: string): L.Path {
  let found: L.Path | undefined;
  countryMap.map.eachLayer((layer) => {
    if (!(layer instanceof L.GeoJSON)) {
      return;
    }
    layer.eachLayer((featureLayer) => {
      const feature = (featureLayer as L.Layer & { feature?: { properties?: { iso_a3?: string } } }).feature;
      if (feature?.properties?.iso_a3 === code) {
        found = featureLayer as L.Path;
      }
    });
  });
  if (!found) {
    throw new Error(`Missing country layer ${code}`);
  }
  return found;
}

function hover(layer: L.Path): void {
  layer.fire("mouseover", {
    latlng: L.latLng(10, 20),
    originalEvent: new MouseEvent("mouseover", { clientX: 3, clientY: 4 }),
  });
}

function click(layer: L.Path): void {
  layer.fire("click", {
    latlng: L.latLng(10, 20),
    originalEvent: new MouseEvent("click", { clientX: 3, clientY: 4 }),
  });
}
