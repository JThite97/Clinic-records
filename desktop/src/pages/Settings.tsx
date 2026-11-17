import { useEffect, useState } from "react";
import { api, url } from "../api";
import { useSession } from "../App";
import { ErrorBox, Field, Modal, useToast } from "../components/ui";
import { useAsync } from "../hooks";
import type { Clinic, User } from "../types";

interface S { clinic: Clinic; runtime: { network_access: boolean; backup_retention: number; auto_backup_hours: number; port: number }; paths: { home: string; backups: string; logs: string } }

export default function Settings() {
  const { user } = useSession();
  const isAdmin = user.role === "admin";
  const toast = useToast();
  const { data, error, reload } = useAsync(() => api.get<S>("/api/settings"), []);
  const [clinic, setClinic] = useState<Clinic | null>(null);
  const [rt, setRt] = useState<S["runtime"] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [imgV, setImgV] = useState(0);

  useEffect(() => { if (data) { setClinic(data.clinic); setRt(data.runtime); } }, [data]);
  const setC = (k: keyof Clinic) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => clinic && setClinic({ ...clinic, [k]: e.target.value });

  async function saveClinic(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try { await api.put("/api/settings/clinic", clinic); toast("Clinic details saved"); reload(); } catch (x: any) { setErr(x.message); }
  }

  async function saveRuntime() {
    try {
      const r = await api.put<{ restart_required: boolean }>("/api/settings/runtime", rt);
      toast(r.restart_required ? "Saved. Restart Clinic Records for the network change to apply." : "Saved");
      reload();
    } catch (x: any) { toast(x.message, "error"); }
  }

  async function uploadImg(kind: "logo" | "signature", f: File | undefined) {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try { await api.upload(`/api/settings/asset/${kind}`, fd); toast(`${kind === "logo" ? "Logo" : "Signature"} updated`); setImgV((v) => v + 1); reload(); } catch (x: any) { toast(x.message, "error"); }
  }

  async function removeImg(kind: "logo" | "signature") {
    await api.del(`/api/settings/asset/${kind}`);
    reload();
  }

  return (
    <div className="page">
      <header className="page-head"><h1>Settings</h1></header>
      <ErrorBox error={error} />
      {clinic && (
        <form className="card form-grid" onSubmit={saveClinic}>
          <h2 className="wide">Clinic & letterhead</h2>
          <fieldset disabled={!isAdmin} className="contents">
            <Field label="Clinic name"><input value={clinic.clinic_name} onChange={setC("clinic_name")} /></Field>
            <Field label="Phone"><input value={clinic.clinic_phone} onChange={setC("clinic_phone")} /></Field>
            <Field label="Address" wide><textarea rows={2} value={clinic.clinic_address} onChange={setC("clinic_address")} /></Field>
            <Field label="Email"><input value={clinic.clinic_email} onChange={setC("clinic_email")} /></Field>
            <Field label="Doctor's name"><input value={clinic.doctor_name} onChange={setC("doctor_name")} /></Field>
            <Field label="Qualifications"><input value={clinic.doctor_qualifications} onChange={setC("doctor_qualifications")} placeholder="MBBS, MD" /></Field>
            <Field label="Registration number"><input value={clinic.doctor_registration} onChange={setC("doctor_registration")} /></Field>
            <Field label="Footer line"><input value={clinic.footer_note} onChange={setC("footer_note")} placeholder="e.g. Not valid for medico-legal purposes" /></Field>
            <Field label="Paper size"><select value={clinic.paper_size} onChange={setC("paper_size")}><option>A4</option><option>Letter</option></select></Field>
          </fieldset>
          <div className="wide row gap wrap">
            {(["logo", "signature"] as const).map((k) => (
              <div key={k} className="asset">
                <span className="field-label">{k === "logo" ? "Clinic logo" : "Signature image"}</span>
                <div className="asset-img">{clinic[`${k}_path`] ? <img src={url(`/api/settings/asset/${k}?v=${imgV}`, true)} alt={k} /> : <span className="muted small">None</span>}</div>
                {isAdmin && <div className="row gap-s"><label className="btn small">Choose…<input type="file" accept="image/png,image/jpeg" hidden onChange={(e) => uploadImg(k, e.target.files?.[0])} /></label>{clinic[`${k}_path`] && <button type="button" className="btn small ghost" onClick={() => removeImg(k)}>Remove</button>}</div>}
              </div>
            ))}
          </div>
          <div className="wide"><ErrorBox error={err} /></div>
          {isAdmin && <div className="wide row end"><button className="btn primary">Save clinic details</button></div>}
        </form>
      )}

      {rt && isAdmin && (
        <section className="card">
          <h2>Backups & phone access</h2>
          <div className="form-grid">
            <Field label="Automatic backup every (hours)" hint="0 turns automatic backups off"><input type="number" min={0} value={rt.auto_backup_hours} onChange={(e) => setRt({ ...rt, auto_backup_hours: Number(e.target.value) })} /></Field>
            <Field label="Backups to keep"><input type="number" min={1} max={365} value={rt.backup_retention} onChange={(e) => setRt({ ...rt, backup_retention: Number(e.target.value) })} /></Field>
            <label className="check wide"><input type="checkbox" checked={rt.network_access} onChange={(e) => setRt({ ...rt, network_access: e.target.checked })} />
              Allow phones on the private network (Tailscale) to connect: read-only web view at <code>http://&lt;this-computer&gt;:{rt.port}/mobile</code> and phone sync. Needs a restart.</label>
          </div>
          <div className="row end"><button className="btn primary" onClick={saveRuntime}>Save</button></div>
          {data && <p className="muted small">Data folder: <code>{data.paths.home}</code> · Log file: <code>{data.paths.logs}</code></p>}
        </section>
      )}

      <PasswordCard />
      {isAdmin && <Users />}
    </div>
  );
}

