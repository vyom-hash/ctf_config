import uuid
from datetime import datetime, timedelta, timezone
from jose import jwt

SECRET_KEY = "change-me"   # must match SECRET_KEY in your .env
ALGORITHM  = "HS256"

user_id = str(uuid.uuid4())   # any UUID — acts as the "user"
expire  = datetime.now(timezone.utc) + timedelta(hours=8)
token   = jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

print(f"User ID : {user_id}")
print(f"Token   : {token}")
