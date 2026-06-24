from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import SessionLocal
import models
import schemas
from fastapi import Request
from security import limiter, create_access_token
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

router = APIRouter()


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, data: schemas.LoginRequest, db: Session = Depends(get_db)):

    user = db.query(models.User).filter(
        or_(
            models.User.username == data.username,
            models.User.phone == data.username
        )
    ).first()

    if not user or not pwd_context.verify(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    access_token = create_access_token(data={"sub": str(user.id), "role": user.role})

    return {
        "message": "Login successful",
        "user_id": user.id,
        "role": user.role,
        "access_token": access_token
    }

@router.post("/register/patient")
@limiter.limit("5/minute")
def register_patient(request: Request, data: schemas.PatientRegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.phone == data.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already registered")
    
    new_user = models.User(
        username=data.username,
        phone=data.phone,
        password=data.password,
        role="patient",
        age=data.age
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {
        "message": "Registration successful",
        "user_id": new_user.id,
        "role": new_user.role
    }