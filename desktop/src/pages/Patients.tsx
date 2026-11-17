import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorBox } from "../components/ui";
import { ageSex, fmtDate } from "../format";
import { useAsync, useDebounced } from "../hooks";
import type { Patient } from "../types";

export default function Patients() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  const [archived, setArchived] = useState(false);
  const dq = useDebounced(q, 150);
  const input = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const [sel, setSel] = useState(0);
  const { data, error } = useAsync(() => api.get<Patient[]>(`/api/patients?limit=50&archived=${archived}&q=${encodeURIComponent(dq)}`), [dq, archived]);

  useEffect(() => { input.current?.focus(); }, [params]);
  useEffect(() => { setSel(0); setParams(dq ? { q: dq } : {}, { replace: true }); }, [dq, setParams]);

  const onKey = (e: React.KeyboardEvent) => {
    if (!data?.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, data.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    if (e.key === "Enter") { e.preventDefault(); nav(`/patients/${data[sel].id}`); }
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>Patients</h1>
        <Link className="btn primary" to="/patients/new">New patient</Link>
      </header>
      <div className="search-bar">
        <input ref={input} className="search" placeholder="Search by name, patient ID (P000123) or phone" value={q}
          onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} aria-label="Search patients" />
        <label className="check"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Include archived</label>
      </div>
      <ErrorBox error={error} />
      <div className="card flush">
        {data && data.length === 0 && <Empty>{dq ? <>No patients match “{dq}”. <Link to="/patients/new">Register a new patient</Link></> : "No patients yet."}</Empty>}
        {data && data.length > 0 && (
          <table className="table clickable">
            <thead><tr><th>ID</th><th>Name</th><th>Age / Sex</th><th>Phone</th><th>Updated</th></tr></thead>
            <tbody>
              {data.map((p, i) => (
                <tr key={p.id} className={i === sel ? "sel" : ""} onClick={() => nav(`/patients/${p.id}`)}>
                  <td className="mono">{p.patient_number}</td>
                  <td><b>{p.full_name}</b>{p.archived && <span className="pill muted-pill">archived</span>}{p.allergies && <span className="pill danger" title={p.allergies}>allergy</span>}</td>
                  <td>{ageSex(p)}</td>
                  <td>{p.phone}</td>
                  <td className="muted">{fmtDate(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
