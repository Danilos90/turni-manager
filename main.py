from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import calendar
from typing import List

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ferie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            year INTEGER,
            iso_week INTEGER
        )
    ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS richieste (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            req_date TEXT,
            shift_name TEXT
        )
    ''')

    conn.commit()
    conn.close()

init_db()

class ScheduleRequest(BaseModel):
    year: int
    target_weeks: List[int]

class AdminRequest(BaseModel):
    employee_id: int
    year: int
    iso_week: int

# --- ROTTA PER IL FRONTEND ---
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
    return {"success": True}

@app.delete("/api/weekends")
def delete_weekend(req: AdminRequest):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("DELETE FROM riposi_weekend WHERE employee_id=? AND year=? AND iso_week=?", (req.employee_id, req.year, req.iso_week))
    conn.commit()
    conn.close()
    return {"success": True}

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
    return {"success": True}

@app.delete("/api/ferie")
def delete_ferie(req: AdminRequest):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("DELETE FROM ferie WHERE employee_id=? AND year=? AND iso_week=?", (req.employee_id, req.year, req.iso_week))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/ferie")
def get_ferie(year: int):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("SELECT employee_id, iso_week FROM ferie WHERE year=?", (year,))
    rows = c.fetchall()
    conn.close()
    return {"success": True, "data": [{"employee_id": r[0], "iso_week": r[1]} for r in rows]}
class RichiestaRequest(BaseModel):
    employee_id: int
    req_date: str
    shift_name: str

@app.post("/api/richieste")
def add_richiesta(req: RichiestaRequest):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("DELETE FROM richieste WHERE employee_id=? AND req_date=?", (req.employee_id, req.req_date))
    c.execute("INSERT INTO richieste (employee_id, req_date, shift_name) VALUES (?, ?, ?)", (req.employee_id, req.req_date, req.shift_name))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/richieste")
def get_richieste():
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    c.execute("SELECT employee_id, req_date, shift_name FROM richieste")
    rows = c.fetchall()
    conn.close()
    return {"success": True, "data": [{"employee_id": r[0], "req_date": r[1], "shift_name": r[2]} for r in rows]}

# --- GENERAZIONE TURNI ---
@app.post("/generate")
def generate_schedule(request: ScheduleRequest):
    conn = sqlite3.connect('turni.db')
    c = conn.cursor()
    
    # Legge i dati reali salvati nel server
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
            # ... (sotto la lettura di ferie e weekend)
    c.execute("SELECT employee_id, req_date, shift_name FROM richieste")
    db_richieste_raw = c.fetchall()
    conn.close()

    richieste_data = {}
    for emp_id, req_date, shift_name in db_richieste_raw:
        if emp_id not in richieste_data:
            richieste_data[emp_id] = {}
        # Converte il nome del turno in ID numerico
        shift_id = {"Riposo": 0, "Apertura": 1, "Centrale_1030": 2, "Centrale_1100": 3, "Chiusura_Lunga": 4, "Chiusura_Corta": 5}.get(shift_name, 0)
        richieste_data[emp_id][req_date] = shift_id

    schedule = generate_weeks_schedule(
        year=request.year,
        target_weeks=request.target_weeks,
        db_weekends=weekends_data, 
        db_ferie=ferie_data,
        db_richieste=richieste_data # <--- AGGIUNTA
    )
    
    if not schedule:
        return {"status": "error", "message": "Nessun turno generato. Verifica i vincoli.", "data": []}
        
    return {"status": "success", "message": "Turni generati con successo!", "data": schedule}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
