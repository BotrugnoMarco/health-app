import bcrypt
pwd = "HealthStrong2026!"
print(bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode())