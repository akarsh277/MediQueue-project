from websocket_manager import manager
from fastapi import BackgroundTasks, APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from database import SessionLocal
import models
import schemas
import os
import boto3
from botocore.exceptions import NoCredentialsError
from fastapi import BackgroundTasks, Request, Path
from typing import Annotated
from security import limiter, get_current_user
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

router = APIRouter(dependencies=[Depends(get_current_user)])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/addPatient")
def add_patient(data: schemas.AddPatientRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

    doc = db.query(models.Doctor).filter(models.Doctor.id == data.doctor_id).first()
    if not doc or not doc.is_available:
        raise HTTPException(
            status_code=400, detail="The selected doctor is currently unavailable."
        )

    today = datetime.utcnow().date().isoformat()
    token = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date == today,
        models.PatientVisit.doctor_id == data.doctor_id
    ).count() + 1

    # 1️⃣ Check if user exists by phone
    user = db.query(models.User).filter(models.User.phone == data.phone).first()

    if not user:
        # Create new patient user
        user = models.User(
            username=data.name, phone=data.phone, password=pwd_context.hash(data.password or "patient123"), role="patient", age=data.age
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # 2️⃣ Check if patient already has active visit today
    existing_visit = (
        db.query(models.PatientVisit)
        .filter(
            models.PatientVisit.user_id == user.id,
            models.PatientVisit.visit_date == today,
            models.PatientVisit.status.in_(["waiting", "serving", "admitted"]),
        )
        .first()
    )

    if existing_visit:
        raise HTTPException(
            status_code=400, detail="Patient already has an active visit today"
        )

    # 3️⃣ Calculate Priority
    if data.is_emergency:
        priority = 1
    elif data.age < 5:
        priority = 2
    elif data.age > 60:
        priority = 3
    else:
        priority = 4

    # 4️⃣ Create Visit Record
    try:
        # Fetch doctor's department
        doc = db.query(models.Doctor).filter(models.Doctor.id == data.doctor_id).first()
        dept = doc.department if doc else None
        
        visit = models.PatientVisit(
            user_id=user.id,
            name=data.name,
            age=data.age,
            problem=data.problem,
            doctor_id=data.doctor_id,
            department=dept,
            priority=priority,
            status="waiting",
            visit_date=today,
            token_number=token
        )

        db.add(visit)
        db.commit()
        db.refresh(visit)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Token generation conflict, please retry. Actual Error: {str(e)}"
        )
    # 5️⃣ Insert into Queue
    queue_entry = models.Queue(patient_id=visit.id, doctor_id=data.doctor_id)

    db.add(queue_entry)
    db.commit()

    # 6️⃣ Check Returning Status
    past_visit_count = db.query(models.PatientVisit).filter(
        models.PatientVisit.user_id == user.id,
        models.PatientVisit.visit_date != today
    ).count()

    is_returning = past_visit_count > 0

    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {
        "success": True,
        "message": "Patient added successfully",
        "data": {
            "visit_id": visit.id, 
            "priority": priority,
            "is_returning": is_returning,
            "past_visit_count": past_visit_count
        },
    }

@router.get("/check-phone/{phone}")
@limiter.limit("10/minute")
def check_phone(request: Request, phone: Annotated[str, Path(pattern=r"^[0-9]{10}$")], db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == phone).first()
    if not user:
        return {"exists": False}
        
    past_visit_count = db.query(models.PatientVisit).filter(
        models.PatientVisit.user_id == user.id,
        models.PatientVisit.visit_date != datetime.utcnow().date().isoformat()
    ).count()
    
    return {
        "exists": True,
        "name": user.username,
        "past_visit_count": past_visit_count
    }

@router.get("/patient-history/{phone}")
def patient_history(phone: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.user_id == user.id
    ).order_by(models.PatientVisit.created_at.desc()).all()
    
    docs = {d.id: d.name for d in db.query(models.Doctor).all()}
    
    history = []
    for v in visits:
        prescriptions = [{"medicine_name": p.medicine_name, "dosage": p.dosage, "duration": p.duration, "notes": p.notes, "is_dispensed": p.is_dispensed} for p in v.prescriptions]
        reports = [{"filename": r.filename, "url": f"/uploads/reports/{r.file_path}"} for r in v.reports]

        history.append({
            "visit_id": v.id,
            "token_number": v.token_number,
            "date": v.visit_date,
            "department": v.department or "Unknown",
            "doctor": f"Dr. {docs.get(v.doctor_id, 'Unknown')}",
            "problem": v.problem or "—",
            "status": v.status,
            "diagnosis": v.diagnosis,
            "prescriptions": prescriptions,
            "reports": reports
        })
        
    return {"name": user.username, "phone": user.phone, "history": history}

# ---------------- PATIENT HOME ----------------

@router.get("/me/{user_id}")
def get_patient_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id, models.User.role == "patient").first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "name": user.username, "phone": user.phone}

