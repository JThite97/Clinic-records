import { useState } from "react";
import { api } from "../api";
import { useSession } from "../App";
import { Empty, ErrorBox, useToast } from "../components/ui";
import { fmtDateTime } from "../format";
import { useAsync } from "../hooks";

interface Dev { id: string; name: string; revoked: boolean; created_at: string; last_seen: string | null }
interface C { id: number; entity: string; label: string; field: string; kind: string; kept_value: unknown; other_value: unknown; kept_device: string; other_device: string; created_at: string }

export default function Sync() {
  const { user } = useSession();
  const isAdmin = user.role === "admin";
  const toast = useToast();
  const devs = useAsync(() => (isAdmin ? api.get<Dev[]>("/api/sync/devices") : Promise.resolve([])), [isAdmin]);
  const conflicts = useAsync(() => api.get<C[]>("/api/sync/conflicts"), []);
  const [code, setCode] = useState<{ code: string; addresses: string[]; port: number; network_access: boolean } | null>(null);

  async function newCode() {
    try { setCode(await api.post("/api/sync/pairing-code")); } catch (e: any) { toast(e.message, "error"); }
  }
  async function revoke(d: Dev) {
    await api.post(`/api/sync/devices/${d.id}/revoke`);
    toast(`${d.name} can no longer sync`);
    devs.reload();
  }
  async function resolve(c: C, useOther: boolean) {
    await api.post(`/api/sync/conflicts/${c.id}/resolve`, { use_other: useOther });
    toast("Conflict resolved");
    conflicts.reload();
  }
  const show = (v: unknown) => (v === null || v === undefined || v === "" ? "(empty)" : String(v));

  return (
    <div className="page">
      <header className="page-head"><div><h1>Phone sync</h1><p className="muted">This computer is the hub. A paired phone keeps its own encrypted copy, works with this computer off, and syncs when both are on the private network.</p></div></header>

      <section className="card">
        <h2>Changes to review {conflicts.data && conflicts.data.length > 0 && <span className="pill danger">{conflicts.data.length}</span>}</h2>
        <ErrorBox error={conflicts.error} />
        {conflicts.data?.length === 0 && <Empty>Nothing to review. When the same detail is changed on two devices, the newest change is kept and the other one appears here.</Empty>}
        {conflicts.data?.map((c) => (
          <div key={c.id} className="conflict">
            <div><b>{c.label}</b> <span className="muted small">· {c.kind === "amendment" ? "two amendments of the same visit" : c.field.replace(/_/g, " ")} · {fmtDateTime(c.created_at)}</span></div>
            {c.kind === "field" ? (
              <div className="row gap wrap">
                <div className="choice kept"><span className="muted small">Kept (newest, from {c.kept_device})</span><b>{show(c.kept_value)}</b></div>
                <div className="choice"><span className="muted small">Other value (from {c.other_device})</span><b>{show(c.other_value)}</b></div>
                <div className="row gap-s"><button className="btn small" onClick={() => resolve(c, false)}>Keep current</button><button className="btn small" onClick={() => resolve(c, true)}>Use other value</button></div>
              </div>
            ) : (
              <div className="row gap wrap"><span className="small">Both amendments are saved in the visit's version history; the newer one is current.</span><button className="btn small" onClick={() => resolve(c, false)}>Mark reviewed</button></div>
            )}
          </div>
        ))}
      </section>

      {isAdmin && (
        <section className="card">
          <div className="row between center"><h2>Paired devices</h2><button className="btn primary" onClick={newCode}>Pair a phone</button></div>
          {code && (
            <div className="pair-box">
              <div className="pair-code">{code.code}</div>
              <div className="small">Enter this code in the Clinic Records phone app within 10 minutes. Server: {code.addresses.length ? code.addresses.map((a) => `${a}:${code.port}`).join(", ") : `this computer, port ${code.port}`}</div>
              {!code.network_access && <div className="warn-note">Phone access is turned off. Turn it on in Settings and restart, or the phone cannot reach this computer.</div>}
            </div>
          )}
          {devs.data?.length === 0 && <Empty>No phones paired yet.</Empty>}
          {devs.data && devs.data.length > 0 && (
            <table className="table">
              <thead><tr><th>Device</th><th>Paired</th><th>Last sync</th><th></th></tr></thead>
              <tbody>{devs.data.map((d) => (
                <tr key={d.id} className={d.revoked ? "dim" : ""}><td>{d.name}</td><td>{fmtDateTime(d.created_at)}</td><td>{d.last_seen ? fmtDateTime(d.last_seen) : "Never"}</td>
                  <td>{d.revoked ? "Revoked" : <button className="link danger" onClick={() => revoke(d)}>Revoke</button>}</td></tr>
              ))}</tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}
