from websocket_manager import manager
from fastapi import BackgroundTasks, APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from database import SessionLocal
import models
from pydantic import BaseModel
from security import RoleChecker

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"], dependencies=[Depends(RoleChecker(['admin', 'doctor']))])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/search/{token_number}")
def search_prescription(token_number: int, db: Session = Depends(get_db)):
    today = datetime.utcnow().date().isoformat()
    
    # We might have multiple visits with the same token number (different doctors),
    # but the token number + today usually identifies a few. We should return all today's prescriptions for this token.
    visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.token_number == token_number,
        models.PatientVisit.visit_date == today
    ).all()
    
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
            
        if prescriptions:
            results.append({
                "visit_id": v.id,
                "patient_name": v.name,
                "doctor_name": f"Dr. {docs.get(v.doctor_id, 'Unknown')}",
                "diagnosis": v.diagnosis,
                "prescriptions": prescriptions
            })
            
    if not results:
        return {"message": "No prescriptions found for this token", "data": []}
        
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
