from websocket_manager import manager
from fastapi import BackgroundTasks, APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from database import SessionLocal
import models
from pydantic import BaseModel
router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/search/{token_number}")
def search_prescription(token_number: int, db: Session = Depends(get_db)):
    from datetime import timedelta
    today_dt = datetime.now().date()
    yesterday_dt = today_dt - timedelta(days=1)
    dates = [today_dt.strftime("%Y-%m-%d"), yesterday_dt.strftime("%Y-%m-%d")]
    
    print(f"[DEBUG] Pharmacy search requested for token: {token_number} on dates: {dates}")
    
    # We query both today and yesterday to prevent timezone boundary issues
    visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.token_number == token_number,
        models.PatientVisit.visit_date.in_(dates)
    ).all()
    
    print(f"[DEBUG] Found {len(visits)} visits matching token {token_number}")
    
    if not visits:
        raise HTTPException(status_code=404, detail="No patient found with this token today")
        
    results = []
    docs = {d.id: d.name for d in db.query(models.Doctor).all()}
    
    for v in visits:
        prescriptions = []
        for p in v.prescriptions:
            prescriptions.append({
                "id": p.id,
                "medicine_name": p.medicine_name,
                "dosage": p.dosage,
                "duration": p.duration,
                "notes": p.notes,
                "is_dispensed": bool(p.is_dispensed)
            })
            
        print(f"[DEBUG] Visit ID: {v.id}, Patient: {v.name}, Status: {v.status}, Prescriptions Count: {len(prescriptions)}")
            
        # Display visits that have prescriptions OR have completed the consultation/admitted status
        if prescriptions or v.status in ["completed", "admission_requested", "admitted", "discharged", "serving"]:
            results.append({
                "visit_id": v.id,
                "token_number": v.token_number,
                "patient_name": v.name,
                "doctor_name": f"Dr. {docs.get(v.doctor_id, 'Unknown')}",
                "diagnosis": v.condition,
                "prescriptions": prescriptions
            })
            
    if not results:
        print(f"[DEBUG] Returning empty data for token {token_number}")
        return {"message": "No prescriptions found for this token", "data": []}
        
    print(f"[DEBUG] Returning {len(results)} results for token {token_number}")
    return {"message": "Prescriptions found", "data": results}

@router.get("/today")
def get_todays_prescriptions(db: Session = Depends(get_db)):
    from datetime import timedelta
    today_dt = datetime.now().date()
    yesterday_dt = today_dt - timedelta(days=1)
    dates = [today_dt.strftime("%Y-%m-%d"), yesterday_dt.strftime("%Y-%m-%d")]
    
    print(f"[DEBUG] Pharmacy today request for dates: {dates}")
    
    visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date.in_(dates)
    ).order_by(models.PatientVisit.id.desc()).all()
    
    results = []
    docs = {d.id: d.name for d in db.query(models.Doctor).all()}
    
    for v in visits:
        prescriptions = []
        for p in v.prescriptions:
            prescriptions.append({
                "id": p.id,
                "medicine_name": p.medicine_name,
                "dosage": p.dosage,
                "duration": p.duration,
                "notes": p.notes,
                "is_dispensed": bool(p.is_dispensed)
            })
            
        if prescriptions or v.status in ["completed", "admission_requested", "admitted", "discharged", "serving"]:
            results.append({
                "visit_id": v.id,
                "token_number": v.token_number,
                "patient_name": v.name,
                "doctor_name": f"Dr. {docs.get(v.doctor_id, 'Unknown')}",
                "diagnosis": v.condition,
                "prescriptions": prescriptions
            })
            
    if not results:
        return {"message": "No prescriptions found for today", "data": []}
        
    return {"message": "Prescriptions found", "data": results}

@router.post("/dispense/{prescription_id}")
def mark_dispensed(prescription_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    prescription = db.query(models.Prescription).filter(models.Prescription.id == prescription_id).first()
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")
        
    prescription.is_dispensed = 1
    db.commit()
    
    background_tasks.add_task(manager.broadcast_all, {"type": "update"})
    return {"success": True, "message": "Medicine marked as dispensed"}
