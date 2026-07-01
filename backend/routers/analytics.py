from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import io
import csv

from database import SessionLocal
import models
from security import RoleChecker

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(RoleChecker(['admin']))])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    today_date = datetime.now().date()
    today_iso = today_date.isoformat()

    # 1. Today Patients
    today_patients = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date == today_iso
    ).count()

    # 2. Bed Occupancy
    total_beds = db.query(models.Bed).count()
    occupied_beds = db.query(models.Bed).filter(models.Bed.status == "occupied").count()
    bed_occupancy = (occupied_beds / total_beds) if total_beds > 0 else 0

    # 3. Department Distribution (All time or today? Let's do all time for better pie chart, or just today)
    # Using all time to have more data
    dept_distribution = {}
    visits_with_dept = db.query(models.PatientVisit.department, func.count(models.PatientVisit.id)).group_by(models.PatientVisit.department).all()
    for dept, count in visits_with_dept:
        if dept:
            dept_distribution[dept] = count

    # 4. Last 7 Days History
    last_7_days = []
    counts_for_trend = []
    for i in range(6, -1, -1):
        d = (today_date - timedelta(days=i)).isoformat()
        count = db.query(models.PatientVisit).filter(models.PatientVisit.visit_date == d).count()
        last_7_days.append({"date": d, "count": count})
        counts_for_trend.append(count)

    # 5. Forecast Logic (Average + Trend)
    if sum(counts_for_trend) == 0:
        forecast_next_day = 0
    else:
        avg_load = sum(counts_for_trend) / len(counts_for_trend)
        trend = (counts_for_trend[-1] - counts_for_trend[0]) / len(counts_for_trend)
        forecast_next_day = max(0, int(avg_load + trend))

    # 6. Average Wait Time (Today's average or historical average)
    completed_visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.serving_time.isnot(None),
        models.PatientVisit.created_at.isnot(None)
    ).order_by(models.PatientVisit.id.desc()).limit(100).all()

    total_wait_mins = 0
    valid_visits = 0
    for v in completed_visits:
        if isinstance(v.serving_time, datetime) and isinstance(v.created_at, datetime):
            diff = (v.serving_time - v.created_at).total_seconds() / 60.0
            if diff >= 0:
                total_wait_mins += diff
                valid_visits += 1

    average_wait_time = int(total_wait_mins / valid_visits) if valid_visits > 0 else 0

    # 7. Alerts
    alerts = []
    waiting_now = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date == today_iso,
        models.PatientVisit.status == "waiting"
    ).count()

    if waiting_now > 20:
        alerts.append("Queue Alert: More than 20 patients currently waiting.")
    
    if bed_occupancy > 0.9:
        alerts.append("Capacity Alert: Bed occupancy is above 90%.")
    
    total_doctors = db.query(models.Doctor).count()
    # Assume a doc can see ~10 patients a day reasonably (adjusted for testing and better UX)
    if total_doctors > 0 and forecast_next_day > (total_doctors * 10):
        alerts.append("Staffing Alert: Forecasted patient load exceeds optimal doctor capacity for tomorrow.")

    return {
        "today_patients": today_patients,
        "bed_occupancy": bed_occupancy,
        "department_distribution": dept_distribution,
        "last_7_days": last_7_days,
        "forecast_next_day": forecast_next_day,
        "alerts": alerts,
        "average_wait_time": average_wait_time
    }

@router.get("/export")
def export_csv(db: Session = Depends(get_db)):
    visits = db.query(models.PatientVisit).all()

    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "patient_visit_id", "department", "arrival_time", 
        "serving_time", "completion_time", "discharge_time", "doctor_id"
    ])

    for v in visits:
        writer.writerow([
            v.id,
            v.department or "",
            v.created_at.isoformat() if isinstance(v.created_at, datetime) else str(v.created_at or ""),
            v.serving_time.isoformat() if isinstance(v.serving_time, datetime) else str(v.serving_time or ""),
            v.completion_time.isoformat() if isinstance(v.completion_time, datetime) else str(v.completion_time or ""),
            v.discharge_time.isoformat() if isinstance(v.discharge_time, datetime) else str(v.discharge_time or ""),
            v.doctor_id or ""
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=patient_analytics_export.csv"}
    )

@router.get("/forecast")
def get_forecast(db: Session = Depends(get_db)):
    today_date = datetime.now().date()
    start_date = today_date - timedelta(days=28)
    start_iso = start_date.isoformat()
    
    # Needs to be extracted from DB
    visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date >= start_iso
    ).all()
    
    # Group by weekday (0=Monday, 6=Sunday)
    weekday_counts = {i: 0 for i in range(7)}
    for v in visits:
        if v.visit_date:
            try:
                date_obj = datetime.strptime(v.visit_date, "%Y-%m-%d").date()
                weekday = date_obj.weekday()
                weekday_counts[weekday] += 1
            except ValueError:
                pass
                
    # Average over 4 weeks
    weekday_avg = {i: int(count / 4) for i, count in weekday_counts.items()}
    
    forecast = []
    # Predict next 7 days
    for i in range(1, 8):
        next_date = today_date + timedelta(days=i)
        next_weekday = next_date.weekday()
        forecast.append({
            "date": next_date.isoformat(),
            "predicted_count": weekday_avg[next_weekday]
        })
        
    return forecast

@router.get("/hourly-heatmap")
def get_hourly_heatmap(db: Session = Depends(get_db)):
    today_date = datetime.now().date()
    start_date = today_date - timedelta(days=7)
    
    visits = db.query(models.PatientVisit).filter(
        models.PatientVisit.created_at >= datetime.combine(start_date, datetime.min.time())
    ).all()
    
    hour_counts = {i: 0 for i in range(24)}
    for v in visits:
        if v.created_at:
            hour_counts[v.created_at.hour] += 1
            
    # Average over 7 days
    hourly_avg = [{"hour": hour, "avg_count": count / 7.0} for hour, count in hour_counts.items()]
    return hourly_avg

@router.get("/bed-forecast")
def get_bed_forecast(db: Session = Depends(get_db)):
    today_date = datetime.now().date()
    start_date = today_date - timedelta(days=7)
    
    # Find all admissions in the last 7 days
    # In sqlite, status could have been updated, so we count records where status='admitted' or bed_id is not null?
    # Actually, we can just look at visit_date for patients who actually got admitted (status='admitted' or 'discharged')
    # Or just average overall status='admitted' and 'discharged' in last 7 days.
    # Alternatively, use visit_date >= start_date + status processing
    past_admissions = db.query(models.PatientVisit).filter(
        models.PatientVisit.visit_date >= start_date.isoformat(),
        models.PatientVisit.bed_id.isnot(None)
    ).count()
    
    predicted_admissions = max(1, int(past_admissions / 7.0))
    
    total_beds = db.query(models.Bed).count()
    occupied_beds = db.query(models.Bed).filter(models.Bed.is_occupied == 1).count()
    current_free_beds = max(0, total_beds - occupied_beds)
    
    risk_level = "🟢 Low Risk"
    if current_free_beds < predicted_admissions:
        risk_level = "🔴 High Risk"
    elif current_free_beds - predicted_admissions <= 2:
        risk_level = "🟡 Medium Risk"
        
    return {
        "predicted_admissions": predicted_admissions,
        "current_free_beds": current_free_beds,
        "risk_level": risk_level
    }
