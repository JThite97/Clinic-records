export function fmtDate(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v.length === 10 ? v + "T00:00:00" : v);
  if (isNaN(d.getTime())) return v;
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

export function fmtDateTime(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  if (isNaN(d.getTime())) return v;
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function ageSex(p: { age: number | null; sex: string }): string {
  const sex = ({ M: "Male", F: "Female", O: "Other" } as Record<string, string>)[p.sex] || "";
  return [p.age != null ? `${p.age} y` : "", sex].filter(Boolean).join(" · ");
}

/** Local date-time string for <input type="datetime-local">. */
export function toLocalInput(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function vitalsLine(v: { bp_systolic: number | null; bp_diastolic: number | null; pulse: number | null; temperature: number | null; spo2: number | null; weight: number | null; resp_rate?: number | null; height?: number | null }): string {
  const parts: string[] = [];
  if (v.bp_systolic && v.bp_diastolic) parts.push(`BP ${v.bp_systolic}/${v.bp_diastolic}`);
  if (v.pulse) parts.push(`Pulse ${v.pulse}`);
  if (v.temperature) parts.push(`Temp ${v.temperature}°C`);
  if (v.spo2) parts.push(`SpO2 ${v.spo2}%`);
  if (v.resp_rate) parts.push(`RR ${v.resp_rate}`);
  if (v.weight) parts.push(`Wt ${v.weight} kg`);
  if (v.height) parts.push(`Ht ${v.height} cm`);
  return parts.join(" · ");
}

/** Frequency like 1-0-1 → doses per day (used to suggest a quantity). */
export function dosesPerDay(freq: string): number | null {
  const m = freq.trim().match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$/);
  if (m) return m.slice(1).filter(Boolean).reduce((a, b) => a + parseFloat(b), 0);
  const f = freq.toLowerCase();
  if (/once|od\b|daily/.test(f)) return 1;
  if (/twice|bd\b/.test(f)) return 2;
  if (/thrice|tds\b|tid\b/.test(f)) return 3;
  return null;
}

export function suggestQuantity(freq: string, duration: string, dose: string): string {
  const perDay = dosesPerDay(freq);
  const days = duration.match(/(\d+)\s*(day|week|month)/i);
  const unit = dose.match(/^(\d+(?:\.\d+)?)\s*(tab|cap)/i);
  if (!perDay || !days || !unit) return "";
  const mult = /week/i.test(days[2]) ? 7 : /month/i.test(days[2]) ? 30 : 1;
  return String(Math.ceil(perDay * parseInt(days[1]) * mult * parseFloat(unit[1])));
}
