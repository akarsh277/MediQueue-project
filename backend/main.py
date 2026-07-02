from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from websocket_manager import manager
from security import SECRET_KEY, ALGORITHM
import jwt
from database import engine, Base, SessionLocal
import models
from routers import auth
from routers import patient
from routers import doctor
from routers import admin
from routers import analytics
from routers import pharmacy
from datetime import datetime
from sqlalchemy import text as sa_text
from fastapi.staticfiles import StaticFiles
import os

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from security import limiter


def _startup_db_seed():
    """
    Fix legacy bad data and ensure an admin account exists.
    Runs once at startup inside uvicorn's own process (no external lock issues).
    """
    db = SessionLocal()
    now = datetime.utcnow().isoformat()
    try:
        from database import IS_SQLITE
        # 1. Fix empty-string created_at values (cause of str_to_datetime crash)
        if IS_SQLITE:
            for table in ("users", "patient_visits", "queue"):
                db.execute(sa_text(
                    f"UPDATE {table} SET created_at = :now "
                    f"WHERE created_at = '' OR created_at IS NULL"
                ), {"now": now})
        else:
            for table in ("users", "patient_visits", "queue"):
                db.execute(sa_text(
                    f"UPDATE {table} SET created_at = :now "
                    f"WHERE created_at IS NULL"
                ), {"now": now})

        # 2. Fix admin user role if incorrectly set
        db.execute(sa_text(
            "UPDATE users SET role = 'admin' WHERE username = 'admin' AND role != 'admin'"
        ))

        # 3. Seed default admin if none exists
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
        
        admin_exists = db.query(models.User).filter(
            models.User.username == "admin"
        ).first()
        if not admin_exists:
            db.add(models.User(
                username="admin",
                phone="0000000000",
                password=pwd_context.hash("admin123"),
                role="admin",
            ))
        else:
            # If the admin was already created but the password isn't hashed, fix it
            if admin_exists.password and not admin_exists.password.startswith(("$pbkdf2", "$2b$", "$2a$")):
                admin_exists.password = pwd_context.hash(admin_exists.password)
            
        demo_admin_exists = db.query(models.User).filter(
            models.User.username == "demo_admin"
        ).first()
        if not demo_admin_exists:
            db.add(models.User(
                username="demo_admin",
                phone="9999999999",
                password=pwd_context.hash("demoadmin123"),
                role="admin",
            ))
            
        # 4. Seed Wards
        ward_names = ["ICU", "General Ward", "Normal Ward"]
        wards_dict = {}
        for w_name in ward_names:
            ward = db.query(models.Ward).filter(models.Ward.name == w_name).first()
            if not ward:
                ward = models.Ward(name=w_name)
                db.add(ward)
            wards_dict[w_name] = ward
        
        db.commit() # Commit wards to get their IDs
        
        # 5. Seed Beds if completely empty
        if db.query(models.Bed).count() == 0:
            icu = db.query(models.Ward).filter(models.Ward.name == "ICU").first()
            gen = db.query(models.Ward).filter(models.Ward.name == "General Ward").first()
            nor = db.query(models.Ward).filter(models.Ward.name == "Normal Ward").first()
            
            # ICU beds (1, 2, 3)
            if icu:
                for i in range(1, 4): db.add(models.Bed(bed_number=i, ward_id=icu.id))
            # General beds (4, 5)
            if gen:
                for i in range(4, 6): db.add(models.Bed(bed_number=i, ward_id=gen.id))
            # Normal beds (6, 7)
            if nor:
                for i in range(6, 8): db.add(models.Bed(bed_number=i, ward_id=nor.id))

        db.commit()
        
        # 6. Fix bed status/is_occupied mismatch
        # Ensure beds that say 'occupied' but no patient is linked are freed
        from sqlalchemy import text as _t
        db.execute(_t(
            "UPDATE beds SET status='free', is_occupied=0 "
            "WHERE is_occupied=1 AND (patient_id IS NULL OR patient_id NOT IN "
            "(SELECT id FROM patient_visits WHERE status='admitted'))"
        ))
        # Ensure beds that have an admitted patient are marked occupied
        db.execute(_t(
            "UPDATE beds SET status='occupied', is_occupied=1 "
            "WHERE patient_id IN (SELECT id FROM patient_visits WHERE status='admitted')"
        ))
        db.commit()

        # 7. Auto-complete stale "serving" patients from previous days
        today = datetime.now().strftime("%Y-%m-%d")
        stale = db.execute(_t(
            "UPDATE patient_visits SET status='completed', "
            "completion_time=:now "
            "WHERE status='serving' AND visit_date < :today"
        ), {"now": now, "today": today})
        if stale.rowcount > 0:
            print(f"[INFO] Auto-completed {stale.rowcount} stale serving patient(s) from previous days.")
        db.commit()

        print("[INFO] DB startup check complete.")
    except Exception as e:
        print(f"[WARN] DB startup check warning: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────
    Base.metadata.create_all(bind=engine)
    _startup_db_seed()
    os.makedirs(os.path.join(os.path.dirname(__file__), "uploads", "reports"), exist_ok=True)
    yield
    # ── Shutdown (nothing needed) ─────────────────────────────


app = FastAPI(lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",  # allow all origins via regex for development with credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(patient.router)
app.include_router(doctor.router)
app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(pharmacy.router)

# Mount static files for uploads
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.get("/")
def read_root():
    return {"message": "MediQueue Backend Running"}

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "MediQueue Backend",
        "version": "1.0"
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    if not token:
        await websocket.close(code=1008)
        return
    if token == 'display':
        role = 'display'
        user_id = 0
    else:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload.get("sub"))
            role = payload.get("role")
        except jwt.PyJWTError:
            await websocket.close(code=1008)
            return

    await manager.connect(websocket, role, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            # We can handle incoming messages here if needed, 
            # currently we mostly push data to clients.
    except WebSocketDisconnect:
        manager.disconnect(websocket, role, user_id)