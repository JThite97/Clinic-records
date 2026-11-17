import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import PrescriptionBuilder from "../components/PrescriptionBuilder";
import { ErrorBox, Field, Spinner, useToast } from "../components/ui";
import VisitCard from "../components/VisitCard";
import { ageSex, fmtDate, toLocalInput } from "../format";
import { openServerFile } from "../native";
import type { Patient, RxItem, Visit } from "../types";

type Form = {
  visit_date: string; chief_complaint: string; history: string; examination: string; diagnosis: string; advice: string; notes: string;
  follow_up_date: string; bp_systolic: string; bp_diastolic: string; pulse: string; temperature: string; weight: string; height: string;
  spo2: string; resp_rate: string;
};
const NUMS = ["bp_systolic", "bp_diastolic", "pulse", "temperature", "weight", "height", "spo2", "resp_rate"] as const;

const blank = (): Form => ({ visit_date: toLocalInput(), chief_complaint: "", history: "", examination: "", diagnosis: "", advice: "", notes: "",
  follow_up_date: "", bp_systolic: "", bp_diastolic: "", pulse: "", temperature: "", weight: "", height: "", spo2: "", resp_rate: "" });

function fromVisit(v: Visit): Form {
  const f = blank();
  (Object.keys(f) as (keyof Form)[]).forEach((k) => { const val = (v as any)[k]; f[k] = val == null ? "" : String(val); });
  f.visit_date = toLocalInput(new Date(v.visit_date));
  return f;
}

/** Dual pane: consultation editor on the left, earlier visits on the right.
 *  Route /patients/:id/visit creates a visit; /visits/:id/amend amends one. */
