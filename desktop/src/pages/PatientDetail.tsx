import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, url } from "../api";
import { useSession } from "../App";
import { Empty, ErrorBox, Field, Spinner, useToast } from "../components/ui";
import { ageSex, fmtBytes, fmtDate, vitalsLine } from "../format";
import { useAsync } from "../hooks";
import { openDocument, openServerFile } from "../native";
import type { DocumentRec, Patient, Visit } from "../types";

export default function PatientDetail() {
  const { id = "" } = useParams();
  const { user } = useSession();
  const nav = useNavigate();
  const [tab, setTab] = useState<"visits" | "documents">("visits");
  const p = useAsync(() => api.get<Patient>(`/api/patients/${id}`), [id]);
  const visits = useAsync(() => api.get<Visit[]>(`/api/patients/${id}/visits`), [id]);
  const docs = useAsync(() => api.get<DocumentRec[]>(`/api/patients/${id}/documents`), [id]);
  const canWriteVisit = user.role !== "staff";

  if (p.error) return <div className="page"><ErrorBox error={p.error} /></div>;
  if (!p.data) return <div className="page"><Spinner /></div>;
  const pt = p.data;

  return (
    <div className="page">
      <header className="patient-head card">
        <div>
          <div className="row gap center"><h1>{pt.full_name}</h1><span className="pill mono">{pt.patient_number}</span>{pt.archived && <span className="pill muted-pill">archived</span>}</div>
          <div className="muted">{[ageSex(pt), pt.blood_group && `Blood ${pt.blood_group}`, pt.phone].filter(Boolean).join(" · ")}</div>
          {pt.allergies && <div className="allergy">Allergies: {pt.allergies}</div>}
          {pt.chronic_conditions && <div className="small"><span className="muted">Chronic:</span> {pt.chronic_conditions}</div>}
        </div>
        <div className="row gap wrap">
          <Link className="btn" to={`/patients/${id}/edit`}>Edit details</Link>
          <button className="btn" onClick={() => openServerFile(`/api/patients/${id}/record.pdf/export`, `/api/patients/${id}/record.pdf`)}>Print record</button>
          {canWriteVisit && <button className="btn primary" onClick={() => nav(`/patients/${id}/visit`)}>New visit</button>}
        </div>
      </header>

      <div className="tabs">
        <button className={tab === "visits" ? "on" : ""} onClick={() => setTab("visits")}>Visits ({visits.data?.length ?? "…"})</button>
        <button className={tab === "documents" ? "on" : ""} onClick={() => setTab("documents")}>Documents ({docs.data?.length ?? "…"})</button>
      </div>

      {tab === "visits" && (
        <div>
          <ErrorBox error={visits.error} />
          {visits.data?.length === 0 && <div className="card"><Empty>No visits yet.{canWriteVisit && <> <Link to={`/patients/${id}/visit`}>Record the first visit</Link></>}</Empty></div>}
          <div className="timeline">
            {visits.data?.map((v) => (
              <Link key={v.id} to={`/visits/${v.id}`} className="card visit-card">
                <div className="row between"><b>{fmtDate(v.visit_date)}</b><span className="row gap">{v.amends_id && <span className="pill">amended</span>}{v.locked ? <span className="pill muted-pill">locked</span> : <span className="pill ok">latest</span>}</span></div>
                {v.chief_complaint && <div><span className="muted">Complaint:</span> {v.chief_complaint}</div>}
                {v.diagnosis && <div><span className="muted">Diagnosis:</span> <b>{v.diagnosis}</b></div>}
                {vitalsLine(v) && <div className="small muted">{vitalsLine(v)}</div>}
                {v.prescription.items.length > 0 && <div className="small">Rx: {v.prescription.items.map((i) => i.medicine_name).join(", ")}</div>}
              </Link>
            ))}
          </div>
        </div>
      )}

      {tab === "documents" && <Documents patientId={id} docs={docs.data} error={docs.error} reload={docs.reload} />}
    </div>
  );
}

function Documents({ patientId, docs, error, reload }: { patientId: string; docs: DocumentRec[] | null; error: string | null; reload: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("lab");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [inputKey, setInputKey] = useState(0);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title);
    fd.append("category", category);
    try {
      await api.upload(`/api/patients/${patientId}/documents`, fd);
      toast("Document stored");
      setFile(null); setTitle(""); setInputKey((k) => k + 1);
      reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function verify(d: DocumentRec) {
    const r = await api.post<{ ok: boolean; reason?: string }>(`/api/documents/${d.id}/verify`);
    toast(r.ok ? "Checksum OK: file is unchanged" : `File check failed${r.reason ? `: ${r.reason}` : ""}`, r.ok ? "ok" : "error");
  }

  async function archive(d: DocumentRec) {
    await api.post(`/api/documents/${d.id}/archive/true`);
    toast("Document archived");
    reload();
  }

  return (
    <div>
      <form className="card row gap wrap end" onSubmit={upload}>
        <Field label="File (PDF, image…)"><input key={inputKey} type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} required /></Field>
        <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. CBC 12 Nov" /></Field>
        <Field label="Type">
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="lab">Lab report</option><option value="imaging">Imaging</option><option value="prescription">Old prescription</option>
            <option value="referral">Referral</option><option value="discharge">Discharge summary</option><option value="other">Other</option>
          </select>
        </Field>
        <button className="btn primary" disabled={busy || !file}>{busy ? "Uploading…" : "Add document"}</button>
      </form>
      <ErrorBox error={err || error} />
      {docs && docs.length === 0 && <div className="card"><Empty>No documents yet.</Empty></div>}
      <div className="doc-grid">
        {docs?.map((d) => (
          <div key={d.id} className="card doc">
            <button className="thumb" onClick={() => openDocument(d.id)} title="Open in default viewer">
              {d.mime_type.startsWith("image/") ? <img src={url(`/api/documents/${d.id}/file`, true)} alt={d.title} loading="lazy" /> : <span className="ext">{d.original_filename.split(".").pop()?.toUpperCase()}</span>}
            </button>
            <b className="ellipsis" title={d.title}>{d.title || d.original_filename}</b>
            <span className="muted small">{d.category} · {fmtDate(d.uploaded_at)} · {fmtBytes(d.size_bytes)}</span>
            <div className="row gap small">
              <button className="link" onClick={() => openDocument(d.id)}>Open</button>
              <button className="link" onClick={() => verify(d)}>Verify</button>
              <button className="link danger" onClick={() => archive(d)}>Archive</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
