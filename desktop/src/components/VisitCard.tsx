import { fmtDate, vitalsLine } from "../format";
import type { Visit } from "../types";

export default function VisitCard({ v, compact }: { v: Visit; compact?: boolean }) {
  const rows: [string, string][] = [
    ["Complaints", v.chief_complaint], ["History", v.history], ["Examination", v.examination],
    ["Diagnosis", v.diagnosis], ["Advice", v.advice], ["Notes", v.notes],
  ];
  return (
    <div className={`visit-detail${compact ? " compact" : ""}`}>
      {vitalsLine(v) && <div className="vitals">{vitalsLine(v)}</div>}
      {rows.filter(([, t]) => t).map(([k, t]) => (
        <div key={k} className="kv"><span className="k">{k}</span><div className="v pre">{t}</div></div>
      ))}
      {v.prescription.items.length > 0 && (
        <div className="kv"><span className="k">Prescription</span>
          <table className="table mini">
            <tbody>{v.prescription.items.map((i, n) => (
              <tr key={n}><td><b>{i.medicine_name}</b></td><td>{i.dose}</td><td>{i.frequency}</td><td>{i.timing}</td><td>{i.duration}</td>{!compact && <td>{i.instructions}</td>}</tr>
            ))}</tbody>
          </table>
          {v.prescription.notes && <div className="pre small">{v.prescription.notes}</div>}
        </div>
      )}
      {v.follow_up_date && <div className="kv"><span className="k">Follow-up</span><div className="v">{fmtDate(v.follow_up_date)}</div></div>}
    </div>
  );
}
