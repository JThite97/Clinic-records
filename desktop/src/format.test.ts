import { describe, expect, it } from "vitest";
import { dosesPerDay, suggestQuantity, vitalsLine } from "./format";

describe("prescription helpers", () => {
  it("counts doses per day", () => {
    expect(dosesPerDay("1-0-1")).toBe(2);
    expect(dosesPerDay("1-1-1-1")).toBe(4);
    expect(dosesPerDay("0.5-0-0.5")).toBe(1);
    expect(dosesPerDay("Once a day")).toBe(1);
    expect(dosesPerDay("SOS")).toBeNull();
  });
  it("suggests quantity", () => {
    expect(suggestQuantity("1-0-1", "5 days", "1 tab")).toBe("10");
    expect(suggestQuantity("1-1-1", "2 weeks", "1 cap")).toBe("42");
    expect(suggestQuantity("1-0-1", "5 days", "10 ml")).toBe("");
  });
  it("formats vitals", () => {
    expect(vitalsLine({ bp_systolic: 120, bp_diastolic: 80, pulse: 72, temperature: null, spo2: 98, weight: null })).toBe("BP 120/80 · Pulse 72 · SpO2 98%");
  });
});
