import { useState } from "react";
import { api } from "../api";
import { ErrorBox, Field } from "../components/ui";
import type { User } from "../types";

export default function Setup({ onDone }: { onDone: (token: string, u: User) => void }) {
  const [mode, setMode] = useState<"new" | "restore">("new");
  const [f, setF] = useState({ clinic_name: "", doctor_name: "", username: "", password: "", confirm: "" });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (mode === "new" && f.password !== f.confirm) { setError("Passwords do not match"); return; }
    setBusy(true);
    try {
      let r: { token: string; user: User };
      if (mode === "new") {
        r = await api.post("/api/system/setup", { clinic_name: f.clinic_name, doctor_name: f.doctor_name, full_name: f.doctor_name, username: f.username, password: f.password });
      } else {
        if (!file) throw new Error("Choose the backup file");
        const fd = new FormData();
        fd.append("file", file);
        fd.append("username", f.username);
        fd.append("password", f.password);
        r = await api.upload("/api/system/restore-setup", fd);
      }
      onDone(r.token, r.user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-screen">
      <form className="card narrow" onSubmit={submit}>
        <div className="brand big"><img src="/icon.svg" alt="" width={40} height={40} /><div><b>Clinic Records</b><span>First-time setup</span></div></div>
        <div className="seg">
          <button type="button" className={mode === "new" ? "on" : ""} onClick={() => setMode("new")}>New clinic</button>
          <button type="button" className={mode === "restore" ? "on" : ""} onClick={() => setMode("restore")}>Restore a backup</button>
        </div>
        {mode === "new" ? (
          <>
            <Field label="Clinic name"><input required value={f.clinic_name} onChange={set("clinic_name")} autoFocus /></Field>
            <Field label="Doctor's name"><input value={f.doctor_name} onChange={set("doctor_name")} placeholder="Dr. …" /></Field>
            <Field label="Username"><input required minLength={2} value={f.username} onChange={set("username")} autoComplete="username" /></Field>
            <Field label="Password" hint="At least 8 characters. This password also unlocks the encrypted records."><input required minLength={8} type="password" value={f.password} onChange={set("password")} autoComplete="new-password" /></Field>
            <Field label="Confirm password"><input required type="password" value={f.confirm} onChange={set("confirm")} autoComplete="new-password" /></Field>
            <p className="warn-note">Keep this password safe. All patient data is encrypted with it; if every administrator password is lost, the records cannot be recovered.</p>
          </>
        ) : (
          <>
            <Field label="Backup file (.crbak)"><input type="file" accept=".crbak" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
            <Field label="Username used on the old computer"><input required value={f.username} onChange={set("username")} /></Field>
            <Field label="Password"><input required type="password" value={f.password} onChange={set("password")} /></Field>
          </>
        )}
        <ErrorBox error={error} />
        <button className="btn primary block" disabled={busy}>{busy ? "Please wait…" : mode === "new" ? "Create clinic" : "Restore and open"}</button>
      </form>
    </div>
  );
}
