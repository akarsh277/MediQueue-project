from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, Text, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column
from typing import List
from datetime import datetime
from database import Base, SafeDateTime


# ---------------- USERS TABLE ----------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    phone = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    age = Column(Integer, default=0)
    created_at = Column(SafeDateTime, default=datetime.utcnow)

    doctor = relationship("Doctor", back_populates="user", uselist=False)
    visits = relationship("PatientVisit", back_populates="user")

# ---------------- DOCTORS TABLE ----------------

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    department = Column(String, nullable=False)
    is_available = Column(Boolean, default=True)
    daily_cap = Column(Integer, default=40)
    user_id = Column(Integer, ForeignKey("users.id"))

    user = relationship("User", back_populates="doctor")
    patients = relationship("PatientVisit", back_populates="doctor")


# ---------------- PATIENT VISIT TABLE ----------------

class PatientVisit(Base):
    __tablename__ = "patient_visits"

    __table_args__ = (
        UniqueConstraint('doctor_id', 'visit_date', 'token_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    age = Column(Integer)
    problem = Column(String)
    doctor_id = Column(Integer, ForeignKey("doctors.id"))

    priority = Column(Integer)
    status = Column(String, index=True)
    visit_date = Column(String, index=True)

    token_number = Column(Integer)

    created_at = Column(SafeDateTime, default=datetime.utcnow)
    
    # Analytics fields
    department = Column(String, index=True)
    serving_time = Column(SafeDateTime)
    completion_time = Column(SafeDateTime)
    discharge_time = Column(SafeDateTime)

    # Intelligent features fields
    condition = Column(String)
    diagnosis = Column(String, nullable=True)
    suggested_bed = Column(String)
    consultation_start_time = Column(SafeDateTime)
    consultation_end_time = Column(SafeDateTime)
    bed_id = Column(Integer, ForeignKey("beds.id"), nullable=True)

    user        = relationship("User", back_populates="visits", foreign_keys=[user_id])
    doctor     = relationship("Doctor", back_populates="patients", foreign_keys=[doctor_id])
    queue_entry = relationship("Queue", back_populates="patient", uselist=False)
    bed_assigned = relationship("Bed", back_populates="admitted_patient", foreign_keys=[bed_id])
    prescriptions = relationship("Prescription", back_populates="visit", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="visit", cascade="all, delete-orphan")

# ---------------- QUEUE TABLE ----------------

class Queue(Base):
    __tablename__ = "queue"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_visits.id"))
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    source = Column(String, default="hospital")
    created_at = Column(SafeDateTime, default=datetime.utcnow)

    patient = relationship("PatientVisit", back_populates="queue_entry")
    doctor  = relationship("Doctor")


# ---------------- WARDS TABLE ----------------

class Ward(Base):
    __tablename__ = "wards"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False) # ICU, General Ward, Normal Ward
    
    beds = relationship("Bed", back_populates="ward")


# ---------------- BEDS TABLE ----------------

class Bed(Base):
    __tablename__ = "beds"

    id = Column(Integer, primary_key=True, index=True)
    bed_number = Column(Integer, unique=True, nullable=False)
    status = Column(String, default="free")  # free / occupied (Legacy)
    patient_id = Column(Integer, ForeignKey("patient_visits.id"), nullable=True) # Legacy
    
    ward_id = Column(Integer, ForeignKey("wards.id"), nullable=True)
    is_occupied = Column(Integer, default=False)  # Stored as integer pseudo-boolean in sqlite

    ward = relationship("Ward", back_populates="beds")
    admitted_patient = relationship("PatientVisit", back_populates="bed_assigned", foreign_keys=[PatientVisit.bed_id])


# ---------------- MESSAGES TABLE ----------------

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_role = Column(String, nullable=False)   # 'doctor' | 'admin'
    sender_id   = Column(Integer, nullable=False)  # user_id of sender
    message     = Column(Text, nullable=False)
    timestamp   = Column(SafeDateTime, default=datetime.utcnow)

# ---------------- PRESCRIPTIONS TABLE ----------------

class Prescription(Base):
    __tablename__ = "prescriptions"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("patient_visits.id"))
    medicine_name = Column(String, nullable=False)
    dosage = Column(String, nullable=False)
    duration = Column(String, nullable=False)
    notes = Column(String)
    is_dispensed = Column(Integer, default=False) # store boolean as integer
    created_at = Column(SafeDateTime, default=datetime.utcnow)

    visit = relationship("PatientVisit", back_populates="prescriptions")


# ---------------- REPORTS TABLE ----------------

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("patient_visits.id"))
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    uploaded_at = Column(SafeDateTime, default=datetime.utcnow)

    visit = relationship("PatientVisit", back_populates="reports")