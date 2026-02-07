import bcrypt
passwd = b"HealthStrong2026!"
salt = bcrypt.gensalt()
hashed = bcrypt.hashpw(passwd, salt)
print(hashed.decode('utf-8'))