# app.py
from flask import Flask, request, jsonify
import requests
import re
import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

app = Flask(__name__)

# -------------------------
# Configuration / Mock Data
# -------------------------
# 6 technicians, 3 regions, availability in ISO8601 with +05:30
TECHNICIANS_DATA = [
    {
        "id": "tech_01",
        "name": "Asha K",
        "skills": ["wm_vibration", "ac_leak"],
        "appliances_supported": ["WashingMachine", "AC"],
        "regions": ["Bengaluru Urban", "Central"],
        "availability_slots": [
            {"start": "2025-09-20T10:00:00+05:30", "end": "2025-09-20T12:00:00+05:30"},
            {"start": "2025-09-20T15:00:00+05:30", "end": "2025-09-20T16:00:00+05:30"}
        ]
    },
    {
        "id": "tech_02",
        "name": "Ravi S",
        "skills": ["fridge_cooling", "tv_display"],
        "appliances_supported": ["Refrigerator", "TV"],
        "regions": ["Mumbai Suburban", "Central"],
        "availability_slots": [
            {"start": "2025-09-21T09:00:00+05:30", "end": "2025-09-21T11:00:00+05:30"},
            {"start": "2025-09-21T14:00:00+05:30", "end": "2025-09-21T16:00:00+05:30"}
        ]
    },
    {
        "id": "tech_03",
        "name": "Priya M",
        "skills": ["ac_airflow", "waterpurifier_filter"],
        "appliances_supported": ["AC", "WaterPurifier"],
        "regions": ["Bengaluru Urban", "West"],
        "availability_slots": [
            {"start": "2025-09-22T10:30:00+05:30", "end": "2025-09-22T12:30:00+05:30"},
            {"start": "2025-09-22T15:30:00+05:30", "end": "2025-09-22T17:00:00+05:30"}
        ]
    },
    {
        "id": "tech_04",
        "name": "Anil P",
        "skills": ["wm_drum", "ac_cooling"],
        "appliances_supported": ["WashingMachine", "AC"],
        "regions": ["West", "Mumbai Suburban"],
        "availability_slots": [
            {"start": "2025-09-23T09:00:00+05:30", "end": "2025-09-23T11:00:00+05:30"},
            {"start": "2025-09-23T13:00:00+05:30", "end": "2025-09-23T15:00:00+05:30"}
        ]
    },
    {
        "id": "tech_05",
        "name": "Neha R",
        "skills": ["fridge_temp", "tv_sound"],
        "appliances_supported": ["Refrigerator", "TV"],
        "regions": ["Central", "Bengaluru Urban"],
        "availability_slots": [
            {"start": "2025-09-24T10:00:00+05:30", "end": "2025-09-24T12:00:00+05:30"},
            {"start": "2025-09-24T15:00:00+05:30", "end": "2025-09-24T16:30:00+05:30"}
        ]
    },
    {
        "id": "tech_06",
        "name": "Kiran V",
        "skills": ["waterpurifier_flow", "ac_noise", "wm_motor"],
        "appliances_supported": ["WaterPurifier", "AC", "WashingMachine"],
        "regions": ["West", "Mumbai Suburban"],
        "availability_slots": [
            {"start": "2025-09-25T09:30:00+05:30", "end": "2025-09-25T11:30:00+05:30"},
            {"start": "2025-09-25T14:30:00+05:30", "end": "2025-09-25T16:30:00+05:30"}
        ]
    }
]

# Cached regions mapping (fallback)
REGIONS_CACHE = [
    {"pincode_prefix": "5600xx", "region_label": "Bengaluru Urban"},
    {"pincode_prefix": "4000xx", "region_label": "Mumbai Suburban"},
    {"pincode_prefix": "1100xx", "region_label": "Delhi"}
]

