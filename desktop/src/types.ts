export type Role = "admin" | "doctor" | "staff";

export interface User { id: string; username: string; full_name: string; role: Role; }

export interface Patient {
  id: string; patient_number: string | null; full_name: string; sex: string; date_of_birth: string | null;
  age_years: number | null; age: number | null; phone: string; alt_phone: string; email: string; address: string;
  blood_group: string; allergies: string; chronic_conditions: string; notes: string; archived: boolean;
  created_at: string; updated_at: string;
}

export interface RxItem {
  medicine_id?: string | null; medicine_name: string; form: string; strength: string; dose: string;
  frequency: string; timing: string; duration: string; quantity: string; instructions: string;
}

export interface Visit {
  id: string; patient_id: string; root_id: string; amends_id: string | null; amendment_reason: string;
  superseded: boolean; locked: boolean; visit_date: string; chief_complaint: string; history: string;
  examination: string; diagnosis: string; advice: string; notes: string; follow_up_date: string | null;
  bp_systolic: number | null; bp_diastolic: number | null; pulse: number | null; temperature: number | null;
  weight: number | null; height: number | null; spo2: number | null; resp_rate: number | null;
  created_by: string; device_id: string; created_at: string;
  prescription: { id: string | null; notes: string; items: RxItem[] };
}

export interface Medicine {
  id: string; name: string; generic_name: string; form: string; strength: string; category: string;
  default_dose: string; default_frequency: string; default_duration: string; default_instructions: string;
  active: boolean; is_custom: boolean; usage_count: number;
}

export interface DocumentRec {
  id: string; patient_id: string; visit_id: string | null; title: string; category: string; original_filename: string;
  mime_type: string; size_bytes: number; sha256: string; archived: boolean; uploaded_by: string; uploaded_at: string;
}

export interface Clinic {
  clinic_name: string; clinic_address: string; clinic_phone: string; clinic_email: string; doctor_name: string;
  doctor_qualifications: string; doctor_registration: string; footer_note: string; paper_size: string;
  logo_path: string; signature_path: string;
}
