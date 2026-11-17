import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { suggestQuantity } from "../format";
import { useDebounced } from "../hooks";
import type { Medicine, RxItem } from "../types";

export const blankItem = (name = ""): RxItem => ({ medicine_id: null, medicine_name: name, form: "", strength: "", dose: "", frequency: "", timing: "", duration: "", quantity: "", instructions: "" });

const FREQS = ["1-0-0", "0-1-0", "0-0-1", "1-0-1", "1-1-1", "1-1-1-1", "SOS", "Once a week", "As directed"];
const TIMINGS = ["After food", "Before food", "Empty stomach", "At bedtime", "With food", ""];

export default function PrescriptionBuilder({ items, onChange }: { items: RxItem[]; onChange: (items: RxItem[]) => void }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 120);
  const [results, setResults] = useState<Medicine[]>([]);
  const [hi, setHi] = useState(0);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!dq.trim()) { setResults([]); return; }
    let alive = true;
    api.get<Medicine[]>(`/api/medicines?limit=12&q=${encodeURIComponent(dq)}`).then((r) => { if (alive) { setResults(r); setHi(0); } }).catch(() => {});
    return () => { alive = false; };
  }, [dq]);

  function add(m: Medicine | null) {
    const it = m ? {
      ...blankItem(m.name), medicine_id: m.id, form: m.form, strength: m.strength, dose: m.default_dose,
      frequency: m.default_frequency, duration: m.default_duration,
      timing: TIMINGS.includes(m.default_instructions) ? m.default_instructions : "",
      instructions: TIMINGS.includes(m.default_instructions) ? "" : m.default_instructions,
    } : blankItem(q.trim());
    if (!it.medicine_name) return;
    it.quantity = suggestQuantity(it.frequency, it.duration, it.dose);
    onChange([...items, it]);
    setQ(""); setResults([]); setOpen(false);
    box.current?.focus();
  }

  function update(i: number, k: keyof RxItem, v: string) {
    const next = items.map((it, j) => {
      if (j !== i) return it;
      const n = { ...it, [k]: v };
      if (["frequency", "duration", "dose"].includes(k)) {
        const prevSuggest = suggestQuantity(it.frequency, it.duration, it.dose);
        if (!it.quantity || it.quantity === prevSuggest) n.quantity = suggestQuantity(n.frequency, n.duration, n.dose);
      }
      return n;
    });
    onChange(next);
  }

  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= items.length) return;
    const n = [...items];
    [n[i], n[j]] = [n[j], n[i]];
    onChange(n);
  };

  return (
    <div className="rx-builder">
      <div className="typeahead">
        <input ref={box} value={q} placeholder="Add medicine: type a name, e.g. para, amox, metformin…" aria-label="Add medicine"
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, results.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
            else if (e.key === "Enter") { e.preventDefault(); add(results[hi] ?? null); }
            else if (e.key === "Escape") setOpen(false);
          }} />
        {open && (results.length > 0 || q.trim()) && (
          <ul className="ta-menu" role="listbox">
            {results.map((m, i) => (
              <li key={m.id} role="option" aria-selected={i === hi} className={i === hi ? "hi" : ""} onMouseDown={(e) => { e.preventDefault(); add(m); }} onMouseEnter={() => setHi(i)}>
                <b>{m.name}</b> <span className="muted">{m.form}{m.category ? ` · ${m.category}` : ""}</span>
              </li>
            ))}
            {q.trim() && <li className="ta-free" onMouseDown={(e) => { e.preventDefault(); add(null); }}>Add “{q.trim()}” as written</li>}
          </ul>
        )}
      </div>
      {items.length === 0 ? <div className="empty small">No medicines added.</div> : (
        <table className="table rx-table">
          <thead><tr><th>#</th><th>Medicine</th><th>Dose</th><th>Frequency</th><th>When</th><th>Duration</th><th>Qty</th><th>Instructions</th><th></th></tr></thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i}>
                <td className="muted">{i + 1}</td>
                <td><input value={it.medicine_name} onChange={(e) => update(i, "medicine_name", e.target.value)} aria-label="Medicine name" /><span className="muted small">{it.form}</span></td>
                <td><input value={it.dose} onChange={(e) => update(i, "dose", e.target.value)} aria-label="Dose" /></td>
                <td><input list="rx-freqs" value={it.frequency} onChange={(e) => update(i, "frequency", e.target.value)} aria-label="Frequency" /></td>
                <td><select value={it.timing} onChange={(e) => update(i, "timing", e.target.value)} aria-label="Timing">{TIMINGS.map((t) => <option key={t} value={t}>{t || "—"}</option>)}</select></td>
                <td><input value={it.duration} onChange={(e) => update(i, "duration", e.target.value)} aria-label="Duration" /></td>
                <td><input value={it.quantity} onChange={(e) => update(i, "quantity", e.target.value)} aria-label="Quantity" /></td>
                <td><input value={it.instructions} onChange={(e) => update(i, "instructions", e.target.value)} aria-label="Instructions" /></td>
                <td className="nowrap">
                  <button type="button" className="icon-btn" onClick={() => move(i, -1)} aria-label="Move up">↑</button>
                  <button type="button" className="icon-btn" onClick={() => move(i, 1)} aria-label="Move down">↓</button>
                  <button type="button" className="icon-btn danger" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="Remove">×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <datalist id="rx-freqs">{FREQS.map((f) => <option key={f} value={f} />)}</datalist>
    </div>
  );
}