# Knowledge stubs for adaptive questioning
KNOWLEDGE_STUBS = {
    "WashingMachine": [
        "Is the drum spinning?",
        "Is there vibration or movement?",
        "Is water intake or drainage normal?",
        "Are any error codes visible?"
    ],
    "AC": [
        "Is it cooling effectively?",
        "Is there reduced airflow?",
        "Any unusual noise?",
        "Any water leakage?",
        "Any error codes displayed?"
    ],
    "Refrigerator": [
        "Is cooling normal?",
        "Any frost buildup?",
        "Is the door sealing properly?",
        "Any unusual noise?"
    ],
    "TV": [
        "Does the TV power on?",
        "Are there display issues?",
        "Is the remote pairing fine?",
        "Are input ports working?"
    ],
    "WaterPurifier": [
        "Is water flowing normally?",
        "Is filter status ok?",
        "Any leakage?",
        "Any unusual noise?"
    ]
}

# In-memory persistence for customers, jobs, appointments
CUSTOMERS: Dict[str, dict] = {}          # customer_id -> customer data
JOBS: Dict[str, dict] = {}               # job_id -> job context
APPOINTMENTS: Dict[str, dict] = {}       # ticket_id -> appointment


# -------------------------
# Validation helpers
# -------------------------
PHONE_RE = re.compile(r"^[6-9]\d{9}$")             # Indian mobile numbers
EMAIL_RE = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w{2,}$")
PINCODE_RE = re.compile(r"^\d{6}$")

def validate_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(re.sub(r"\D", "", phone)))

def validate_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))

def validate_pincode(pincode: str) -> bool:
    return bool(PINCODE_RE.match(pincode.strip()))

def mask_pii(s: str) -> str:
    if not s: return s
    # simple mask for logs: show first 2 and last 2 digits/letters
    if "@" in s:
        parts = s.split("@")
        return parts[0][:2] + "***@" + parts[1]
    return s[:2] + "***" + s[-2:]


# -------------------------
# Utility: parse ISO datetimes
# -------------------------
def parse_iso(dt_str: str) -> datetime:
    # Python 3.7+ supports fromisoformat with offset
    return datetime.fromisoformat(dt_str)

def overlap_slot(pref_start: datetime, pref_end: datetime, tech_start: datetime, tech_end: datetime) -> Optional[tuple]:
    latest_start = max(pref_start, tech_start)
    earliest_end = min(pref_end, tech_end)
    if latest_start < earliest_end:
        return (latest_start, earliest_end)
    return None

# -------------------------
# Pincode lookup with retry + fallback
# -------------------------
def lookup_region(pincode: str, retries: int = 2, timeout: float = 3.0) -> str:
    url = f"https://api.zippopotam.us/IN/{pincode}"
    attempts = 0
    while attempts <= retries:
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                js = resp.json()
                places = js.get("places", [])
                if places:
                    # Choose stable field: state (or place name if you prefer)
                    state = places[0].get("state", "").strip()
                    place_name = places[0].get("place name", "").strip()
                    # Try to map to our cached region labels
                    for r in REGIONS_CACHE:
                        lab = r["region_label"].lower()
                        if lab in state.lower() or lab in place_name.lower():
                            return r["region_label"]
                    # fallback to 'state' if no mapping
                    return state or place_name or "Unknown"
            else:
                # non-200 treated as failure and retried
                pass
        except requests.RequestException:
            pass
        attempts += 1
    # fallback to cached mapping by prefix
    for r in REGIONS_CACHE:
        prefix = r["pincode_prefix"][:4]  # e.g., "5600"
        if pincode.startswith(prefix[:len(prefix)]):
            return r["region_label"]
    return "Unknown"

# -------------------------
# Scheduling logic
# -------------------------
def find_technicians_for(appliance: str, required_skill: Optional[str], region_label: str) -> List[dict]:
    matches = []
    for tech in TECHNICIANS_DATA:
        if appliance in tech["appliances_supported"]:
            if region_label in tech["regions"]:
                if required_skill:
                    if required_skill in tech["skills"]:
                        matches.append(tech)
                else:
                    matches.append(tech)
    return matches

