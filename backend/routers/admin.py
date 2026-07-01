from websocket_manager import manager
from fastapi import BackgroundTasks, APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
from database import SessionLocal
import models
import schemas
from pydantic import BaseModel
from security import RoleChecker, limiter
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

class ConfirmAdmissionRequest(BaseModel):
    bed_number: int

router = APIRouter(dependencies=[Depends(RoleChecker(['admin']))])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- ADD USER ----------------

@router.post("/addUser")
@limiter.limit("10/minute")
def add_user(request: Request, data: schemas.AddUserRequest, db: Session = Depends(get_db)):
    if data.role == "patient":
        raise HTTPException(
            status_code=400,
            detail="Patients should be added using addPatient API"
        )
    existing = db.query(models.User).filter(models.User.phone == data.phone).first()
    
    if data.role not in ["admin", "doctor"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    user = models.User(
        username=data.username,
        phone=data.phone,
        password=pwd_context.hash(data.password),
        role=data.role
    )

    db.add(user)
    db.commit()

    return {"message": "User created successfully"}


# ---------------- ADD DOCTOR ----------------

@router.post("/addDoctor")
@limiter.limit("10/minute")
def add_doctor(request: Request, data: schemas.AddDoctorRequest, db: Session = Depends(get_db)):
    
    existing_user = db.query(models.User).filter(models.User.phone == data.phone).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User with this phone number already exists")

    # 1. Create Login Account (User)
    user = models.User(
        username=data.name,
        phone=data.phone,
        password=pwd_context.hash(data.password),
        role="doctor"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 2. Create Doctor Profile linked to the new User
    doctor = models.Doctor(
        name=data.name,
        department=data.department,
        user_id=user.id
    )
    db.add(doctor)
    db.commit()

    return {"message": "Doctor and login account created successfully"}


# ---------------- WARDS & BEDS ----------------

@router.get("/wards")
def get_wards(db: Session = Depends(get_db)):
    wards = db.query(models.Ward).all()
    return [{"id": w.id, "name": w.name} for w in wards]

@router.get("/ward-bed-summary")
def ward_bed_summary(db: Session = Depends(get_db)):
    """Returns free/total bed counts per ward for admission request UI."""
    wards = db.query(models.Ward).all()
    result = []
    for w in wards:
        total = db.query(models.Bed).filter(models.Bed.ward_id == w.id).count()
        free = db.query(models.Bed).filter(
            models.Bed.ward_id == w.id,
            models.Bed.is_occupied == 0,
            models.Bed.status == "free"
        ).count()
        result.append({"id": w.id, "name": w.name, "free": free, "total": total})
    return result
@router.post("/addBed")
def add_bed(data: schemas.AddBedRequest, db: Session = Depends(get_db)):

    ward = db.query(models.Ward).filter(models.Ward.id == data.ward_id).first()
    if not ward:
        raise HTTPException(status_code=400, detail="Specified Ward does not exist")

    existing = db.query(models.Bed).filter(models.Bed.bed_number == data.bed_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bed already exists")

    bed = models.Bed(
        bed_number=data.bed_number,
        ward_id=ward.id,
        is_occupied=0,
        status="free"
    )

    db.add(bed)
    db.commit()

    return {"message": f"Bed #{bed.bed_number} added successfully to {ward.name}"}


# ---------------- ADMIN STATS ----------------

@router.get("/adminStats")
def admin_stats(db: Session = Depends(get_db)):

    today = datetime.now().strftime("%Y-%m-%d")

    total_patients_today = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date == today
    ).count()

    waiting = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date == today,
        models.PatientVisit.status == "waiting"
    ).count()

    serving = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date == today,
        models.PatientVisit.status == "serving"
    ).count()

    admitted = db.query(models.PatientVisit).filter(
        models.PatientVisit.status == "admitted"
    ).count()

    beds_available = db.query(models.Bed).filter(
        models.Bed.status == "free"
    ).count()

    total_doctors = db.query(models.Doctor).count()

    return {
        "total_patients_today": total_patients_today,
        "waiting": waiting,
        "serving": serving,
        "admitted": admitted,
        "beds_available": beds_available,
        "total_doctors": total_doctors
    }


# ---------------- ADMITTED PATIENTS ----------------

@router.get("/admittedPatients")
def admitted_patients(db: Session = Depends(get_db)):
    # Use is_occupied as the canonical source of truth
    beds = db.query(models.Bed).filter(models.Bed.is_occupied == 1).all()
    result = []
    for bed in beds:
        # Try bed.patient_id first, fallback to bed_id on PatientVisit
        patient = None
        if bed.patient_id:
            patient = db.query(models.PatientVisit).filter(
                models.PatientVisit.id == bed.patient_id
            ).first()
        if not patient:
            patient = db.query(models.PatientVisit).filter(
                models.PatientVisit.bed_id == bed.id,
                models.PatientVisit.status == "admitted"
            ).first()
        if patient:
            result.append({
                "visit_id":   patient.id,
                "name":       patient.name,
                "age":        patient.age,
                "problem":    patient.problem,
                "bed_number": bed.bed_number,
                "status":     patient.status,
            })
    return result

