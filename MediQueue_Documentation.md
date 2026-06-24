# MediQueue: Comprehensive Technical & Architectural Documentation

## 1. Executive Summary
MediQueue is an intelligent, high-performance Smart Hospital Management and Queue System. It transforms traditional First-Come-First-Serve (FCFS) triage into a dynamic, priority-based mechanism that optimizes patient wait times, intelligently distributes workload among doctors, and forecasts future resource bottlenecks for hospital administrators. 

Built on a robust Python FastAPI backend and a lightweight, zero-build vanilla web frontend, it seamlessly handles walk-in registrations, remote home bookings, clinical consultations, pharmaceutical dispensaries, and inpatient bed assignments.

---

## 2. Core Engine & Algorithms (Deep Dive)
The true power of MediQueue lies in its automated logic running behind the scenes.

### 2.1 Priority Scoring Algorithm
MediQueue recalculates patient order continuously using a weighted formula. This ensures critical emergencies are immediately escalated without indefinitely postponing non-critical patients (starvation prevention).

**Formula**: `Score = (Emergency Value * 5) + Senior Value + (Wait Duration in Minutes / 10.0)`

*   **Emergency Value**: `1` if marked Emergency (Priority 1), else `0`.
*   **Senior Value**: `2` if patient age > 60, else `0`.
*   **Wait Duration Engine**: The wait time continuously ticks upwards from `created_at`. This means an older normal-priority patient will gradually accumulate enough score to surpass a newly arrived higher-priority patient. (Includes a robust safety fallback to `0` wait time if a timestamp is ever null or malformed, mathematically preventing queue crashes).

### 2.2 Dynamic Wait-Time Estimation
Patient wait times are not static. The system calculates real-time estimated wait times based on historical throughput.
*   **Averaging Metric**: The engine fetches the last `5` completed consultation durations for the specific doctor (using `consultation_start_time` and `consultation_end_time`).
*   **Weighted Average**: More recent consultations are given a higher weight (e.g., the 5th most recent consultation has weight 1, the most recent has weight 5) to react faster to sudden slowdowns.
*   **Wait Time Formula**: `Remaining Time of Current Serving Patient + ((Queue Position - 1) * Weighted Average Consultation Time)`.

### 2.3 Predictive Analytics & Forecasting
The `/analytics` module crunches historical data to forecast upcoming challenges.
*   **Next Day Patient Forecast**: Averages patient load over the past 4 weeks, grouped by weekday, to project tomorrow's arrivals.
*   **Bed Availability Risk Levels**: Analyzes daily admission thresholds over the past week to predict upcoming admission requests. It compares these predictions against currently `free` beds to trigger alarms: `🟢 Low Risk`, `🟡 Medium Risk`, or `🔴 High Risk`.
*   **Hourly Heatmaps**: Averages patient arrival times (`created_at`) across the last 7 days to generate 24-hour distribution curves, helping admins schedule shift handovers.

### 2.4 Workload Balancer
When administrators trigger `/admin/auto-assign-doctor`, the system evaluates all doctors in the required department. It counts the number of `waiting` patients currently assigned to each doctor and reassigns the patient to the doctor with the absolute lowest load.

---

## 3. Database Architecture & Schema

MediQueue utilizes SQLite managed via SQLAlchemy ORM, designed for fast transaction processing and relational integrity.

### 3.1 Tables Overview
*   **Users (`users`)**: Central authentication entity. Tracks `role` (patient, doctor, admin), `phone` (unique), and encrypted `password`.
*   **Doctors (`doctors`)**: Linked to `Users`. Tracks professional `name`, `department`, `is_available` status (persisted across reboots), and configurable `daily_cap` for patient limits.
*   **PatientVisit (`patient_visits`)**: The core transactional heavyweight table.
    *   Tracks state transitions: `waiting` -> `serving` -> `completed` / `admission_requested` -> `admitted` -> `discharged` / `cancelled`.
    *   Maintains strict timestamping: `created_at`, `serving_time`, `consultation_start_time`, `consultation_end_time`, `completion_time`, `discharge_time`.
