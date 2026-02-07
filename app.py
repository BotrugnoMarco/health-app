import streamlit as st
import pandas as pd
import sqlite3
import google.generativeai as genai
import plotly.graph_objects as go
import streamlit_authenticator as stauth
import json
import yaml
import bcrypt
from datetime import datetime
import time

# ==========================================
# CONFIGURAZIONE PAGINA E STATO
# ==========================================
st.set_page_config(page_title="Health Tracker AI", layout="wide", page_icon="❤️")

# Costante per il nome del DB
DB_NAME = "health.db"

# ==========================================
# GESTIONE DATABASE (SQLITE)
# ==========================================

def init_db():
    """Inizializza il database creando le tabelle se non esistono."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Tabella Pasti
    c.execute('''
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            description TEXT,
            kcal REAL,
            pro REAL,
            carbo REAL,
            fat REAL
        )
    ''')
    
    # Tabella Dati Zepp (Smartwatch) - 'date' è UNIQUE per upsert
    c.execute('''
        CREATE TABLE IF NOT EXISTS zepp_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            steps INTEGER,
            sleep_hours REAL,
            deep_sleep_min INTEGER,
            min_heart_rate INTEGER,
            max_heart_rate INTEGER,
            body_weight REAL
        )
    ''')

    # Tabella Workout
    c.execute('''
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            sport_type TEXT,
            duration_min INTEGER,
            kcal_burned REAL
        )
    ''')

    conn.commit()
    conn.close()

def run_query(query, params=(), fetch=False):
    """Helper per eseguire query SQL in modo sicuro."""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(query, params)
        if fetch:
            data = c.fetchall()
            cols = [description[0] for description in c.description]
            conn.close()
            return pd.DataFrame(data, columns=cols)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Errore Database: {e}")
        return False

# ==========================================
# FUNZIONI AI (GEMINI)
# ==========================================

def analyze_food_text(text_input):
    """Chiama Gemini per analizzare il testo del pasto."""
    if "GOOGLE_API_KEY" not in st.secrets:
        st.error("API Key di Google non trovata nei secrets! Controlla .streamlit/secrets.toml")
        return None

    api_key_val = st.secrets["GOOGLE_API_KEY"]
    if "INSERISCI" in api_key_val:
        st.warning("⚠️ Hai dimenticato di inserire la tua API Key vera nel file .streamlit/secrets.toml")
        return None

    genai.configure(api_key=api_key_val)
    model = genai.GenerativeModel('gemini-pro')

    prompt = f"""
    Sei un nutrizionista esperto. Analizza il seguente testo che descrive un pasto: "{text_input}".
    Restituisci ESCLUSIVAMENTE un oggetto JSON valido (senza markdown ```json ... ```) con le seguenti chiavi:
    - "descrizione": (stringa, un riassunto conciso di cosa è stato mangiato)
    - "kcal": (numero intero, stima calorie)
    - "pro": (numero, grammi proteine)
    - "carbo": (numero, grammi carboidrati)
    - "fat": (numero, grammi grassi)
    
    Se il testo non è cibo, restituisci JSON con valori null o 0.
    """
    
    try:
        response = model.generate_content(prompt)
        # Pulizia base se Gemini aggiunge backticks
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)
        return data
    except Exception as e:
        st.error(f"Errore nel parsing AI: {e}")
        return None

# ==========================================
# LOGICA DI IMPORT (ZEPP)
# ==========================================

def process_zepp_csv(uploaded_file):
    """Analizza il CSV di Zepp e mappa le colonne."""
    try:
        df = pd.read_csv(uploaded_file)
        
        # --- CONFIGURAZIONE MAPPING COLONNE ---
        # Modifica i valori a destra in base alle colonne esatte del tuo CSV Zepp
        # Le chiavi a sinistra sono quelle interne del DB
        mapping = {
            "date": "date",  # Formato atteso da Zepp spesso è 'date' o 'Time'
            "steps": "steps", 
            "sleep_hours": "totalSleep", 
            "deep_sleep_min": "deepSleep",
            "min_heart_rate": "minHeartRate",
            "max_heart_rate": "maxHeartRate",
            "body_weight": "weight"
        }
        
        # Tentativo di rilevamento automatico o fallback
        # A volte Zepp esporta date come 'Time' o 'Date'
        if 'date' not in df.columns:
            possible_date_cols = [c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()]
            if possible_date_cols:
                mapping['date'] = possible_date_cols[0]

        # Filtriamo solo le colonne che troviamo nel CSV
        available_columns = [col for col in mapping.values() if col in df.columns]
        
        if not available_columns:
            st.error("Nessuna colonna riconosciuta nel CSV. Verifica intestazioni CSV o aggiorna la mappa in process_zepp_csv.")
            st.write("Colonne trovate nel file:", df.columns.tolist())
            return None, None

        st.info(f"Colonne mappate: {available_columns}")
        return df, mapping
    except Exception as e:
        st.error(f"Errore lettura CSV: {e}")
        return None, None

def save_zepp_data(df, mapping):
    """Esegue l'Upsert dei dati Zepp nel DB."""
    count_updated = 0
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    try:
        for _, row in df.iterrows():
            col_date_csv = mapping.get('date')
            
            if col_date_csv not in row:
                continue

            date_val = str(row[col_date_csv])
            # Se la data contiene ore (es. 2024-01-01 12:00:00), teniamo solo YYYY-MM-DD
            if len(date_val) > 10:
                try:
                    # Tenta parsing standard
                    dt_obj = pd.to_datetime(date_val)
                    date_val = dt_obj.strftime("%Y-%m-%d")
                except:
                    date_val = date_val[:10]
                
            steps = int(row.get(mapping.get('steps'), 0) or 0)
            
            # Esempio conversione sonno minuti -> ore se necessario
            raw_sleep = float(row.get(mapping.get('sleep_hours'), 0) or 0)
            sleep_h = raw_sleep / 60 if raw_sleep > 24 else raw_sleep 
            
            deep_sleep = int(row.get(mapping.get('deep_sleep_min'), 0) or 0)
            min_hr = int(row.get(mapping.get('min_heart_rate'), 0) or 0)
            max_hr = int(row.get(mapping.get('max_heart_rate'), 0) or 0)
            weight = float(row.get(mapping.get('body_weight'), 0) or 0)

            # Query UPSERT (Insert or Replace)
            c.execute('''
                INSERT OR REPLACE INTO zepp_data 
                (date, steps, sleep_hours, deep_sleep_min, min_heart_rate, max_heart_rate, body_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (date_val, steps, sleep_h, deep_sleep, min_hr, max_hr, weight))
            
            count_updated += 1 

        conn.commit()
        st.success(f"Dati salvati! Record processati: {count_updated}")
        
    except Exception as e:
        st.error(f"Errore durante il salvataggio nel DB: {e}")
    finally:
        conn.close()

# ==========================================
# MAIN APP
# ==========================================

def main():
    init_db()

    # --- AUTENTICAZIONE ---

    @st.cache_data
    def get_password_hash(password_raw):
        """Genera hash della password e lo cacha per evitare rigenerazioni ad ogni rerun"""
        try:
            return bcrypt.hashpw(password_raw.encode(), bcrypt.gensalt()).decode()
        except Exception as e:
            st.error(f"Errore hashing: {e}")
            return '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWrn96pzvCpBelOE83.xKryp.YXi.w'

    # Hash stabile per la sessione
    password_hash = get_password_hash("HealthStrong2026!")

    # Configurazione Utenti
    config = {
        'credentials': {
            'usernames': {
                'marco': {
                    'name': 'Marco Botrugno',
                    'password': password_hash,
                    'email': 'marco@health.com',
                }
            }
        },
        'cookie': {'expiry_days': 30, 'key': 'random_signature_key', 'name': 'health_cookie'},
        'preauthorized': {'emails': []}
    }

    authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days'],
    )

    # Login Widget
    try:
        # Versione 0.4.x: login() prende 'location' come primo argomento (o kwargs)
        # Rimuoviamo il titolo 'Login' che causava errore perché interpretato come location
        authenticator.login(location='main')
    except Exception as e:
        st.error(f"Errore inizializzazione Auth: {e}")
        return

    # Recupero variabili da session_state
    authentication_status = st.session_state.get('authentication_status')
    name = st.session_state.get('name')
    username = st.session_state.get('username')

    if authentication_status is False:
        st.error('Username/password non corretti (Prova: admin / abc)')
        return 
    elif authentication_status is None:
        st.warning('Inserisci username e password per accedere')
        return 
    
    # --- UTENTE LOGGATO ---
    with st.sidebar:
        st.title(f"Ciao, {name} 👋")
        authenticator.logout('Logout', 'main')
        st.divider()
        st.caption("Health Tracker v1.0")

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "🥑 Food AI Tracker", "⌚ Import Zepp"])

    # ---------------- TAB 1: DASHBOARD ----------------
    with tab1:
        st.header("La tua Salute a Colpo d'Occhio")
        
        # Recupero Dati Ultimi 30 Giorni
        df_meals = run_query("SELECT timestamp, kcal FROM meals WHERE timestamp >= date('now', '-30 days')", fetch=True)
        df_zepp = run_query("SELECT date, body_weight, sleep_hours, steps FROM zepp_data WHERE date >= date('now', '-30 days') ORDER BY date ASC", fetch=True)
        
        # KPI Cards
        col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
        
        curr_weight = "N/A"
        avg_sleep = 0
        
        if not df_zepp.empty:
            # Trova ultimo peso valido > 0
            valid_weights = df_zepp[df_zepp['body_weight'] > 0]
            if not valid_weights.empty:
                curr_weight = valid_weights['body_weight'].iloc[-1]
            
            avg_sleep = df_zepp['sleep_hours'].mean()
        
        col_kpi1.metric("Peso Attuale", f"{curr_weight} kg")
        col_kpi2.metric("Media Sonno (30gg)", f"{avg_sleep:.1f} h")
        
        st.divider()
        
        # Preparazione dati per grafico combinato
        if not df_meals.empty:
            df_meals['date'] = pd.to_datetime(df_meals['timestamp']).dt.strftime('%Y-%m-%d')
            daily_kcal = df_meals.groupby('date')['kcal'].sum().reset_index()
        else:
            daily_kcal = pd.DataFrame(columns=['date', 'kcal'])

        # Merge Meal Kcal vs Steps
        if not df_zepp.empty:
            # Assicuriamoci che entrambi abbiano colonna date stringa
            df_zepp['date'] = df_zepp['date'].astype(str)
            
            merged_df = pd.merge(df_zepp, daily_kcal, on='date', how='outer').fillna(0)
            merged_df = merged_df.sort_values('date').tail(7) # Ultimi 7 giorni
            
            # Creazione Grafico Plotly
            fig = go.Figure()
            
            # Barre: Calorie Assunte
            fig.add_trace(go.Bar(
                x=merged_df['date'],
                y=merged_df['kcal'],
                name='Calorie Cibo (Assunte)',
                marker_color='salmon'
            ))
            
            # Linea: Passi (Proxy attività)
            fig.add_trace(go.Scatter(
                x=merged_df['date'],
                y=merged_df['steps'],
                name='Passi (Attività)',
                yaxis='y2',
                mode='lines+markers',
                line=dict(color='royalblue', width=3)
            ))
            
            fig.update_layout(
                title="Calorie vs Attività (Ultimi 7 gg)",
                yaxis=dict(title="Kcal", side='left'),
                yaxis2=dict(title="Passi", overlaying='y', side='right', showgrid=False),
                legend=dict(x=0, y=1.1, orientation='h'),
                template="plotly_white",
                height=500
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Carica dati Zepp o inserisci pasti per iniziare a vedere i grafici.")

    # ---------------- TAB 2: FOOD AI ----------------
    with tab2:
        st.header("Cosa hai mangiato oggi?")
        
        with st.form("food_input_form", clear_on_submit=False):
            user_text = st.text_area("Descrivi il tuo pasto", placeholder="Esempio: Una fetta di petto di pollo ai ferri con insalata mista e un cucchiaio d'olio")
            submitted = st.form_submit_button("Analizza con AI ✨")
        
        if submitted and user_text:
            with st.spinner("Gemini sta analizzando i valori nutrizionali..."):
                ai_result = analyze_food_text(user_text)
                
            if ai_result:
                st.session_state['temp_food_data'] = ai_result
        
        # Se abbiamo dati in sessione pronti per essere salvati
        if 'temp_food_data' in st.session_state:
            data = st.session_state['temp_food_data']
            
            st.divider()
            st.subheader("Anteprima:")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Kcal", data.get('kcal', 0))
            col2.metric("Proteine", f"{data.get('pro', 0)}g")
            col3.metric("Carboidrati", f"{data.get('carbo', 0)}g")
            col4.metric("Grassi", f"{data.get('fat', 0)}g")
            st.text(f"Descrizione: {data.get('description', user_text)}")
            
            col_b1, col_b2 = st.columns([1, 4])
            if col_b1.button("💾 Conferma e Salva"):
                sql = '''INSERT INTO meals (timestamp, description, kcal, pro, carbo, fat)
                         VALUES (?, ?, ?, ?, ?, ?)'''
                params = (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    data.get('description', user_text),
                    data.get('kcal', 0),
                    data.get('pro', 0),
                    data.get('carbo', 0),
                    data.get('fat', 0)
                )
                if run_query(sql, params):
                    st.success("Pasto salvato correttamente!")
                    del st.session_state['temp_food_data']
                    time.sleep(1)
                    st.rerun()
            
            if col_b2.button("❌ Annulla"):
                 del st.session_state['temp_food_data']
                 st.rerun()

    # ---------------- TAB 3: ZEPP IMPORT ----------------
    with tab3:
        st.header("Importazione Dati Salute")
        st.markdown("""
        Carica qui il CSV esportato dall'app Zepp/Amazfit. 
        Il sistema cercherà di riconoscere automaticamente colonne come `date`, `steps`, `totalSleep`, `weight`, etc.
        """)
        
        uploaded_file = st.file_uploader("Scegli file CSV", type=['csv'])
        
        if uploaded_file is not None:
            st.subheader("Anteprima Dati")
            df_zepp, mapping = process_zepp_csv(uploaded_file)
            
            if df_zepp is not None:
                st.dataframe(df_zepp.head())
                st.caption(f"Colonne mappate: {mapping}")
                
                if st.button("Conferma e Salva nel Database"):
                    with st.spinner("Salvataggio in corso (Upsert)..."):
                        save_zepp_data(df_zepp, mapping)

if __name__ == "__main__":
    main()