@router.post("/book-home/{user_id}")
def book_home(user_id: int, data: schemas.HomeBookingRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    doc = db.query(models.Doctor).filter(models.Doctor.id == data.doctor_id).first()
    if not doc or not doc.is_available:
        raise HTTPException(status_code=400, detail="The selected doctor is currently unavailable.")

    today = datetime.utcnow().date().isoformat()
    
    daily_count = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date == today,
        models.PatientVisit.doctor_id == data.doctor_id,
    ).count()
    if daily_count >= doc.daily_cap:
        raise HTTPException(status_code=400, detail="Doctor fully booked today.")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Patient user not found")

    existing_visit = db.query(models.PatientVisit).filter(
        models.PatientVisit.user_id == user.id,
        models.PatientVisit.visit_date == today,
        models.PatientVisit.status.in_(["waiting", "serving", "admitted"]),
    ).first()
    if existing_visit:
        raise HTTPException(status_code=400, detail="Patient already has an active visit today")

    token = daily_count + 1
    dept = doc.department if doc else None

    try:
        # Emergency overwrites age-based priority mapping
        calculated_priority = 1 if data.is_emergency else (2 if (user.age and user.age <= 12) else (3 if (user.age and user.age >= 60) else 4))

        visit = models.PatientVisit(
            user_id=user.id,
            name=user.username,
            age=user.age or 30, 
            problem=data.problem,
            doctor_id=data.doctor_id,
            department=dept,
            priority=calculated_priority,
            status="waiting",
            visit_date=today,
            token_number=token
        )
        db.add(visit)
        db.commit()
        db.refresh(visit)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Token generation conflict: {str(e)}")

    queue_entry = models.Queue(patient_id=visit.id, doctor_id=data.doctor_id, source="home")
    db.add(queue_entry)
    db.commit()

    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"success": True, "message": "Appointment booked successfully", "visit_id": visit.id, "token": token}

from fastapi import BackgroundTasks, UploadFile, File
import os
import shutil
import boto3

UPLOAD_DIR = "uploads/reports"

S3_BUCKET = os.getenv("AWS_BUCKET_NAME")
if S3_BUCKET:
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1")
    )

@router.post("/uploads/{visit_id}")
def upload_report(visit_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    visit = db.query(models.PatientVisit).filter(models.PatientVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    safe_filename = f"{visit_id}_{datetime.utcnow().timestamp()}_{file.filename}"
    
    if S3_BUCKET:
        try:
            s3_client.upload_fileobj(file.file, S3_BUCKET, safe_filename)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cloud upload failed: {str(e)}")
    else:
        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR)
        file_path = os.path.join(UPLOAD_DIR, safe_filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    report = models.Report(
        visit_id=visit_id,
        file_path=safe_filename,
        filename=file.filename
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {"message": "Report uploaded successfully", "report_id": report.id}

@router.post("/cancel/{visit_id}")
def cancel_visit(visit_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    visit = db.query(models.PatientVisit).filter(models.PatientVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    if visit.status != "waiting":
         raise HTTPException(status_code=400, detail="Cannot cancel a visit that is already serving or completed")

    visit.status = "cancelled"
    
    q_entry = db.query(models.Queue).filter(models.Queue.patient_id == visit_id).first()
    if q_entry:
         db.delete(q_entry)
         
    db.commit()
    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"success": True, "message": "Appointment cancelled"}

# ---------------- PREDICT WAIT TIME ----------------

@router.get("/predict-wait-time/{patient_id}")
def predict_wait_time(patient_id: int, db: Session = Depends(get_db)):
    # 1. Fetch patient
    patient = db.query(models.PatientVisit).filter(models.PatientVisit.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    if patient.status != "waiting":
         return {
             "patient_id": patient_id,
             "queue_position": 0,
             "estimated_wait_time": 0,
             "message": f"Patient is currently {patient.status}"
         }

    doctor_id = patient.doctor_id
    today = datetime.utcnow().date().isoformat()

    # 2. Reconstruct priority queue to determine position
    waiting_patients = db.query(models.PatientVisit).filter(
        models.PatientVisit.doctor_id == doctor_id,
        models.PatientVisit.visit_date == today,
        models.PatientVisit.status == "waiting"
    ).all()
    
    now = datetime.utcnow()
    scored_patients = []
    
    for wp in waiting_patients:
        wait_dur = 0
        if wp.created_at: wait_dur = (now - wp.created_at).total_seconds() / 60.0
        emerg_val = 1 if wp.priority == 1 else 0
        age_val = 2 if wp.age and wp.age > 60 else 0
        score = (emerg_val * 5) + age_val + (wait_dur / 10.0)
        scored_patients.append((score, wp))
        
    scored_patients.sort(key=lambda x: x[0], reverse=True)
    
    position = 1
    for i, sp in enumerate(scored_patients):
        if sp[1].id == patient_id:
            position = i + 1
            break

    # 3. Fetch past consultation durations (last 5)
    past_visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.doctor_id == doctor_id,
        models.PatientVisit.consultation_start_time.isnot(None),
        models.PatientVisit.consultation_end_time.isnot(None)
    ).order_by(models.PatientVisit.id.desc()).limit(5).all()

    avg_consultation_time = 10  # default
    
    if past_visits:
        # Reverse to get chronological order for weighted avg (oldest to newest)
        past_visits.reverse() 
        sum_weighted_time = 0
        sum_weights = 0
        for idx, pv in enumerate(past_visits):
            weight = idx + 1 # 1 to 5
            duration_mins = (pv.consultation_end_time - pv.consultation_start_time).total_seconds() / 60.0
            duration_mins = max(2.0, min(duration_mins, 30.0)) # Clamp between 2 and 30 mins
            sum_weighted_time += (duration_mins * weight)
            sum_weights += weight
            
        if sum_weights > 0:
            avg_consultation_time = sum_weighted_time / sum_weights
            
    # 4. Determine remaining time for current patient
    currently_serving = db.query(models.PatientVisit).filter(
        models.PatientVisit.doctor_id == doctor_id,
        models.PatientVisit.visit_date == today,
        models.PatientVisit.status == "serving"
    ).first()
    
    remaining_time = 0
    if currently_serving and currently_serving.consultation_start_time:
         elapsed = (now - currently_serving.consultation_start_time).total_seconds() / 60.0
         remaining_time = max(0, avg_consultation_time - elapsed)
         
    # 5. Calculate final predicted wait time
    predicted_wait_time = int(remaining_time + ((position - 1) * avg_consultation_time))
    
    return {
        "patient_id": patient_id,
        "queue_position": position,
        "estimated_wait_time": predicted_wait_time
    }