*   **Queue (`queue`)**: An auxiliary table storing active queue relationships and the `source` (e.g., 'hospital', 'home').
*   **Wards & Beds (`wards`, `beds`)**: Manages physical capacity. Beds track `status` ('free', 'occupied') and an `is_occupied` boolean integer flag.
*   **Messages (`messages`)**: A robust internal communication ledger tracking messages between doctors and the reception/admin.
*   **Prescriptions (`prescriptions`)**: Linked to `PatientVisit`. Stores `medicine_name`, `dosage`, `duration`, `notes`, and an `is_dispensed` flag.
*   **Reports (`reports`)**: Tracks file uploads (PDFs, Images) tied to specific visits, storing the physical `file_path`.

---

## 4. API Endpoints Reference

The backend is strictly modularized across various FastAPI Routers.

### 4.1 Authentication & Security (`/routers/auth.py` & `/security.py`)
*   **JWT Middleware**: All protected endpoints (patient home, doctor portal, admin panel) enforce JWT (JSON Web Token) Bearer authentication via a `get_current_user` dependency. 
*   **Unauthorized Access**: Requests without a valid Bearer token immediately return a `401 Unauthorized` response.
*   `POST /login`: Authenticates users (Username or Phone + Password). Generates and returns a signed JWT `access_token`, along with the `user_id` and `role`.
*   `POST /register/patient`: Public endpoint for patient self-registration.

### 4.2 Patient Workflows (`/routers/patient.py`)
*   `POST /addPatient`: Admin/Reception endpoint to walk-in a patient. Generates a token and calculates priority based on age/emergency flags.
*   `GET /me/{user_id}`: Retrieves patient profile details.
*   `POST /book-home/{user_id}`: Allows registered patients to self-book appointments from home. Enforces the doctor's specific `daily_cap` limit dynamically.
*   `GET /check-phone/{phone}`: Quick lookup to see if a walk-in patient exists in the system.
*   `GET /patient-history/{phone}`: Retrieves past visits, prescriptions, and reports.
*   `GET /predict-wait-time/{patient_id}`: Returns dynamically calculated queue position and ETA.
*   `POST /uploads/{visit_id}`: Uploads medical reports/documents via Cloud Object Storage (S3-compatible utilizing `boto3`), safely falling back to local storage if AWS keys are not configured.
*   `POST /cancel/{visit_id}`: Cancels a 'waiting' appointment.

### 4.3 Doctor Workflows (`/routers/doctor.py`)
*   `GET /doctors`: Lists all doctors and their real-time `is_available` status.
*   `GET /queue/{doctor_id}`: The core doctor view. Returns the priority-sorted queue for today.
*   `POST /nextPatient/{doctor_id}`: Moves the top priority patient from `waiting` to `serving` and initiates the `consultation_start_time`.
*   `POST /push-back/{visit_id}`: Returns a serving patient to the waiting pool (if they need to use the washroom, get a test, etc.).
*   `POST /skipPatient/{visit_id}`: Skips a waiting patient (who may be unresponsive), dropping them lower in the queue.
*   `POST /completePatient/{visit_id}`: Marks a visit successfully complete.
*   `POST /request-admission/{visit_id}`: Changes status to `admission_requested` and suggests a bed type based on patient condition and age.
*   `POST /prescription/{visit_id}`: Attaches diagnoses and multiple medicine lines to a visit.
*   `POST /toggle-availability`: Sets the doctor online/offline, blocking new bookings. This state is durably persisted to the database.
*   `GET /patientDetails/{visit_id}`: Deep dive into a patient's historical records.

### 4.4 Admin & Operations (`/routers/admin.py`)
*   `GET /adminStats`: Live dashboard figures (Total patients, Waiting, Serving, Admitted, Beds Free).
*   `GET /ward-bed-summary`: Detailed view of capacity across ICU, General, and Normal wards.
*   `GET /admissionRequests`: Lists all patients needing beds.
*   `POST /confirm-admission/{visit_id}`: Overrides or accepts doctor suggestions, searches for the first available bed in the target ward, and assigns it.
*   `POST /auto-assign-doctor`: Triggers the Workload Balancer logic.
*   `POST /addDoctor` / `POST /addUser` / `POST /addBed`: Entity creation endpoints.

