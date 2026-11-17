import { useState } from "react";
import { api } from "../api";
import { ErrorBox, Field } from "../components/ui";
import type { User } from "../types";

export default function Login({ clinicName, onDone }: { clinicName: string | null; onDone: (t: string, u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ token: string; user: User }>("/api/auth/login", { username, password });
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
        <div className="brand big"><img src="/icon.svg" alt="" width={40} height={40} /><div><b>{clinicName || "Clinic Records"}</b><span>Records are encrypted. Log in to open them.</span></div></div>
        <Field label="Username"><input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" required /></Field>
        <Field label="Password"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></Field>
        <ErrorBox error={error} />
        <button className="btn primary block" disabled={busy}>{busy ? "Unlocking…" : "Log in"}</button>
      </form>
    </div>
  );
}
