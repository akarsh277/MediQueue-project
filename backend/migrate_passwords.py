from database import SessionLocal
import models
from passlib.context import CryptContext

# Use pbkdf2_sha256 instead of bcrypt to avoid passlib bcrypt 4.x compatibility bugs
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def migrate():
    db = SessionLocal()
    users = db.query(models.User).all()
    count = 0
    for user in users:
        # Check if already hashed (pbkdf2 hashes start with $pbkdf2)
        if user.password and not user.password.startswith(("$pbkdf2", "$2b$", "$2a$")):
            raw_pass = user.password
            hashed = pwd_context.hash(raw_pass)
            user.password = hashed
            count += 1
    db.commit()
    db.close()
    print(f"Migrated {count} user passwords successfully!")

if __name__ == "__main__":
    migrate()