### 4.5 Analytics & BI (`/routers/analytics.py`)
*   `GET /analytics/dashboard`: Aggregates 7-day histories, department pie distributions, and triggers operational alerts if queues are > 20 or beds > 90% full.
*   `GET /analytics/forecast`: Weekday averaged projections.
*   `GET /analytics/hourly-heatmap`: Arrival distribution across 24 hours.
*   `GET /analytics/bed-forecast`: Capacity risk analysis.
*   `GET /analytics/export`: Downloads full patient histories as an exportable `.csv` file.

### 4.6 Pharmacy (`/routers/pharmacy.py`)
*   `GET /pharmacy/search/{token_number}`: Looks up today's prescriptions by token number.
*   `POST /pharmacy/dispense/{prescription_id}`: Flags a specific medication as physically dispensed to the patient.

### 4.7 Real-Time WebSockets
*   `ws://localhost:8000/ws`: Real-time bidirectional connection endpoint for frontend updates. Replaces legacy HTTP polling. Authenticates via JWT token query parameter (or bypasses for public `display` dashboards). Broadcasts events like patient admissions, queue movements, and new messages instantly across all connected clients.

---

## 5. Technical Stack & Directory Layout

**Backend**
*   **FastAPI**: Asynchronous Python API.
*   **SQLAlchemy + SQLite**: Database Management.
*   **Pydantic**: Deep request body validation and constraint checking.
*   **JWT (JSON Web Tokens)**: Cryptographic token generation for stateless API security.

**Frontend**
*   **Vanilla HTML5 / CSS3 / JS**: Zero build-step requirement.
*   **Progressive Web App (PWA)**: Installable via `manifest.json` and a Service Worker (`sw.js`) for a native desktop/mobile app feel.
*   **CSS Glassmorphism**: Utilizes CSS variables in `style.css` for a unified modern aesthetic.
*   **Fetch API & WebSockets**: Asynchronous HTTP calls combined with real-time WebSockets to the FastAPI backend.

**Directory Structure**
```
c:\projects\MediQueue
│
├── frontend/                     
│   ├── admin.html                # High-level operations & analytics
│   ├── doctor.html               # Queue management & consultation
│   ├── patient.html              # Walk-in registration
│   ├── patient_dashboard.html    # Home booking & ETA viewer
│   ├── display.html              # TV Lobby Queue Monitor
│   ├── pharmacy.html             # Prescription dispensing
│   ├── style.css                 
│   ├── script.js                 # Contains MQWebSocketManager
│   ├── manifest.json             # Web App Manifest for PWA installability
│   └── sw.js                     # Service Worker for PWA
│
├── backend/                      
│   ├── main.py                   # App startup, WebSockets setup & Automatic DB Seeding
│   ├── database.py               # SQLite Engine configuration
│   ├── models.py                 # SQLAlchemy schemas
│   ├── schemas.py                # Pydantic models
│   ├── security.py               # JWT generation and role validation
│   ├── websocket_manager.py      # ConnectionManager for handling live WebSockets
│   ├── routers/                  
│   │   ├── admin.py, analytics.py, auth.py, doctor.py, patient.py, pharmacy.py
│   └── uploads/                  # Local storage for Medical Reports
│
├── mediqueue.db                  # Auto-generated database
└── MediQueue_Documentation.md    # This master document
```

---

## 6. How To Run The Project

### Step 1: Start the Backend Service
1. Open a terminal and navigate to the backend folder: `cd c:\projects\MediQueue\backend`
2. Run the uvicorn development server: 
   ```bash
   uvicorn main:app --reload --port 8000
   ```
*(The backend runs on `http://127.0.0.1:8000`. Interactive Swagger UI Docs are generated automatically at `http://127.0.0.1:8000/docs`)*

### Step 2: Serve the Frontend Portal
1. Open a new terminal and navigate to the frontend directory: `cd c:\projects\MediQueue\frontend`
2. Serve static files using Python's built-in HTTP server:
   ```bash
   python -m http.server 3000
   ```
3. Access the interfaces via a web browser:
   * **Login/Gatekeeper**: `http://localhost:3000/login.html`
   * **Doctor Portal**: `http://localhost:3000/doctor.html`
   * **Admin Hub**: `http://localhost:3000/admin.html`
   * **Patient Home**: `http://localhost:3000/patient_dashboard.html`