function PasswordCard() {
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [n1, setN1] = useState("");
  const [n2, setN2] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (n1 !== n2) { setErr("New passwords do not match"); return; }
    try { await api.post("/api/auth/password", { current_password: cur, new_password: n1 }); toast("Password changed"); setCur(""); setN1(""); setN2(""); setErr(null); }
    catch (x: any) { setErr(x.message); }
  }
  return (
    <form className="card form-grid" onSubmit={save}>
      <h2 className="wide">My password</h2>
      <Field label="Current password"><input type="password" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
      <Field label="New password"><input type="password" minLength={8} value={n1} onChange={(e) => setN1(e.target.value)} required /></Field>
      <Field label="Repeat new password"><input type="password" value={n2} onChange={(e) => setN2(e.target.value)} required /></Field>
      <div className="wide"><ErrorBox error={err} /></div>
      <div className="wide row end"><button className="btn">Change password</button></div>
    </form>
  );
}

function Users() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api.get<(User & { active: boolean })[]>("/api/users"), []);
  const [add, setAdd] = useState(false);
  const [reset, setReset] = useState<User | null>(null);
  const [f, setF] = useState({ username: "", full_name: "", password: "", role: "doctor" });
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function create() {
    setErr(null);
    try { await api.post("/api/users", f); toast("User added"); setAdd(false); setF({ username: "", full_name: "", password: "", role: "doctor" }); reload(); } catch (x: any) { setErr(x.message); }
  }
  async function doReset() {
    if (!reset) return;
    setErr(null);
    try { await api.post(`/api/users/${reset.id}/password`, { new_password: pw }); toast("Password reset"); setReset(null); setPw(""); } catch (x: any) { setErr(x.message); }
  }
  async function toggle(u: User & { active: boolean }) {
    try { await api.post(`/api/users/${u.id}/active/${!u.active}`); if (!u.active) toast("Re-activated. Set a new password for this user."); reload(); } catch (x: any) { toast(x.message, "error"); }
  }

  return (
    <section className="card">
      <div className="row between center"><h2>Users</h2><button className="btn" onClick={() => { setAdd(true); setErr(null); }}>Add user</button></div>
      <p className="muted small">Doctors record visits and prescriptions. Staff can register patients and add documents. Administrators also manage users, backups and settings.</p>
      <table className="table">
        <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Status</th><th></th></tr></thead>
        <tbody>{data?.map((u) => (
          <tr key={u.id} className={u.active ? "" : "dim"}><td className="mono">{u.username}</td><td>{u.full_name}</td><td>{u.role}</td><td>{u.active ? "Active" : "Disabled"}</td>
            <td className="nowrap"><button className="link" onClick={() => { setReset(u); setErr(null); }}>Reset password</button> <button className="link" onClick={() => toggle(u)}>{u.active ? "Disable" : "Enable"}</button></td></tr>
        ))}</tbody>
      </table>
      {add && (
        <Modal title="Add user" onClose={() => setAdd(false)} footer={<><button className="btn" onClick={() => setAdd(false)}>Cancel</button><button className="btn primary" onClick={create}>Add</button></>}>
          <div className="form-grid">
            <Field label="Username"><input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoFocus /></Field>
            <Field label="Full name"><input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
            <Field label="Password"><input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
            <Field label="Role"><select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="doctor">Doctor</option><option value="staff">Staff</option><option value="admin">Administrator</option></select></Field>
          </div>
          <ErrorBox error={err} />
        </Modal>
      )}
      {reset && (
        <Modal title={`Reset password · ${reset.username}`} onClose={() => setReset(null)} footer={<><button className="btn" onClick={() => setReset(null)}>Cancel</button><button className="btn primary" onClick={doReset}>Set password</button></>}>
          <Field label="New password"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus /></Field>
          <ErrorBox error={err} />
        </Modal>
      )}
    </section>
  );
}
