import { useState } from "react";
import { api, url } from "../api";
import { ErrorBox, Field, Modal, useToast } from "../components/ui";
import { fmtBytes, fmtDateTime } from "../format";
import { useAsync } from "../hooks";
import { openFolder } from "../native";

interface B { name: string; size_bytes: number; created_at: string; reason: string }
interface L { backups: B[]; folder: string; retention: number; auto_backup_hours: number }

export default function Backups() {
  const toast = useToast();
  const { data, error, reload } = useAsync(() => api.get<L>("/api/backups"), []);
  const [busy, setBusy] = useState(false);
  const [restore, setRestore] = useState<B | null>(null);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    try {
      const r = await api.post<{ name: string; verify: { ok: boolean } }>("/api/backups");
      toast(r.verify.ok ? "Backup created and verified" : "Backup created but verification failed", r.verify.ok ? "ok" : "error");
      reload();
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }

  async function verify(b: B) {
    const r = await api.post<{ ok: boolean; reason?: string }>(`/api/backups/${encodeURIComponent(b.name)}/verify`);
    toast(r.ok ? "Backup decrypted and every file checked OK" : `Verification failed: ${r.reason}`, r.ok ? "ok" : "error");
  }

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try { await api.upload("/api/backups/upload", fd); toast("Backup file added"); reload(); } catch (x: any) { toast(x.message, "error"); }
    e.target.value = "";
  }

  async function doRestore() {
    if (!restore) return;
    setErr(null);
    setBusy(true);
    try {
      await api.post("/api/backups/restore", { name: restore.name, password: pw });
      toast("Restored. Please log in again.");
      setTimeout(() => location.reload(), 800);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Backups</h1><p className="muted">Encrypted with AES-256. {data && <>Automatic backup every {data.auto_backup_hours} h while the app is open; the newest {data.retention} are kept.</>}</p></div>
        <div className="row gap">
          <label className="btn">Add backup file…<input type="file" accept=".crbak" hidden onChange={upload} /></label>
          <button className="btn primary" disabled={busy} onClick={create}>{busy ? "Working…" : "Back up now"}</button>
        </div>
      </header>
      <ErrorBox error={error} />
      {data && <p className="muted small">Folder: <code>{data.folder}</code> <button className="link" onClick={() => openFolder(data.folder)}>Open</button>. Copy these files to a USB drive or another disk regularly.</p>}
      <div className="card flush">
        <table className="table">
          <thead><tr><th>Created</th><th>Type</th><th>Size</th><th>File</th><th></th></tr></thead>
          <tbody>
            {data?.backups.length === 0 && <tr><td colSpan={5} className="empty">No backups yet.</td></tr>}
            {data?.backups.map((b) => (
              <tr key={b.name}>
                <td>{fmtDateTime(b.created_at)}</td>
                <td><span className={`pill ${b.reason === "pre-restore" ? "muted-pill" : ""}`}>{b.reason}</span></td>
                <td>{fmtBytes(b.size_bytes)}</td>
                <td className="mono small">{b.name}</td>
                <td className="nowrap">
                  <button className="link" onClick={() => verify(b)}>Verify</button>{" "}
                  <a className="link" href={url(`/api/backups/${encodeURIComponent(b.name)}/download`, true)}>Download</a>{" "}
                  <button className="link danger" onClick={() => { setRestore(b); setPw(""); setErr(null); }}>Restore…</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {restore && (
        <Modal title="Restore backup" onClose={() => setRestore(null)}
          footer={<><button className="btn" onClick={() => setRestore(null)}>Cancel</button><button className="btn danger" disabled={busy || !pw} onClick={doRestore}>{busy ? "Restoring…" : "Restore"}</button></>}>
          <p>This replaces all current records and documents with the backup from <b>{fmtDateTime(restore.created_at)}</b>.</p>
          <p className="muted">A safety snapshot of the current data is taken first, so you can undo this from the list.</p>
          <Field label="Your password"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus /></Field>
          <ErrorBox error={err} />
        </Modal>
      )}
    </div>
  );
}
