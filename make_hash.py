import bcrypt
try:
    # Genera hash per the user's desired password
    password = "HealthStrong2026!"
    # Gensalt defaults to 12 rounds
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    print(f"HASH_RESULT:{hashed.decode('utf-8')}")
except Exception as e:
    print(f"ERROR:{e}")
