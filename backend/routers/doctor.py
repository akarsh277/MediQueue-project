from websocket_manager import manager
from fastapi import BackgroundTasks, APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from database import SessionLocal
from pydantic import BaseModel
import models
import schemas
from security import get_current_user

router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])



# ── Schemas (local, lightweight) ──────────────────────────────
class SendMessageRequest(BaseModel):
    sender_role: str
    sender_id: int
    message: str


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── List All Doctors ───────────────────────────────────────────
@router.get("/doctors")
def list_doctors(db: Session = Depends(get_db)):
    doctors = db.query(models.Doctor).all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "department": d.department,
            "user_id": d.user_id,
            "is_available": d.is_available
        }
        for d in doctors
    ]


# ── Resolve Doctor Profile ID from User ID ─────────────────────
@protected_router.get("/myDoctorId/{user_id}")
def my_doctor_id(user_id: int, db: Session = Depends(get_db)):
    doctor = db.query(models.Doctor).filter(models.Doctor.user_id == user_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found for this user")
    return {
        "doctor_id": doctor.id,
        "name": doctor.name,
        "department": doctor.department,
    }


# ── Today's All Patient Visits ─────────────────────────────────
@protected_router.get("/todayPatients")
def today_patients(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    today = datetime.now().strftime("%Y-%m-%d")
    visits = (
        db.query(models.PatientVisit)
        .filter(models.PatientVisit.visit_date == today)
        .order_by(models.PatientVisit.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    priority_labels = {1: "Emergency", 2: "Child", 3: "Senior", 4: "Normal"}

    result = []
    for v in visits:
        # Fetch doctor name
        doctor_name = "—"
        if v.doctor_id:
            doc = db.query(models.Doctor).filter(models.Doctor.id == v.doctor_id).first()
            if doc:
                doctor_name = f"Dr. {doc.name}"

        # Fetch phone number
        phone = ""
        if v.user_id:
            u = db.query(models.User).filter(models.User.id == v.user_id).first()
            if u:
                phone = u.phone

        result.append({
            "visit_id": v.id,
            "token_number": v.token_number,
            "name": v.name,
            "phone": phone,
            "age": v.age,
            "problem": v.problem,
            "doctor": doctor_name,
            "priority": priority_labels.get(v.priority, "Normal"),
            "status": v.status,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        })

    return result


@router.get("/queue/{doctor_id}")
def get_queue(doctor_id: int, db: Session = Depends(get_db)):

    today = datetime.now().strftime("%Y-%m-%d")

    patients = (
        db.query(models.PatientVisit)
        .filter(
            models.PatientVisit.doctor_id == doctor_id,
            models.PatientVisit.visit_date == today,
            models.PatientVisit.status == "waiting",
        )
        .order_by(
            models.PatientVisit.priority.asc(), models.PatientVisit.created_at.asc()
        )
        .all()
    )

    response = []

    # Calculate average consultation time
    avg_mins = 5
    historical_visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.doctor_id == doctor_id,
        models.PatientVisit.serving_time.isnot(None),
        models.PatientVisit.completion_time.isnot(None)
    ).order_by(models.PatientVisit.id.desc()).limit(50).all()
    
    if historical_visits:
        total_time = 0
        valid_count = 0
        for hv in historical_visits:
            if isinstance(hv.serving_time, datetime) and isinstance(hv.completion_time, datetime):
                diff = (hv.completion_time - hv.serving_time).total_seconds() / 60.0
                if diff > 0 and diff < 180: # Sanity check
                    total_time += diff
                    valid_count += 1
        if valid_count > 0:
            avg_mins = max(1, int(total_time / valid_count))

    now = datetime.utcnow()
    
    # Pre-calculate to sort
    scored_patients = []
    for patient in patients:
        wait_duration = 0
        if patient.created_at:
            try:
                wait_duration = (now - patient.created_at).total_seconds() / 60.0
            except Exception:
                wait_duration = 0
            
        emergency_val = 1 if patient.priority == 1 else 0
        age_val = 2 if patient.age and patient.age > 60 else 0
        score = (emergency_val * 5) + age_val + (wait_duration / 10.0)
        
        scored_patients.append({
            "patient": patient,
            "score": score,
            "wait_mins": int(wait_duration)
        })
    
    # Sort by highest priority score descending
    scored_patients.sort(key=lambda x: x["score"], reverse=True)

    for index, sp in enumerate(scored_patients):
        patient = sp["patient"]
        position = index + 1
        waiting_time = (position - 1) * avg_mins

        response.append(
            {
                "token_number": patient.token_number,
                "visit_id": patient.id,
                "name": patient.name,
                "age": patient.age,
                "priority": patient.priority,
                "queue_position": position,
                "estimated_waiting_time_minutes": waiting_time,
                "waiting_duration_mins": sp["wait_mins"],
                "priority_score": round(sp["score"], 2)
            }
        )

    return response


@protected_router.post("/nextPatient/{doctor_id}")
def next_patient(doctor_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

    today = datetime.now().strftime("%Y-%m-%d")

    # Check if someone already serving
    serving = (
        db.query(models.PatientVisit)
        .filter(
            models.PatientVisit.doctor_id == doctor_id,
            models.PatientVisit.visit_date == today,
            models.PatientVisit.status == "serving",
        )
        .first()
    )

    if serving:
        raise HTTPException(status_code=400, detail="A patient is already being served")

    # Get next waiting patient
    patients = (
        db.query(models.PatientVisit)
        .filter(
            models.PatientVisit.doctor_id == doctor_id,
            models.PatientVisit.visit_date == today,
            models.PatientVisit.status == "waiting",
        )
        .all()
    )
    
    if not patients:
        raise HTTPException(status_code=404, detail="No patients in queue")

    now = datetime.utcnow()
    scored_patients = []
    for patient in patients:
        wait_duration = 0
        if patient.created_at:
            try:
                wait_duration = (now - patient.created_at).total_seconds() / 60.0
            except Exception:
                wait_duration = 0
            
        emergency_val = 1 if patient.priority == 1 else 0
        age_val = 2 if patient.age and patient.age > 60 else 0
        score = (emergency_val * 5) + age_val + (wait_duration / 10.0)
        
        scored_patients.append((score, patient))
        
    scored_patients.sort(key=lambda x: x[0], reverse=True)
    next_patient = scored_patients[0][1]

    if not next_patient:
        raise HTTPException(status_code=404, detail="No patients in queue")

    next_patient.status = "serving"
    next_patient.serving_time = datetime.utcnow()
    # fulfilling the requirement for Feature 4 tracking consultation time start
    next_patient.consultation_start_time = next_patient.serving_time
    db.commit()

    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {
        "message": "Patient now serving",
        "token_number": next_patient.token_number,
        "visit_id": next_patient.id,
        "name": next_patient.name,
    }


@protected_router.post("/push-back/{visit_id}")
def push_back_patient(visit_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    visit = db.query(models.PatientVisit).filter(models.PatientVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
        
    if visit.status != "serving":
        raise HTTPException(status_code=400, detail="Only serving patients can be pushed back")
        
    visit.status = "waiting"
    visit.created_at = datetime.utcnow()
    visit.serving_time = None
    visit.consultation_start_time = None
    
    db.commit()
    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"message": "Patient pushed back to waiting queue successfully"}


@protected_router.post("/completePatient/{visit_id}")
def complete_patient(visit_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

    patient = (
        db.query(models.PatientVisit)
        .filter(
            models.PatientVisit.id == visit_id, models.PatientVisit.status == "serving"
        )
        .first()
    )

    if not patient:
        raise HTTPException(status_code=404, detail="Serving patient not found")

    patient.status = "completed"
    patient.completion_time = datetime.utcnow()
    db.commit()

    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"message": "Patient marked as completed"}


@protected_router.post("/request-admission/{visit_id}")
def request_admission(visit_id: int, data: schemas.RequestAdmissionRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

    patient = (
        db.query(models.PatientVisit)
        .filter(
            models.PatientVisit.id == visit_id, models.PatientVisit.status == "serving"
        )
        .first()
    )

    if not patient:
        raise HTTPException(status_code=404, detail="Serving patient not found")

    cond = data.condition.lower()
    
    if cond == "critical":
         suggested_bed = "ICU"
    elif patient.age and patient.age > 60:
         suggested_bed = "General Ward"
    else:
         suggested_bed = "Normal Ward"

    patient.condition = data.condition
    patient.suggested_bed = suggested_bed
    patient.status = "admission_requested"
    patient.completion_time = datetime.utcnow()
    # also fulfill the requirement for feature 4:
    patient.consultation_end_time = patient.completion_time

    db.commit()

    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {
        "message": "Admission requested", 
        "suggested_bed": suggested_bed,
        "condition": patient.condition
    }


@protected_router.post("/dischargePatient/{visit_id}")
def discharge_patient(visit_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

    patient = (
        db.query(models.PatientVisit)
        .filter(
            models.PatientVisit.id == visit_id, models.PatientVisit.status == "admitted"
        )
        .first()
    )

    if not patient:
        raise HTTPException(status_code=404, detail="Admitted patient not found")

    bed = db.query(models.Bed).filter(models.Bed.patient_id == visit_id).first()

    if bed:
        bed.status = "free"
        bed.is_occupied = 0
        bed.patient_id = None

    patient.status = "discharged"
    patient.discharge_time = datetime.utcnow()

    db.commit()

    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"message": "Patient discharged and bed freed"}

@router.get("/currentServing/{doctor_id}")
def current_serving(doctor_id: int, db: Session = Depends(get_db)):

    today = datetime.now().strftime("%Y-%m-%d")

    patient = db.query(models.PatientVisit).filter(
        models.PatientVisit.doctor_id == doctor_id,
        models.PatientVisit.visit_date == today,
        models.PatientVisit.status == "serving"
    ).first()

    if not patient:
        return {"message": "No patient currently serving"}

    return {
        "token_number": patient.token_number,
        "name": patient.name,
        "visit_id": patient.id
    }


@protected_router.get("/doctor/{doctor_id}")
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return {
        "id": doctor.id,
        "name": doctor.name,
        "department": doctor.department,
        "user_id": doctor.user_id,
        "is_available": doctor.is_available
    }

@protected_router.get("/doctor/{doctor_id}/availability")
def get_doctor_availability(doctor_id: int, db: Session = Depends(get_db)):
    doc = db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()
    return {"is_available": doc.is_available if doc else False}

@protected_router.post("/doctor/{doctor_id}/toggle-availability")
def toggle_doctor_availability(doctor_id: int, data: schemas.ToggleAvailabilityRequest, db: Session = Depends(get_db)):
    doc = db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()
    if doc:
        doc.is_available = data.is_available
        db.commit()
    return {"is_available": data.is_available}


@protected_router.post("/sendMessage")
def send_message(data: SendMessageRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    msg = models.Message(
        sender_role=data.sender_role,
        sender_id=data.sender_id,
        message=data.message,
        timestamp=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {
        "id": msg.id,
        "sender_role": msg.sender_role,
        "sender_id": msg.sender_id,
        "message": msg.message,
        "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
    }


@protected_router.get("/messages")
def get_messages(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    msgs = db.query(models.Message).order_by(models.Message.id.asc()).offset(skip).limit(limit).all()
    result = []
    for m in msgs:
        sender_name = None
        if m.sender_role == 'doctor':
            doc = db.query(models.Doctor).filter(models.Doctor.user_id == m.sender_id).first()
            if doc:
                sender_name = f"Dr. {doc.name}"
            else:
                sender_name = f"Doctor (ID: {m.sender_id})"
        elif m.sender_role == 'admin':
            sender_name = "Admin / Reception"
            
        result.append({
            "id": m.id,
            "sender_role": m.sender_role,
            "sender_id": m.sender_id,
            "sender_name": sender_name,
            "message": m.message,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        })
    return result


# ── Unread Counts for Admin Red Dots ────────────────────────
@protected_router.get("/admin/unread-messages-count")
def unread_messages_count(since_id: int = 0, db: Session = Depends(get_db)):
    """Returns count of doctor messages sent after since_id (admin tracks last seen id)."""
    count = db.query(models.Message).filter(
        models.Message.id > since_id,
        models.Message.sender_role == "doctor"
    ).count()
    return {"count": count}


@protected_router.get("/admin/pending-admissions-count")
def pending_admissions_count(db: Session = Depends(get_db)):
    """Returns count of admission requests pending admin approval."""
    count = db.query(models.PatientVisit).filter(
        models.PatientVisit.status == "admission_requested"
    ).count()
    return {"count": count}

# ---------------- NEW DOCTOR FEATURES ----------------

@protected_router.post("/skipPatient/{visit_id}")
def skip_patient(visit_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    patient = db.query(models.PatientVisit).filter(
        models.PatientVisit.id == visit_id,
        models.PatientVisit.status == "waiting"
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Waiting patient not found")
        
    patient.created_at = datetime.utcnow()
    db.commit()
    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"message": "Patient skipped and moved down the queue"}

@protected_router.post("/cancelPatient/{visit_id}")
def cancel_patient(visit_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    patient = db.query(models.PatientVisit).filter(
        models.PatientVisit.id == visit_id,
        models.PatientVisit.status == "waiting"
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Waiting patient not found")
        
    patient.status = "cancelled"
    q_entry = db.query(models.Queue).filter(models.Queue.patient_id == visit_id).first()
    if q_entry:
        db.delete(q_entry)
        
    db.commit()
    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"message": "Patient appointment cancelled"}

@protected_router.get("/patientDetails/{visit_id}")
def get_patient_details(visit_id: int, db: Session = Depends(get_db)):
    v = db.query(models.PatientVisit).filter(models.PatientVisit.id == visit_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Visit not found")

    user = db.query(models.User).filter(models.User.id == v.user_id).first()
    
    history = []
    if user:
        past_visits = db.query(models.PatientVisit).filter(
            models.PatientVisit.user_id == user.id,
            models.PatientVisit.id != visit_id
        ).order_by(models.PatientVisit.created_at.desc()).all()
        
        docs = {d.id: d.name for d in db.query(models.Doctor).all()}
        for pv in past_visits:
            prescriptions = [{"medicine_name": p.medicine_name, "dosage": p.dosage, "duration": p.duration, "notes": p.notes} for p in pv.prescriptions]
            reports = [{"filename": r.filename, "url": f"/uploads/reports/{r.file_path}"} for r in pv.reports]
            history.append({
                "visit_id": pv.id,
                "date": pv.visit_date,
                "doctor": f"Dr. {docs.get(pv.doctor_id, 'Unknown')}",
                "problem": pv.problem or "—",
                "diagnosis": pv.diagnosis,
                "prescriptions": prescriptions,
                "reports": reports
            })
            
    current_reports = [{"filename": r.filename, "url": f"/uploads/reports/{r.file_path}"} for r in v.reports]
    current_prescriptions = [{"medicine_name": p.medicine_name, "dosage": p.dosage, "duration": p.duration, "notes": p.notes} for p in v.prescriptions]

    return {
        "visit_id": v.id,
        "name": v.name,
        "age": v.age,
        "problem": v.problem,
        "history": history,
        "current_reports": current_reports,
        "current_diagnosis": v.diagnosis,
        "current_condition": v.condition,
        "current_prescriptions": current_prescriptions
    }

@protected_router.post("/prescription/{visit_id}")
def complete_consultation(visit_id: int, data: schemas.CompleteConsultationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    patient = db.query(models.PatientVisit).filter(
        models.PatientVisit.id == visit_id,
        models.PatientVisit.status == "serving"
    ).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Serving patient not found")
        
    if data.diagnosis:
        patient.diagnosis = data.diagnosis
        
    for p in data.prescriptions:
        presc = models.Prescription(
            visit_id=visit_id,
            medicine_name=p.medicine_name,
            dosage=p.dosage,
            duration=p.duration,
            notes=p.notes
        )
        db.add(presc)
        
    db.commit()
    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"message": "Prescription and diagnosis saved successfully"}

router.include_router(protected_router)