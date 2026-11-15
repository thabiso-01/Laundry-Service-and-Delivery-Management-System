// Shapes returned by the backend (see /docs). Only the fields the UI uses.

export type Role = "customer" | "driver" | "business" | "admin";
export type Verification = "pending" | "approved" | "rejected";
export type OrderStatus =
  | "placed" | "accepted" | "declined" | "cancelled" | "collected" | "received"
  | "processing" | "ready" | "out_for_delivery" | "delivered";

export interface Me {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role: Role;
  status: string;
  must_change_password: boolean;
  mfa_enabled: boolean;
  sms_enabled: boolean;
  driver: { verification_status: Verification; rejection_reason: string | null; is_available: boolean } | null;
  business: {
    business_id: string;
    business_name: string;
    business_verification_status: Verification;
    business_rejection_reason: string | null;
    staff_role: "owner" | "manager" | "attendant";
    is_active: boolean;
  } | null;
}

export interface TokenOut {
  access_token: string | null;
  must_change_password: boolean;
  mfa_required: boolean;
  mfa_token: string | null;
}

export interface Service {
  id: string;
  name: string;
  description: string | null;
  category: string;
  pricing_unit: "per_kg" | "per_item" | "per_load";
  price_cents: number;
  min_quantity: number;
  turnaround_hours: number;
  price_display: string;
  is_active?: boolean;
}

export interface LaundrySearchItem {
  id: string;
  business_name: string;
  description: string | null;
  suburb: string | null;
  city: string | null;
  distance_km: number;
  service_count: number;
  from_price_display: string;
  fastest_turnaround_hours: number;
  rating_avg: number | null;
  rating_count: number;
  matching_services: Service[] | null;
}

export interface LaundryDetail {
  id: string;
  business_name: string;
  description: string | null;
  contact_phone: string | null;
  address_line: string | null;
  suburb: string | null;
  city: string | null;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  services: Service[];
  rating_avg: number | null;
  rating_count: number;
}

export interface Line {
  service_id: string;
  service_name: string;
  pricing_unit: string;
  unit_price_cents: number;
  quantity: number;
  line_total_cents: number;
  description: string;
}

export interface Quote {
  items: Line[];
  subtotal_cents: number;
  delivery_fee_cents: number;
  total_cents: number;
  distance_km: number;
  is_estimate: boolean;
  earliest_delivery: string;
  total_display: string;
}

export interface Address {
  address_line: string;
  suburb: string | null;
  city: string;
  province?: string | null;
  postal_code?: string | null;
  latitude: number;
  longitude: number;
}

export interface StatusEvent {
  from_status: OrderStatus | null;
  to_status: OrderStatus;
  note: string | null;
  created_at: string;
  actor_name?: string | null;
  actor_role?: string | null;
}

export interface Handover {
  kind: string;
  method: string;
  created_at: string;
  location_flagged: boolean;
  distance_from_expected_m: number | null;
  incident_reference?: string | null;
}

export interface Seal {
  seal_number: string;
  leg: "collection" | "delivery";
  check_result: string | null;
  recorded_at: string;
}

export interface OrderSummary {
  id: string;
  order_number: string;
  status: OrderStatus;
  business_name: string;
  total_cents: number;
  is_estimate: boolean;
  collection_window_start: string;
  collection_window_end: string;
  delivery_window_start: string;
  delivery_window_end: string;
  created_at: string;
}

export interface Order extends OrderSummary {
  business_id: string;
  items: Line[];
  subtotal_cents: number;
  delivery_fee_cents: number;
  distance_km: number;
  collection_address: Address;
  delivery_address: Address;
  notes: string | null;
  cancelled_reason: string | null;
  declined_reason: string | null;
  history: StatusEvent[];
  driver: { first_name: string; phone: string | null; vehicle_type: string | null; vehicle_registration: string | null; job_kind: string } | null;
  handovers: Handover[];
  seals: Seal[];
  paid_cents: number;
  adjustment_cents: number;
  final_total_cents: number;
  balance_cents: number;
  trips: { job_id: string; kind: "collection" | "delivery"; status: string; driver_first_name: string | null }[];
  // business view only
  customer_name?: string;
  customer_phone?: string | null;
  seal_incident_reference?: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Stop {
  name: string;
  area: string;
  phone: string | null;
  address_line: string | null;
  latitude: number | null;
  longitude: number | null;
  notes: string | null;
}

export interface DriverJob {
  id: string;
  kind: "collection" | "delivery";
  status: "open" | "assigned" | "picked_up" | "completed" | "cancelled";
  order_number: string;
  window_start: string;
  window_end: string;
  driver_fee_cents: number;
  item_count: number;
  pickup: Stop;
  dropoff: Stop;
  next_step: string | null;
}

export interface JobBoardItem {
  id: string;
  kind: "collection" | "delivery";
  pickup_area: string;
  dropoff_area: string;
  distance_to_pickup_km: number;
  trip_km: number;
  window_start: string;
  window_end: string;
  fee_display: string;
  item_count: number;
}

export interface Requirement {
  name: string;
  accepted_types: string[];
  status: "missing" | "pending" | "approved" | "rejected";
  document_id: string | null;
  notes: string | null;
}

export interface Doc {
  id: string;
  document_type: string;
  original_filename: string;
  status: Verification;
  review_notes: string | null;
  uploaded_at: string;
}

export interface DocumentsOverview {
  documents: Doc[];
  requirements: Requirement[];
  ready_for_review: boolean;
  all_approved: boolean;
}

export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string;
  order_id: string | null;
  incident_id: string | null;
  read_at: string | null;
  created_at: string;
}

export interface IncidentUpdate {
  from_status: string | null;
  to_status: string | null;
  note: string | null;
  internal: boolean;
  author: string;
  created_at: string;
}

export interface IncidentSummary {
  id: string;
  reference: string;
  order_number: string | null;
  category: string;
  status: string;
  severity: string;
  is_automatic: boolean;
  created_at: string;
}

export interface Incident extends IncidentSummary {
  order_id: string | null;
  description: string;
  resolution: string | null;
  updates: IncidentUpdate[];
}

export interface Photo {
  id: string;
  stage: string;
  uploader_role: string;
  caption: string | null;
  created_at: string;
}

export interface AdminIncident extends Incident {
  reporter_id: string;
  reporter_name: string;
  reporter_role: string;
  assigned_admin_name: string | null;
  incident_photos: Photo[];
  evidence: {
    order_number: string;
    order_status: string;
    business_name: string;
    customer_name: string;
    history: StatusEvent[];
    handovers: (Handover & { from_name: string | null; to_name: string | null; latitude: number | null; longitude: number | null })[];
    seals: Seal[];
    photos: Photo[];
  } | null;
}
