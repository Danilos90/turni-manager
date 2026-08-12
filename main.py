from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import calendar

from solver import generate_weeks_schedule

app = FastAPI(title="Gestione Turni API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def init_db():
    conn = sqlite3.connect('turni.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS riposi_weekend (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            year INTEGER,
            iso_week INTEGER
        )
    ''')
    # ORA LA TABELLA FERIE RAGIONA A SETTIMANE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ferie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            year INTEGER,
            iso_week INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class GenerateRequest(BaseModel):
    year: int
    month: int

class AdminRequest(BaseModel):
    employee_id: int
    year: int
    iso_week: int

# --- ROTTA PER IL FRONTEND (PASSO 2) ---
@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

# --- API WEEKEND ---
@app.post("/api/weekends")
def add_weekend(req: AdminRequest):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("DELETE FROM riposi_weekend WHERE employee_id=? AND year=? AND iso_week=?", (req.employee_id, req.year, req.iso_week))
    c.execute("INSERT INTO riposi_weekend (employee_id, year, iso_week) VALUES (?, ?, ?)", (req.employee_id, req.year, req.iso_week))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Weekend salvato!"}

@app.get("/api/weekends")
def get_weekends(year: int):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("SELECT employee_id, iso_week FROM riposi_weekend WHERE year=?", (year,))
    rows = c.fetchall()
    conn.close()
    return {"success": True, "data": [{"employee_id": r[0], "iso_week": r[1]} for r in rows]}

# --- API FERIE ---
@app.post("/api/ferie")
def add_ferie(req: AdminRequest):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("DELETE FROM ferie WHERE employee_id=? AND year=? AND iso_week=?", (req.employee_id, req.year, req.iso_week))
    c.execute("INSERT INTO ferie (employee_id, year, iso_week) VALUES (?, ?, ?)", (req.employee_id, req.year, req.iso_week))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Settimana di ferie salvata!"}

@app.get("/api/ferie")
def get_ferie(year: int):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("SELECT employee_id, iso_week FROM ferie WHERE year=?", (year,))
    rows = c.fetchall()
    conn.close()
    return {"success": True, "data": [{"employee_id": r[0], "iso_week": r[1]} for r in rows]}

# --- GENERAZIONE TURNI ---
@app.post("/generate")
def generate_schedule(request: GenerateRequest):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    
    c.execute("SELECT employee_id, iso_week FROM riposi_weekend WHERE year=?", (request.year,))
    db_weekends = c.fetchall()
    
    c.execute("SELECT employee_id, iso_week FROM ferie WHERE year=?", (request.year,))
    db_ferie_raw = c.fetchall()
    conn.close()
    
    weekends_data = {}
    for emp_id, wk in db_weekends:
        if wk not in weekends_data:
            weekends_data[wk] = []
        weekends_data[wk].append(emp_id)

    ferie_data = {}
    for emp_id, wk in db_ferie_raw:
        if wk not in ferie_data:
            ferie_data[wk] = []
        ferie_data[wk].append(emp_id)

    # Calcoliamo quali sono le settimane di questo mese per passarle al nuovo motore
    cal = calendar.Calendar(firstweekday=0)
    weeks_matrix = cal.monthdatescalendar(request.year, request.month)
    target_weeks = [week[0].isocalendar()[1] for week in weeks_matrix]

    schedule = generate_weeks_schedule(
        year=request.year,
        target_weeks=target_weeks,
        db_weekends=weekends_data, 
        db_ferie=ferie_data
    )
    
    if not schedule:
        return {"success": False, "message": "Nessun turno generato. Presidi minimi impossibili da coprire.", "data": []}
        
    return {"success": True, "message": "Turni generati con successo!", "data": schedule}

# --- AVVIO SERVER (HOST = 0.0.0.0 per accessibilità esterna) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)