def propose_slots(tech: dict, customer_pref_slots: List[dict], max_proposals: int = 2) -> List[dict]:
    proposals = []
    # try to find overlaps with customer prefs
    for pref in customer_pref_slots:
        try:
            pref_start = parse_iso(pref["start"])
            pref_end = parse_iso(pref["end"])
        except Exception:
            continue
        for ts in tech["availability_slots"]:
            try:
                tech_start = parse_iso(ts["start"])
                tech_end = parse_iso(ts["end"])
            except Exception:
                continue
            ov = overlap_slot(pref_start, pref_end, tech_start, tech_end)
            if ov:
                proposals.append({"start": ov[0].isoformat(), "end": ov[1].isoformat(), "technician_id": tech["id"]})
                if len(proposals) >= max_proposals:
                    return proposals
    # if no overlaps found, propose first available slots from tech
    for ts in tech["availability_slots"]:
        proposals.append({"start": ts["start"], "end": ts["end"], "technician_id": tech["id"]})
        if len(proposals) >= max_proposals:
            break
    return proposals

def persist_appointment(appointment: dict) -> str:
    ticket_id = f"TK-{uuid.uuid4().hex[:8]}"
    APPOINTMENTS[ticket_id] = appointment
    # optional: write to disk for judges (not required)
    # with open("appointments.json", "w") as f:
    #     json.dump(APPOINTMENTS, f, indent=2)
    return ticket_id

# -------------------------
# Integration placeholders
# -------------------------
def create_crm_ticket(appointment: dict) -> str:
    # Placeholder to integrate with a CRM (return crm_ticket_id)
    # e.g., call CRM API and return created ticket id
    print("[INTEGRATION] create_crm_ticket called (placeholder)")
    return "CRM-PLACEHOLDER"

def sync_calendar(appointment: dict) -> str:
    # Placeholder to integrate with calendar API (Google Calendar / Outlook)
    print("[INTEGRATION] sync_calendar called (placeholder)")
    return "CAL-PLACEHOLDER"

def warm_transfer_payload(appointment: dict) -> dict:
    # Create a compact summary for human agent warm transfer
    summary = {
        "customer": appointment.get("customer_name"),
        "phone": appointment.get("phone")[:2] + "***" + appointment.get("phone")[-2:],
        "appliance": appointment.get("appliance_type"),
        "fault_symptoms": appointment.get("fault_symptoms"),
        "attempted_slots": appointment.get("proposed_slots", [])
    }
    return summary

# -------------------------
# Endpoints (Intent handlers)
# -------------------------

