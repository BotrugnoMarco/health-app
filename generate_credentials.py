import bcrypt
import time

try:
    password = "HealthStrong2026!"
    # Generate salt and hash
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    with open("hash.txt", "w") as f:
        f.write(hashed.decode('utf-8'))
        
    print("Hash generated successfully in hash.txt")
except Exception as e:
    with open("hash.txt", "w") as f:
        f.write(f"Error: {str(e)}")
    print(f"Error: {e}")
