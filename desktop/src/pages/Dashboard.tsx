import { Link } from "react-router-dom";
import { api } from "../api";
import { useSession } from "../App";
import { Empty, ErrorBox, Spinner } from "../components/ui";
import { fmtDate } from "../format";
import { useAsync } from "../hooks";

interface Dash {
  patients: number; visits: number; last_backup_hours: number | null;
  today: { visit_id: string; visit_date: string; patient_id: string; patient_number: string; full_name: string; diagnosis: string; chief_complaint: string }[];
  follow_ups: { visit_id: string; follow_up_date: string; patient_id: string; patient_number: string; full_name: string; phone: string }[];
}

export default function Dashboard() {
  const { user } = useSession();
  const { data, error, loading } = useAsync(() => api.get<Dash>("/api/dashboard"), []);
  const backupWarn = data && user.role === "admin" && (data.last_backup_hours === null || data.last_backup_hours > 48);
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Today</h1><p className="muted">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</p></div>
        <div className="row gap"><Link className="btn" to="/patients?focus=1">Find patient <kbd>Ctrl K</kbd></Link><Link className="btn primary" to="/patients/new">New patient</Link></div>
      </header>
      <ErrorBox error={error} />
      {loading && !data && <Spinner />}
      {data && (
        <>
          {backupWarn && <div className="banner warn">No backup in the last two days. <Link to="/backups">Back up now</Link></div>}
          <div className="stats">
            <div className="stat"><span>Patients</span><b>{data.patients}</b></div>
            <div className="stat"><span>Visits recorded</span><b>{data.visits}</b></div>
            <div className="stat"><span>Seen today</span><b>{data.today.length}</b></div>
            <div className="stat"><span>Follow-ups this week</span><b>{data.follow_ups.length}</b></div>
          </div>
          <div className="grid2">
            <section className="card">
              <h2>Seen today</h2>
              {data.today.length === 0 ? <Empty>No visits yet today.</Empty> : (
                <ul className="list">
                  {data.today.map((t) => (
                    <li key={t.visit_id}><Link to={`/visits/${t.visit_id}`}>
                      <div className="row between"><b>{t.full_name}</b><span className="muted">{new Date(t.visit_date).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span></div>
                      <div className="muted small">{t.patient_number} · {t.diagnosis || t.chief_complaint || "—"}</div>
                    </Link></li>
                  ))}
                </ul>
              )}
            </section>
            <section className="card">
              <h2>Follow-ups due (7 days)</h2>
              {data.follow_ups.length === 0 ? <Empty>No follow-ups due.</Empty> : (
                <ul className="list">
                  {data.follow_ups.map((f) => (
                    <li key={f.visit_id}><Link to={`/patients/${f.patient_id}`}>
                      <div className="row between"><b>{f.full_name}</b><span className="pill">{fmtDate(f.follow_up_date)}</span></div>
                      <div className="muted small">{f.patient_number} · {f.phone}</div>
                    </Link></li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