# ---------------- ADMISSION REQUESTS ----------------

@router.get("/admissionRequests")
def admission_requests(db: Session = Depends(get_db)):
    # Also fetch all wards to pass for manual override
    wards = db.query(models.Ward).all()
    ward_list = [{"id": w.id, "name": w.name} for w in wards]

    patients = db.query(models.PatientVisit).filter(
        models.PatientVisit.status == "admission_requested"
    ).all()
    
    result = []
    for p in patients:
        doc_name = "—"
        if p.doctor_id:
            doc = db.query(models.Doctor).filter(models.Doctor.id == p.doctor_id).first()
            if doc: doc_name = f"Dr. {doc.name}"
            
        result.append({
            "visit_id": p.id,
            "name": p.name,
            "age": p.age,
            "condition": p.condition,
            "doctor": doc_name,
            "suggested_bed": p.suggested_bed,
            "status": p.status
        })
    return {
        "requests": result,
        "wards": ward_list
    }

@router.post("/confirm-admission/{visit_id}")
def confirm_admission(visit_id: int, data: schemas.ConfirmAdmissionRequest, db: Session = Depends(get_db)):
    patient = db.query(models.PatientVisit).filter(
        models.PatientVisit.id == visit_id, 
        models.PatientVisit.status == "admission_requested"
    ).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Admission request not found")

    # Determine target ward
    target_ward = None
    if data.ward_id:
        target_ward = db.query(models.Ward).filter(models.Ward.id == data.ward_id).first()
    elif patient.suggested_bed:
        target_ward = db.query(models.Ward).filter(models.Ward.name == patient.suggested_bed).first()
        
    if not target_ward:
        raise HTTPException(status_code=400, detail="Ward not found for assignment")

    # Find first available bed in target ward
    bed = db.query(models.Bed).filter(
        models.Bed.ward_id == target_ward.id,
        models.Bed.is_occupied == 0,
        models.Bed.status == "free"
    ).first()
    
    if not bed:
        raise HTTPException(status_code=400, detail=f"No beds available in {target_ward.name}")

    # Mark as occupied
    bed.status = "occupied"
    bed.is_occupied = 1
    bed.patient_id = patient.id

    patient.status = "admitted"
    patient.bed_id = bed.id
    patient.suggested_bed = None # Clear suggestion
    
    db.commit()
    return {"message": f"Patient admitted to Bed #{bed.bed_number} in {target_ward.name}"}

# ---------------- WORKLOAD BALANCER ----------------

def get_least_busy_doctor(db: Session, today: str, dept: str = None):
    query = db.query(models.Doctor)
    if dept:
        query = query.filter(models.Doctor.department == dept)
    doctors = query.all()
    
    if not doctors:
        return None
        
    least_busy = None
    min_load = float('inf')
    
    for doc in doctors:
        # User Feedback #4: Count only status == "waiting" patients
        load = db.query(models.PatientVisit).filter(
            models.PatientVisit.doctor_id == doc.id,
            models.PatientVisit.visit_date == today,
            models.PatientVisit.status == "waiting"
        ).count()
        
        if load < min_load:
            min_load = load
            least_busy = doc
            
    return least_busy

@router.post("/auto-assign-doctor")
def auto_assign_doctor(data: schemas.AutoAssignDoctorRequest, db: Session = Depends(get_db)):
    patient = db.query(models.PatientVisit).filter(models.PatientVisit.id == data.patient_id).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient visit not found")
        
    if patient.status != "waiting":
         raise HTTPException(status_code=400, detail="Only waiting patients can be reassigned")

    today = datetime.now().strftime("%Y-%m-%d")
    least_busy = get_least_busy_doctor(db, today, dept=patient.department)
    
    if not least_busy:
        raise HTTPException(status_code=404, detail="No doctors available")
        
    patient.doctor_id = least_busy.id
    db.commit()
    
    # Also update Queue entry if exists, or create one
    queue_entry = db.query(models.Queue).filter(models.Queue.patient_id == patient.id).first()
    if queue_entry:
        queue_entry.doctor_id = least_busy.id
    else:
        new_q = models.Queue(patient_id=patient.id, doctor_id=least_busy.id)
        db.add(new_q)
        
    db.commit()
    
    return {
        "message": "Doctor automatically assigned",
        "assigned_doctor": f"Dr. {least_busy.name}",
        "doctor_id": least_busy.id
    }