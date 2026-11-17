import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, auth, setAuthLostHandler } from "./api";
import { Spinner, ToastProvider } from "./components/ui";
import type { User } from "./types";
import Setup from "./pages/Setup";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Patients from "./pages/Patients";
import PatientForm from "./pages/PatientForm";
import PatientDetail from "./pages/PatientDetail";
import VisitWorkspace from "./pages/VisitWorkspace";
import VisitView from "./pages/VisitView";
import Medicines from "./pages/Medicines";
import Backups from "./pages/Backups";
import Settings from "./pages/Settings";
import Sync from "./pages/Sync";
import Audit from "./pages/Audit";

interface Status { initialized: boolean; unlocked: boolean; clinic_name: string | null; version: string }

interface Session { user: User; clinicName: string; logout: () => Promise<void>; lock: () => Promise<void> }
const SessionCtx = createContext<Session | null>(null);
export const useSession = () => useContext(SessionCtx)!;

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(auth.user());
  const reached = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const s = await api.get<Status>("/api/system/status");
      setStatus(s);
      setError(null);
      reached.current = true;
      if (!s.unlocked) { auth.clear(); setUser(null); }
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    setAuthLostHandler(() => { setUser(null); refresh(); });
    let tries = 0;
    refresh();
    // The server may still be starting inside the desktop shell: retry until it answers.
    const t = setInterval(() => { if (!reached.current && tries++ < 60) refresh(); }, 1000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => { if (status) document.title = status.clinic_name ? `${status.clinic_name} · Clinic Records` : "Clinic Records"; }, [status]);

  const onLogin = (token: string, u: User) => { auth.set(token, u); setUser(u); refresh(); };

  if (!status) {
    return <div className="center-screen">{error ? <div className="card narrow"><h2>Starting Clinic Records…</h2><p className="muted">{error}</p><Spinner /></div> : <Spinner />}</div>;
  }
  if (!status.initialized) return <ToastProvider><Setup onDone={onLogin} /></ToastProvider>;
  if (!user || !auth.token()) return <ToastProvider><Login clinicName={status.clinic_name} onDone={onLogin} /></ToastProvider>;

  const session: Session = {
    user,
    clinicName: status.clinic_name || "Clinic Records",
    logout: async () => { try { await api.post("/api/auth/logout"); } catch { /* ignore */ } auth.clear(); setUser(null); },
    lock: async () => { try { await api.post("/api/auth/lock"); } catch { /* ignore */ } auth.clear(); setUser(null); refresh(); },
  };

  return (
    <SessionCtx.Provider value={session}>
      <ToastProvider>
        <Shell />
      </ToastProvider>
    </SessionCtx.Provider>
  );
}

function Shell() {
  const { user, clinicName, logout, lock } = useSession();
  const nav = useNavigate();
  const isAdmin = user.role === "admin";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); nav("/patients?focus=1"); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n" && !e.shiftKey) { e.preventDefault(); nav("/patients/new"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><img src="/icon.svg" alt="" width={28} height={28} /><div><b>{clinicName}</b><span>Clinic Records</span></div></div>
        <nav>
          <NavLink to="/" end>Today</NavLink>
          <NavLink to="/patients">Patients</NavLink>
          <NavLink to="/medicines">Medicines</NavLink>
          <NavLink to="/sync">Phone sync</NavLink>
          {isAdmin && <NavLink to="/backups">Backups</NavLink>}
          {isAdmin && <NavLink to="/audit">Audit log</NavLink>}
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div className="who"><b>{user.full_name || user.username}</b><span>{user.role}</span></div>
          <div className="row gap">
            <button className="btn small ghost" onClick={lock} title="Close the encrypted database">Lock</button>
            <button className="btn small ghost" onClick={logout}>Log out</button>
          </div>
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/patients" element={<Patients />} />
          <Route path="/patients/new" element={<PatientForm />} />
          <Route path="/patients/:id" element={<PatientDetail />} />
          <Route path="/patients/:id/edit" element={<PatientForm />} />
          <Route path="/patients/:id/visit" element={<VisitWorkspace key="new" />} />
          <Route path="/visits/:id" element={<VisitView />} />
          <Route path="/visits/:id/amend" element={<VisitWorkspace mode="amend" />} />
          <Route path="/medicines" element={<Medicines />} />
          <Route path="/sync" element={<Sync />} />
          <Route path="/backups" element={isAdmin ? <Backups /> : <Navigate to="/" />} />
          <Route path="/audit" element={isAdmin ? <Audit /> : <Navigate to="/" />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}