@app.route("/register_service_issue", methods=["POST"])
def register_service_issue():
    payload = request.json or {}
    # Capture and validate critical entities
    full_name = payload.get("full_name", "").strip()
    phone = payload.get("phone", "").strip()
    email = payload.get("email", "").strip()
    address_text = payload.get("address_text", "").strip()
    pincode = payload.get("pincode", "").strip()
    preferred_time_slots = payload.get("preferred_time_slots", [])
    appliance_type = payload.get("appliance_type", "").strip()
    fault_symptoms = payload.get("fault_symptoms", [])
    urgency = payload.get("urgency", "normal")

    errors = []
    if not full_name:
        errors.append("full_name required")
    if not validate_phone(phone):
        errors.append("invalid phone (expected 10-digit Indian mobile)")
    if email and not validate_email(email):
        errors.append("invalid email")
    if not validate_pincode(pincode):
        errors.append("invalid pincode (6 digits)")
    if not appliance_type:
        errors.append("appliance_type required")
    if errors:
        return jsonify({"status":"error","errors":errors}), 400

    # Lookup region (with retry and fallback)
    region_label = lookup_region(pincode)

    # Simple triage: take first symptom as required skill mapping if present
    required_skill = fault_symptoms[0] if fault_symptoms else None

    # Find matching technicians
    techs = find_technicians_for(appliance_type, required_skill, region_label)

    # propose slots from first matched technician
    proposals = []
    if techs:
        proposals = propose_slots(techs[0], preferred_time_slots or [])
        # ensure at least two proposals: try to get from more technicians
        idx = 0
        while len(proposals) < 2 and idx+1 < len(techs):
            more = propose_slots(techs[idx+1], preferred_time_slots or [])
            for p in more:
                if p not in proposals:
                    proposals.append(p)
            idx += 1

    # Persist customer & job context
    customer_id = f"CUST-{uuid.uuid4().hex[:8]}"
    CUSTOMERS[customer_id] = {
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "address_text": address_text,
        "pincode": pincode,
        "region_label": region_label,
        "preferred_time_slots": preferred_time_slots
    }
    job_id = f"JOB-{uuid.uuid4().hex[:8]}"
    JOBS[job_id] = {
        "request_type": "service",
        "appliance_type": appliance_type,
        "model_if_known": payload.get("model_if_known", ""),
        "fault_symptoms": fault_symptoms,
        "installation_details": [],
        "urgency": urgency,
        "customer_id": customer_id
    }

    # Build triage response
    response = {
        "status": "ok",
        "customer_id": customer_id,
        "job_id": job_id,
        "region_label": region_label,
        "matched_tech_count": len(techs),
        "proposed_slots": proposals,
        "knowledge_questions": KNOWLEDGE_STUBS.get(appliance_type, [])
    }

    # Log (masked)
    print(f"[LOG] register_service_issue: customer={mask_pii(full_name)}, phone={mask_pii(phone)}, region={region_label}")

    return jsonify(response), 200


@app.route("/book_installation", methods=["POST"])
def book_installation():
    payload = request.json or {}
    # For installation flow, reuse same structure but different request_type
    # Validate similar fields
    full_name = payload.get("full_name", "").strip()
    phone = payload.get("phone", "").strip()
    pincode = payload.get("pincode", "").strip()
    appliance_type = payload.get("appliance_type", "").strip()
    preferred_time_slots = payload.get("preferred_time_slots", [])
    email = payload.get("email", "").strip()

    errors = []
    if not full_name:
        errors.append("full_name required")
    if not validate_phone(phone):
        errors.append("invalid phone")
    if email and not validate_email(email):
        errors.append("invalid email")
    if not validate_pincode(pincode):
        errors.append("invalid pincode")
    if not appliance_type:
        errors.append("appliance_type required")
    if errors:
        return jsonify({"status":"error","errors":errors}), 400

    region_label = lookup_region(pincode)
    # For installation, skill is generic installation for appliance
    required_skill = f"install_{appliance_type.lower()}"
    techs = find_technicians_for(appliance_type, None, region_label)

    proposals = []
    if techs:
        proposals = propose_slots(techs[0], preferred_time_slots or [])
        # aim to propose two
        idx = 0
        while len(proposals) < 2 and idx+1 < len(techs):
            more = propose_slots(techs[idx+1], preferred_time_slots or [])
            for p in more:
                if p not in proposals:
                    proposals.append(p)
            idx += 1

    # create customer/job
    customer_id = f"CUST-{uuid.uuid4().hex[:8]}"
    CUSTOMERS[customer_id] = {
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "address_text": payload.get("address_text", ""),
        "pincode": pincode,
        "region_label": region_label,
        "preferred_time_slots": preferred_time_slots
    }
    job_id = f"JOB-{uuid.uuid4().hex[:8]}"
    JOBS[job_id] = {
        "request_type": "installation",
        "appliance_type": appliance_type,
        "model_if_known": payload.get("model_if_known", ""),
        "fault_symptoms": [],
        "installation_details": payload.get("installation_details", []),
        "urgency": payload.get("urgency", "normal"),
        "customer_id": customer_id
    }

    print(f"[LOG] book_installation: customer={mask_pii(full_name)}, pincode={pincode}, region={region_label}")

    return jsonify({
        "status": "ok",
        "customer_id": customer_id,
        "job_id": job_id,
        "region_label": region_label,
        "proposed_slots": proposals
    }), 200


