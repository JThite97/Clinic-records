import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useSession } from "../App";
import { ErrorBox, Spinner } from "../components/ui";
import VisitCard from "../components/VisitCard";
import { fmtDate, fmtDateTime } from "../format";
import { useAsync } from "../hooks";
import { openServerFile } from "../native";
import type { Patient, Visit } from "../types";

export default function VisitView() {
  const { id = "" } = useParams();
  const { user } = useSession();
  const v = useAsync(() => api.get<Visit>(`/api/visits/${id}`), [id]);
  const hist = useAsync(() => api.get<Visit[]>(`/api/visits/${id}/history`), [id]);
  const p = useAsync(() => (v.data ? api.get<Patient>(`/api/patients/${v.data.patient_id}`) : Promise.resolve(null)), [v.data?.patient_id]);

  if (v.error) return <div className="page"><ErrorBox error={v.error} /></div>;
  if (!v.data) return <div className="page"><Spinner /></div>;
  const visit = v.data;
  const current = hist.data?.find((h) => !h.superseded);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="crumbs">{p.data && <Link to={`/patients/${p.data.id}`}>{p.data.full_name} · {p.data.patient_number}</Link>}</div>
          <h1>Visit · {fmtDate(visit.visit_date)}</h1>
          <div className="muted small">Recorded by {visit.created_by || "—"} on {fmtDateTime(visit.created_at)}{visit.device_id !== "desktop" ? " (from phone)" : ""}</div>
          {p.data?.allergies && <div className="allergy">Allergies: {p.data.allergies}</div>}
        </div>
        <div className="row gap">
          {user.role !== "staff" && !visit.superseded && <Link className="btn" to={`/visits/${visit.id}/amend`}>Amend</Link>}
          <button className="btn primary" onClick={() => openServerFile(`/api/visits/${visit.id}/prescription.pdf/export`, `/api/visits/${visit.id}/prescription.pdf`)}>Print prescription</button>
        </div>
      </header>
      {visit.superseded && current && <div className="banner warn">This is an older version. <Link to={`/visits/${current.id}`}>Open the current version</Link></div>}
      {visit.amends_id && <div className="banner">Amended{visit.amendment_reason ? `: ${visit.amendment_reason}` : ""}</div>}
      <div className="card"><VisitCard v={visit} /></div>
      {hist.data && hist.data.length > 1 && (
        <section className="card">
          <h2>Version history</h2>
          <p className="muted small">Saved visits are never overwritten. Every amendment is a new version; earlier versions stay here for reference.</p>
          <table className="table">
            <thead><tr><th>Saved</th><th>By</th><th>Reason</th><th>Diagnosis</th><th></th></tr></thead>
            <tbody>{hist.data.map((h) => (
              <tr key={h.id} className={h.id === visit.id ? "sel" : ""}>
                <td>{fmtDateTime(h.created_at)}</td><td>{h.created_by}</td><td>{h.amendment_reason || (h.amends_id ? "—" : "Original")}</td><td>{h.diagnosis}</td>
                <td>{h.id !== visit.id && <Link to={`/visits/${h.id}`}>View</Link>}{!h.superseded && <span className="pill ok">current</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        </section>
      )}
    </div>
  );
}
