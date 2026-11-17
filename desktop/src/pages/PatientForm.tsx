import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Field, useToast } from "../components/ui";
import type { Patient } from "../types";

const EMPTY = { full_name: "", sex: "", date_of_birth: "", age_years: "", phone: "", alt_phone: "", email: "", address: "",
  blood_group: "", allergies: "", chronic_conditions: "", notes: "" };
type Form = typeof EMPTY;

export default function PatientForm() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const [f, setF] = useState<Form>(EMPTY);
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.get<Patient>(`/api/patients/${id}`).then((p) => {
      setArchived(p.archived);
      setF({ ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).map((k) => [k, (p as any)[k] ?? ""])) } as Form);
    }).catch((e) => setError(e.message));
  }, [id]);

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { ...f, age_years: f.age_years === "" ? null : Number(f.age_years), date_of_birth: f.date_of_birth || null };
    try {
      const p = id ? await api.put<Patient>(`/api/patients/${id}`, body) : await api.post<Patient>("/api/patients", body);
      toast(id ? "Patient updated" : `Registered ${p.patient_number}`);
      nav(`/patients/${p.id}`, { replace: true });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleArchive() {
    if (!id) return;
    await api.put(`/api/patients/${id}`, { archived: !archived });
    toast(archived ? "Patient restored" : "Patient archived");
    nav(`/patients/${id}`);
  }

  return (
    <div className="page">
      <header className="page-head"><h1>{id ? "Edit patient" : "New patient"}</h1></header>
      <form className="card form-grid" onSubmit={save}>
        <Field label="Full name" wide><input required value={f.full_name} onChange={set("full_name")} autoFocus /></Field>
        <Field label="Sex">
          <select value={f.sex} onChange={set("sex")}><option value="">—</option><option value="M">Male</option><option value="F">Female</option><option value="O">Other</option></select>
        </Field>
        <Field label="Date of birth"><input type="date" value={f.date_of_birth} onChange={set("date_of_birth")} /></Field>
        <Field label="Age (years)" hint="If date of birth is unknown"><input type="number" min={0} max={130} value={f.age_years} onChange={set("age_years")} /></Field>
        <Field label="Blood group">
          <select value={f.blood_group} onChange={set("blood_group")}><option value="">—</option>{["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].map((b) => <option key={b}>{b}</option>)}</select>
        </Field>
        <Field label="Phone"><input type="tel" value={f.phone} onChange={set("phone")} /></Field>
        <Field label="Alternate phone"><input type="tel" value={f.alt_phone} onChange={set("alt_phone")} /></Field>
        <Field label="Email"><input type="email" value={f.email} onChange={set("email")} /></Field>
        <Field label="Address" wide><textarea rows={2} value={f.address} onChange={set("address")} /></Field>
        <Field label="Allergies" wide hint="Shown in red on every screen and printout"><input value={f.allergies} onChange={set("allergies")} placeholder="e.g. Penicillin" /></Field>
        <Field label="Chronic conditions" wide><input value={f.chronic_conditions} onChange={set("chronic_conditions")} placeholder="e.g. Type 2 diabetes, hypertension" /></Field>
        <Field label="Notes" wide><textarea rows={2} value={f.notes} onChange={set("notes")} /></Field>
        <div className="wide"><ErrorBox error={error} /></div>
        <div className="wide row between">
          <div>{id && <button type="button" className="btn ghost" onClick={toggleArchive}>{archived ? "Restore patient" : "Archive patient"}</button>}</div>
          <div className="row gap"><button type="button" className="btn" onClick={() => nav(-1)}>Cancel</button><button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save patient"}</button></div>
        </div>
      </form>
    </div>
  );
}
