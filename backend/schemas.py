from pydantic import BaseModel, StringConstraints, field_validator
from typing import Annotated
import re

class LoginRequest(BaseModel):
    username: str
    password: str

class AddPatientRequest(BaseModel):
    phone: Annotated[str, StringConstraints(pattern=r'^\+?[0-9]{10,15}$')]
    name: str
    age: int
    problem: str
    doctor_id: int
    is_emergency: bool = False
    password: str | None = "patient123"

    @field_validator('age')
    @classmethod
    def age_must_be_valid(cls, v):
        if v <= 0 or v > 120:
            raise ValueError('Age must be between 1 and 120')
        return v

    @field_validator('name')
    @classmethod
    def name_must_be_valid(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError('Name must be at least 2 characters')
        if not re.match(r'^[A-Za-z\s.]+$', v):
            raise ValueError('Name can only contain letters, spaces, and dots')
        return v

    @field_validator('problem')
    @classmethod
    def problem_must_be_valid(cls, v):
        if len(v.strip()) < 3:
            raise ValueError('Problem description must be at least 3 characters')
        return v.strip()

class AddUserRequest(BaseModel):
    username: str
    phone: Annotated[str, StringConstraints(pattern=r'^\+?[0-9]{10,15}$')]
    password: Annotated[str, StringConstraints(min_length=6)]
    role: str

class AddDoctorRequest(BaseModel):
    name: str
    department: str
    phone: Annotated[str, StringConstraints(pattern=r'^\+?[0-9]{10,15}$')]
    password: str

    @field_validator('name')
    @classmethod
    def name_must_be_valid(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError('Doctor name must be at least 2 characters')
        if not re.match(r'^[A-Za-z\s.]+$', v):
            raise ValueError('Doctor name can only contain letters, spaces, and dots')
        return v

    @field_validator('department')
    @classmethod
    def dept_must_be_valid(cls, v):
        if len(v.strip()) < 2:
            raise ValueError('Department must be at least 2 characters')
        return v.strip()

    @field_validator('password')
    @classmethod
    def password_must_be_valid(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v


class AddBedRequest(BaseModel):
    bed_number: int
    ward_id: int

    @field_validator('bed_number')
    @classmethod
    def bed_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Bed number must be 1 or greater')
        return v

class RequestAdmissionRequest(BaseModel):
    condition: str

class ConfirmAdmissionRequest(BaseModel):
    bed_number: int | None = None
    ward_id: int | None = None

class AutoAssignDoctorRequest(BaseModel):
    patient_id: int

class ToggleAvailabilityRequest(BaseModel):
    is_available: bool

class PatientRegisterRequest(BaseModel):
    username: Annotated[str, StringConstraints(min_length=2, max_length=50, pattern=r'^[A-Za-z\s.]+$')]
    phone: Annotated[str, StringConstraints(pattern=r'^\+?[0-9]{10,15}$')]
    password: Annotated[str, StringConstraints(min_length=6)]
    age: int

    @field_validator('age')
    @classmethod
    def age_must_be_valid(cls, v):
        if v <= 0 or v > 120:
            raise ValueError('Age must be between 1 and 120')
        return v

class HomeBookingRequest(BaseModel):
    doctor_id: int
    problem: str
    is_emergency: bool = False

    @field_validator('problem')
    @classmethod
    def problem_must_be_valid(cls, v):
        if len(v.strip()) < 3:
            raise ValueError('Problem description must be at least 3 characters')
        return v.strip()

class PrescriptionCreateRequest(BaseModel):
    medicine_name: str
    dosage: str
    duration: str
    notes: str | None = None

class CompleteConsultationRequest(BaseModel):
    diagnosis: str | None = None
    prescriptions: list[PrescriptionCreateRequest] = []