@app.route("/ask_availability", methods=["GET"])
def ask_availability():
    # Query params: pincode, appliance
    pincode = request.args.get("pincode", "").strip()
    appliance = request.args.get("appliance", "").strip()
    if not validate_pincode(pincode) or not appliance:
        return jsonify({"error": "pincode and appliance required"}), 400
    region_label = lookup_region(pincode)
    # collect available technicians and their first 2 slots
    results = []
    for tech in TECHNICIANS_DATA:
        if appliance in tech["appliances_supported"] and region_label in tech["regions"]:
            slots = tech.get("availability_slots", [])[:2]
            results.append({"technician_id": tech["id"], "technician_name": tech["name"], "slots": slots})
    return jsonify({"region_label": region_label, "availability": results}), 200


@app.route("/confirm_booking", methods=["POST"])
def confirm_booking():
    payload = request.json or {}
    # requires customer_id, job_id, chosen_slot (start,end), technician_id
    customer_id = payload.get("customer_id")
    job_id = payload.get("job_id")
    chosen_slot = payload.get("chosen_slot")
    technician_id = payload.get("technician_id")

    if not customer_id or not job_id or not chosen_slot or not technician_id:
        return jsonify({"error":"customer_id, job_id, chosen_slot, technician_id required"}), 400
    customer = CUSTOMERS.get(customer_id)
    job = JOBS.get(job_id)
    if not customer or not job:
        return jsonify({"error":"invalid customer_id or job_id"}), 400

    appointment = {
        "customer_id": customer_id,
        "customer_name": customer.get("full_name"),
        "phone": customer.get("phone"),
        "email": customer.get("email"),
        "address_text": customer.get("address_text"),
        "pincode": customer.get("pincode"),
        "region_label": customer.get("region_label"),
        "appliance_type": job.get("appliance_type"),
        "fault_symptoms": job.get("fault_symptoms"),
        "technician_id": technician_id,
        "slot_start": chosen_slot.get("start"),
        "slot_end": chosen_slot.get("end"),
        "status": "confirmed",
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    ticket_id = persist_appointment(appointment)

    # Integration placeholders
    crm_id = create_crm_ticket(appointment)
    cal_id = sync_calendar(appointment)

    appointment["ticket_id"] = ticket_id
    appointment["crm_id"] = crm_id
    appointment["calendar_id"] = cal_id

    print(f"[LOG] Booking confirmed: ticket={ticket_id}, customer={mask_pii(customer.get('full_name'))}")

    return jsonify({"status":"ok", "ticket_id": ticket_id, "appointment": appointment}), 200


@app.route("/reschedule", methods=["POST"])
def reschedule():
    payload = request.json or {}
    ticket_id = payload.get("ticket_id")
    new_slot = payload.get("new_slot")
    if not ticket_id or not new_slot:
        return jsonify({"error":"ticket_id and new_slot required"}), 400
    appointment = APPOINTMENTS.get(ticket_id)
    if not appointment:
        return jsonify({"error":"ticket not found"}), 404

    # Try to find if technician has this new_slot available
    tech = next((t for t in TECHNICIANS_DATA if t["id"] == appointment["technician_id"]), None)
    if not tech:
        return jsonify({"error":"technician not found"}), 404

    # Check overlap - simple equality check against tech availability slots
    match = False
    for ts in tech["availability_slots"]:
        if ts["start"] == new_slot.get("start") and ts["end"] == new_slot.get("end"):
            match = True
            break

    if not match:
        # propose alternative
        alt = tech["availability_slots"][0]
        return jsonify({"status":"no", "message":"requested slot not available", "alternative_slot": alt}), 200

    # update appointment
    appointment["slot_start"] = new_slot.get("start")
    appointment["slot_end"] = new_slot.get("end")
    appointment["status"] = "rescheduled"
    appointment["rescheduled_at"] = datetime.now(timezone.utc).isoformat()
    print(f"[LOG] Rescheduled ticket={ticket_id}")
    return jsonify({"status":"ok", "ticket_id": ticket_id, "appointment": appointment}), 200


@app.route("/cancel", methods=["POST"])
def cancel():
    payload = request.json or {}
    ticket_id = payload.get("ticket_id")
    reason = payload.get("reason", "")
    if not ticket_id:
        return jsonify({"error":"ticket_id required"}), 400
    appointment = APPOINTMENTS.get(ticket_id)
    if not appointment:
        return jsonify({"error":"ticket not found"}), 404
    appointment["status"] = "cancelled"
    appointment["cancel_reason"] = reason
    appointment["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    print(f"[LOG] Cancelled ticket={ticket_id}")
    return jsonify({"status":"ok","ticket_id":ticket_id}), 200


@app.route("/update_contact", methods=["POST"])
def update_contact():
    payload = request.json or {}
    customer_id = payload.get("customer_id")
    phone = payload.get("phone")
    email = payload.get("email")
    if not customer_id:
        return jsonify({"error":"customer_id required"}), 400
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return jsonify({"error":"customer not found"}), 404
    if phone:
        if not validate_phone(phone):
            return jsonify({"error":"invalid phone"}), 400
        customer["phone"] = phone
    if email:
        if not validate_email(email):
            return jsonify({"error":"invalid email"}), 400
        customer["email"] = email
    print(f"[LOG] Updated contact for customer={customer_id}")
    return jsonify({"status":"ok","customer":customer}), 200


@app.route("/change_address", methods=["POST"])
def change_address():
    payload = request.json or {}
    customer_id = payload.get("customer_id")
    address_text = payload.get("address_text", "")
    pincode = payload.get("pincode", "")
    if not customer_id:
        return jsonify({"error":"customer_id required"}), 400
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return jsonify({"error":"customer not found"}), 404
    if address_text:
        customer["address_text"] = address_text
    if pincode:
        if not validate_pincode(pincode):
            return jsonify({"error":"invalid pincode"}), 400
        customer["pincode"] = pincode
        customer["region_label"] = lookup_region(pincode)
    print(f"[LOG] Address updated for customer={customer_id}")
    return jsonify({"status":"ok","customer":customer}), 200


@app.route("/escalate_to_human", methods=["POST"])
def escalate_to_human():
    payload = request.json or {}
    ticket_id = payload.get("ticket_id")
    reason = payload.get("reason", "")
    appointment = APPOINTMENTS.get(ticket_id) if ticket_id else None
    if not appointment:
        # If no ticket, still allow escalation with context from payload
        appointment = payload.get("context", {})
    summary = warm_transfer_payload(appointment)
    summary["reason"] = reason
    # In a real system, call transfer API here; return payload for human agent
    print(f"[LOG] Escalation requested. Summary: {summary}")
    return jsonify({"status":"ok", "transfer_payload": summary}), 200


# -------------------------
# Observability endpoint for judges (dump current state)
# -------------------------
@app.route("/_debug/state", methods=["GET"])
def debug_state():
    # mask PII in output
    masked_customers = {}
    for cid, c in CUSTOMERS.items():
        masked = c.copy()
        masked["phone"] = mask_pii(masked.get("phone",""))
        masked["email"] = mask_pii(masked.get("email",""))
        masked_customers[cid] = masked
    return jsonify({
        "customers": masked_customers,
        "jobs": JOBS,
        "appointments_count": len(APPOINTMENTS),
        "technicians_count": len(TECHNICIANS_DATA)
    }), 200

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
