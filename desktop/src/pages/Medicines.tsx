import { useState } from "react";
import { api } from "../api";
import { useSession } from "../App";
import { Empty, ErrorBox, Field, Modal, useToast } from "../components/ui";
import { useAsync, useDebounced } from "../hooks";
import type { Medicine } from "../types";

const EMPTY = { name: "", generic_name: "", form: "Tablet", strength: "", category: "", default_dose: "1 tab", default_frequency: "1-0-1", default_duration: "5 days", default_instructions: "After food" };

export default function Medicines() {
  const { user } = useSession();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [inactive, setInactive] = useState(false);
  const dq = useDebounced(q, 150);
  const { data, error, reload } = useAsync(() => api.get<Medicine[]>(`/api/medicines?limit=200&inactive=${inactive}&q=${encodeURIComponent(dq)}`), [dq, inactive]);
  const [edit, setEdit] = useState<(typeof EMPTY & { id?: string }) | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const canEdit = user.role !== "staff";

  async function save() {
    if (!edit) return;
    setErr(null);
    try {
      if (edit.id) await api.put(`/api/medicines/${edit.id}`, edit);
      else await api.post("/api/medicines", edit);
      toast("Medicine saved");
      setEdit(null);
      reload();
    } catch (e: any) { setErr(e.message); }
  }

  async function toggle(m: Medicine) {
    await api.put(`/api/medicines/${m.id}`, { active: !m.active });
    reload();
  }

  return (
    <div className="page">
      <header className="page-head"><div><h1>Medicine library</h1><p className="muted">Used for autocomplete in prescriptions. Most used medicines come first.</p></div>
        {canEdit && <button className="btn primary" onClick={() => setEdit({ ...EMPTY })}>Add medicine</button>}</header>
      <div className="search-bar">
        <input className="search" placeholder="Search medicines" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> Show hidden</label>
      </div>
      <ErrorBox error={error} />
      <div className="card flush">
        {data?.length === 0 && <Empty>No medicines found.</Empty>}
        {data && data.length > 0 && (
          <table className="table">
            <thead><tr><th>Name</th><th>Form</th><th>Category</th><th>Default</th><th>Used</th><th></th></tr></thead>
            <tbody>{data.map((m) => (
              <tr key={m.id} className={m.active ? "" : "dim"}>
                <td><b>{m.name}</b>{m.is_custom && <span className="pill">custom</span>}<div className="muted small">{m.generic_name}</div></td>
                <td>{m.form}</td><td className="small">{m.category}</td>
                <td className="small">{[m.default_dose, m.default_frequency, m.default_duration].filter(Boolean).join(" · ")}</td>
                <td>{m.usage_count}</td>
                <td className="nowrap">{canEdit && <><button className="link" onClick={() => setEdit({ ...EMPTY, ...m })}>Edit</button> <button className="link" onClick={() => toggle(m)}>{m.active ? "Hide" : "Show"}</button></>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {edit && (
        <Modal title={edit.id ? "Edit medicine" : "Add medicine"} onClose={() => setEdit(null)}
          footer={<><button className="btn" onClick={() => setEdit(null)}>Cancel</button><button className="btn primary" onClick={save}>Save</button></>}>
          <div className="form-grid">
            <Field label="Name (as printed)" wide><input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} autoFocus /></Field>
            <Field label="Generic name"><input value={edit.generic_name} onChange={(e) => setEdit({ ...edit, generic_name: e.target.value })} /></Field>
            <Field label="Form"><input value={edit.form} onChange={(e) => setEdit({ ...edit, form: e.target.value })} /></Field>
            <Field label="Strength"><input value={edit.strength} onChange={(e) => setEdit({ ...edit, strength: e.target.value })} /></Field>
            <Field label="Category"><input value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} /></Field>
            <Field label="Default dose"><input value={edit.default_dose} onChange={(e) => setEdit({ ...edit, default_dose: e.target.value })} /></Field>
            <Field label="Default frequency"><input value={edit.default_frequency} onChange={(e) => setEdit({ ...edit, default_frequency: e.target.value })} /></Field>
            <Field label="Default duration"><input value={edit.default_duration} onChange={(e) => setEdit({ ...edit, default_duration: e.target.value })} /></Field>
            <Field label="Default instructions"><input value={edit.default_instructions} onChange={(e) => setEdit({ ...edit, default_instructions: e.target.value })} /></Field>
          </div>
          <ErrorBox error={err} />
        </Modal>
      )}
    </div>
  );
}
