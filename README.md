<div align="center">
  
# MediQueue

**Intelligent Smart Hospital Management & Priority-Based Queue System**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![SQLite](https://img.shields.io/badge/SQLite-07405E?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)

</div>

## 📖 Overview

**MediQueue** transforms traditional First-Come-First-Serve (FCFS) triage into a dynamic, priority-based mechanism that optimizes patient wait times, intelligently distributes workload among doctors, and forecasts future resource bottlenecks for hospital administrators.

Built on a robust Python FastAPI backend and a lightweight, zero-build vanilla web frontend (PWA), it seamlessly handles walk-in registrations, remote home bookings, clinical consultations, pharmaceutical dispensaries, and inpatient bed assignments.

## ✨ Key Features

*   **Priority Scoring Algorithm**: Dynamically calculates patient priority based on age, emergency status, and waiting duration to prevent queue starvation while escalating emergencies.
*   **Real-Time Wait Estimations**: Predicts waiting times using weighted historical consultation throughput data.
*   **Workload Balancer**: Automatically reassigns patients to doctors with the lowest load to optimize throughput.
*   **Predictive Analytics**: Forecasts patient influx, bed availability risks, and generates 24-hour arrival distribution heatmaps.
*   **Progressive Web App (PWA)**: Installable, fast, and responsive frontend built with Vanilla JS and CSS Glassmorphism.
*   **Real-Time WebSockets**: Live bidirectional updates for queue movements, bed availability, and messages without HTTP polling.
*   **Secure Ecosystem**: Role-based access control (Admin, Doctor, Patient) backed by JWT authentication.

## 🏗 Architecture

**Backend Stack**:
*   **FastAPI**: Asynchronous Python API.
*   **SQLAlchemy + SQLite**: Database Management.
*   **Pydantic**: Deep request body validation.
*   **JWT & WebSockets**: Stateless API security and live updates.

**Frontend Stack**:
*   **Vanilla HTML5 / CSS3 / JS**: Zero build-step requirement.
*   **PWA**: Service Worker (`sw.js`) and Manifest for a native feel.

## 🚀 Installation & Setup

Follow these steps to run MediQueue locally:

### 1. Clone the Repository
```bash
git clone https://github.com/akarsh277/Mediqueue-project.git
cd Mediqueue-project
```

### 2. Set Up the Backend
We recommend using a virtual environment for Python dependencies to avoid conflicts.
```bash
# Navigate to the backend directory
cd backend

# Create and activate a virtual environment (optional but recommended)
python -m venv venv
# On Windows: venv\Scripts\activate
# On Mac/Linux: source venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

### 3. Run the Backend Service
```bash
uvicorn main:app --reload --port 8000
```
> The API will run on `http://127.0.0.1:8000`. 
> Swagger Interactive Docs are available at `http://127.0.0.1:8000/docs`.

### 4. Start the Frontend
Open a new terminal session and navigate to the frontend folder:
```bash
cd frontend

# Serve static files using Python
python -m http.server 3000
```
> Access the application portals via browser:
> *   **Login Portal**: `http://localhost:3000/login.html`
> *   **Admin Dashboard**: `http://localhost:3000/admin.html`
> *   **Doctor Portal**: `http://localhost:3000/doctor.html`
> *   **Patient Portal**: `http://localhost:3000/patient_dashboard.html`

## 📚 Documentation
For an in-depth understanding of the algorithms, database schema, and detailed API documentation, please refer to the [MediQueue Documentation](MediQueue_Documentation.md).