export default function VisitWorkspace({ mode = "new" }: { mode?: "new" | "amend" }) {
  const params = useParams();
  const amendId = mode === "amend" ? params.id ?? null : null;
  const nav = useNavigate();
  const toast = useToast();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [history, setHistory] = useState<Visit[]>([]);
  const [idx, setIdx] = useState(0);
  const [target, setTarget] = useState<Visit | null>(null);
  const [f, setF] = useState<Form>(blank);
  const [items, setItems] = useState<RxItem[]>([]);
  const [rxNotes, setRxNotes] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        let pid = params.id!;
        let rootId: string | null = null;
        if (amendId) {
          const v = await api.get<Visit>(`/api/visits/${amendId}`);
          setTarget(v);
          setF(fromVisit(v));
          setItems(v.prescription.items);
          setRxNotes(v.prescription.notes);
          pid = v.patient_id;
          rootId = v.root_id;
        }
        const [p, vs] = await Promise.all([api.get<Patient>(`/api/patients/${pid}`), api.get<Visit[]>(`/api/patients/${pid}/visits`)]);
        setPatient(p);
        setHistory(rootId ? vs.filter((x) => x.root_id !== rootId) : vs);
      } catch (e: any) { setError(e.message); }
    })();
  }, [params.id, amendId]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { setF((x) => ({ ...x, [k]: e.target.value })); setDirty(true); };
  const prev = history[idx] || null;

  const save = useCallback(async (print: boolean) => {
    if (!patient) return;
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { ...f, follow_up_date: f.follow_up_date || null, visit_date: f.visit_date || null, prescription: { items, notes: rxNotes } };
    NUMS.forEach((k) => { body[k] = f[k] === "" ? null : Number(f[k]); });
    try {
      let v: Visit;
      if (target) v = await api.post<Visit>(`/api/visits/${target.id}/amend`, { ...body, reason });
      else v = await api.post<Visit>(`/api/patients/${patient.id}/visits`, body);
      setDirty(false);
      toast(target ? "Amendment saved. The original is kept in the history." : "Visit saved");
      if (print) await openServerFile(`/api/visits/${v.id}/prescription.pdf/export`, `/api/visits/${v.id}/prescription.pdf`);
      nav(`/visits/${v.id}`, { replace: true });
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }, [f, items, rxNotes, patient, target, reason, nav, toast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); if (!busy) save(false); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, busy]);

  const bmi = useMemo(() => {
    const w = parseFloat(f.weight), h = parseFloat(f.height);
    return w > 0 && h > 0 ? (w / ((h / 100) ** 2)).toFixed(1) : "";
  }, [f.weight, f.height]);

  if (error && !patient) return <div className="page"><ErrorBox error={error} /></div>;
  if (!patient) return <div className="page"><Spinner /></div>;

  return (
    <div className="page workspace">
      <header className="page-head">
        <div>
          <h1>{target ? "Amend visit" : "New visit"} · {patient.full_name}</h1>
          <div className="muted">{patient.patient_number} · {ageSex(patient)}{patient.phone ? ` · ${patient.phone}` : ""}</div>
          {patient.allergies && <div className="allergy">Allergies: {patient.allergies}</div>}
        </div>
        <div className="row gap">
          <Link className="btn" to={target ? `/visits/${target.id}` : `/patients/${patient.id}`}>Cancel</Link>
          <button className="btn" disabled={busy} onClick={() => save(false)}>Save <kbd>Ctrl S</kbd></button>
          <button className="btn primary" disabled={busy} onClick={() => save(true)}>Save &amp; print</button>
        </div>
      </header>
      {target && (
        <div className="banner">
          You are amending the visit of {fmtDate(target.visit_date)}. The current version will be kept unchanged in the history.
          <Field label={target.locked ? "Reason for amendment (required)" : "Reason for amendment"}><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Lab report received, correcting dose" /></Field>
        </div>
      )}
      <ErrorBox error={error} />
      <div className="split">
        <section className="card editor">
          <div className="vitals-grid">
            <Field label="Date & time"><input type="datetime-local" value={f.visit_date} onChange={set("visit_date")} /></Field>
            <Field label="BP (mmHg)"><div className="row gap-s"><input className="w-xs" inputMode="numeric" placeholder="120" value={f.bp_systolic} onChange={set("bp_systolic")} aria-label="Systolic" /><span>/</span><input className="w-xs" inputMode="numeric" placeholder="80" value={f.bp_diastolic} onChange={set("bp_diastolic")} aria-label="Diastolic" /></div></Field>
            <Field label="Pulse /min"><input inputMode="numeric" value={f.pulse} onChange={set("pulse")} /></Field>
            <Field label="Temp °C"><input inputMode="decimal" value={f.temperature} onChange={set("temperature")} /></Field>
            <Field label="SpO2 %"><input inputMode="numeric" value={f.spo2} onChange={set("spo2")} /></Field>
            <Field label="Resp. rate"><input inputMode="numeric" value={f.resp_rate} onChange={set("resp_rate")} /></Field>
            <Field label="Weight kg"><input inputMode="decimal" value={f.weight} onChange={set("weight")} /></Field>
            <Field label="Height cm" hint={bmi ? `BMI ${bmi}` : undefined}><input inputMode="decimal" value={f.height} onChange={set("height")} /></Field>
          </div>
          <Field label="Chief complaints"><textarea rows={2} value={f.chief_complaint} onChange={set("chief_complaint")} autoFocus={!target} /></Field>
          <Field label="History"><textarea rows={2} value={f.history} onChange={set("history")} /></Field>
          <Field label="Examination"><textarea rows={2} value={f.examination} onChange={set("examination")} /></Field>
          <Field label="Diagnosis"><input value={f.diagnosis} onChange={set("diagnosis")} /></Field>
          <div className="row between center"><h3>Prescription</h3>
            {prev && prev.prescription.items.length > 0 && (
              <button type="button" className="btn small" onClick={() => { setItems([...items, ...prev.prescription.items.map((i) => ({ ...i }))]); setDirty(true); toast(`Copied ${prev.prescription.items.length} medicines from ${fmtDate(prev.visit_date)}`); }}>
                Copy from {fmtDate(prev.visit_date)}
              </button>
            )}
          </div>
          <PrescriptionBuilder items={items} onChange={(x) => { setItems(x); setDirty(true); }} />
          <Field label="Prescription notes"><input value={rxNotes} onChange={(e) => { setRxNotes(e.target.value); setDirty(true); }} /></Field>
          <Field label="Advice"><textarea rows={2} value={f.advice} onChange={set("advice")} /></Field>
          <div className="row gap">
            <Field label="Follow-up date"><input type="date" value={f.follow_up_date} onChange={set("follow_up_date")} /></Field>
            <div className="row gap-s quick">
              {[3, 7, 14, 30].map((d) => <button type="button" key={d} className="btn small ghost" onClick={() => { const x = new Date(); x.setDate(x.getDate() + d); setF((o) => ({ ...o, follow_up_date: toLocalInput(x).slice(0, 10) })); setDirty(true); }}>+{d}d</button>)}
            </div>
          </div>
          <Field label="Private notes (not printed)"><textarea rows={2} value={f.notes} onChange={set("notes")} /></Field>
        </section>

        <aside className="card history-pane">
          <div className="row between center">
            <h3>{target ? "Version being amended" : "Previous visit"}</h3>
            {!target && history.length > 1 && (
              <div className="row gap-s">
                <button className="icon-btn" disabled={idx >= history.length - 1} onClick={() => setIdx(idx + 1)} aria-label="Older">‹</button>
                <span className="muted small">{idx + 1} / {history.length}</span>
                <button className="icon-btn" disabled={idx === 0} onClick={() => setIdx(idx - 1)} aria-label="Newer">›</button>
              </div>
            )}
          </div>
          {target ? <><div className="muted small">{fmtDate(target.visit_date)}</div><VisitCard v={target} compact /></> :
            prev ? <><div className="row between"><b>{fmtDate(prev.visit_date)}</b><Link className="small" to={`/visits/${prev.id}`}>Open</Link></div><VisitCard v={prev} compact /></> :
              <div className="empty">First visit for this patient.</div>}
        </aside>
      </div>
    </div>
  );
}
