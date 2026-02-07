import streamlit_authenticator as stauth
hashed_passwords = stauth.Hasher(['HealthTracker@2026']).generate()
print(hashed_passwords[0])
