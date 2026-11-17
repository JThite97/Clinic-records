import { api } from "../api";
import { ErrorBox, Spinner } from "../components/ui";
import { fmtDateTime } from "../format";
import { useAsync } from "../hooks";

interface E { id: number; ts: string; username: string; action: string; entity: string; entity_id: string; details: Record<string, unknown> }

export default function Audit() {
  const { data, error } = useAsync(() => api.get<{ entries: E[]; chain_ok: boolean; first_bad_id: number | null }>("/api/audit?limit=500"), []);
  return (
    <div className="page">
      <header className="page-head"><div><h1>Audit log</h1><p className="muted">Every change, login and backup. Entries are hash-chained, so tampering is detectable.</p></div></header>
      <ErrorBox error={error} />
      {!data && !error && <Spinner />}
      {data && <div className={`banner ${data.chain_ok ? "ok" : "warn"}`}>{data.chain_ok ? "Integrity check passed: the audit trail is intact." : `Integrity check FAILED at entry #${data.first_bad_id}.`}</div>}
      {data && (
        <div className="card flush">
          <table className="table">
            <thead><tr><th>#</th><th>When</th><th>User</th><th>Action</th><th>Details</th></tr></thead>
            <tbody>{data.entries.map((e) => (
              <tr key={e.id}><td className="muted">{e.id}</td><td className="nowrap">{fmtDateTime(e.ts)}</td><td>{e.username}</td><td className="mono small">{e.action}</td>
                <td className="small muted">{Object.entries(e.details).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ")}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
