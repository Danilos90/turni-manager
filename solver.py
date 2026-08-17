import datetime
from ortools.sat.python import cp_model

NUM_EMPLOYEES = 9
EMPLOYEES = range(1, NUM_EMPLOYEES + 1)
DAYS = range(7)
LUN, MAR, MER, GIO, VEN, SAB, DOM = 0, 1, 2, 3, 4, 5, 6

REST_PATTERNS = {
    "LUN_GIO": [LUN, GIO],
    "LUN_VEN": [LUN, VEN],
    "MAR_MER": [MAR, MER],
    "GIO_VEN": [GIO, VEN],
    "SAB_DOM": [SAB, DOM]
}

SHIFTS = {
    "RIPOSO": 0,
    "APERTURA": 1,        # 09:30 13:00 14:00 18:30
    "CENTRALE_1030": 2,   # 10:30 13:00 14:00 19:30
    "CENTRALE_1100": 3,   # 11:00 14:30 15:30 20:00
    "CHIUSURA_LUNGA": 4,  # 12:00 14:30 15:30 21:00
    "CHIUSURA_CORTA": 5,  # 15:00 21:00
    "FERIE": 7
}
SHIFT_IDS = list(SHIFTS.values())

SHIFT_NAMES_REVERSE = {
    0: "Riposo",
    1: "09:30 13:00 14:00 18:30",
    2: "10:30 13:00 14:00 19:30",
    3: "11:00 14:30 15:30 20:00",
    4: "12:00 14:30 15:30 21:00",
    5: "15:00 21:00",
    7: "Ferie"
}

def solve_week(week_dates, weekend_off_this, weekend_off_next, ferie_this_week, 
               prev_weekend_shifts, history_shifts, history_weekend_shifts, history_patterns, db_richieste):
    
    model = cp_model.CpModel()
    works = {}
    rest_pattern_vars = {}
    obj_terms = []

    for e in EMPLOYEES:
        for p in REST_PATTERNS.keys():
            rest_pattern_vars[(e, p)] = model.NewBoolVar(f'rest_{e}_{p}')
        for d in DAYS:
            for s in SHIFT_IDS:
                works[(e, d, s)] = model.NewBoolVar(f'w_{e}_d{d}_s{s}')

    active_employees = [e for e in EMPLOYEES if e not in ferie_this_week]
    db_weekend_employees = [e for e in active_employees if e in weekend_off_this]
    weekday_active_employees = [e for e in active_employees if e not in db_weekend_employees]

    # MAX 3 PERSONE PER PATTERN FERIALE
    for p_name in ["LUN_GIO", "LUN_VEN", "MAR_MER", "GIO_VEN"]:
        count_p = sum(rest_pattern_vars[(emp, p_name)] for emp in active_employees)
        model.Add(count_p <= 3)

    for e in EMPLOYEES:
        for d in DAYS:
            model.AddExactlyOne(works[(e, d, s)] for s in SHIFT_IDS)

        if e in ferie_this_week:
            for d in DAYS:
                model.Add(works[(e, d, SHIFTS["FERIE"])] == 1)
            for p in REST_PATTERNS.keys():
                model.Add(rest_pattern_vars[(e, p)] == 0)
        else:
            model.AddExactlyOne(rest_pattern_vars[(e, p)] for p in REST_PATTERNS.keys())

            for p, d_off in REST_PATTERNS.items():
                for d in DAYS:
                    if d in d_off:
                        model.Add(works[(e, d, SHIFTS["RIPOSO"])] == 1).OnlyEnforceIf(rest_pattern_vars[(e, p)])
                    else:
                        model.Add(works[(e, d, SHIFTS["RIPOSO"])] == 0).OnlyEnforceIf(rest_pattern_vars[(e, p)])

            for d in DAYS:
                model.Add(works[(e, d, SHIFTS["FERIE"])] == 0)

            if e in db_weekend_employees:
                model.Add(rest_pattern_vars[(e, "SAB_DOM")] == 1)
            else:
                model.Add(rest_pattern_vars[(e, "SAB_DOM")] == 0)

            # DIVIETO DOPPIO TURNO TARDO NEL WEEKEND (SAB & DOM)
            late_shifts_sab_dom = [
                works[(e, SAB, SHIFTS["CENTRALE_1100"])],
                works[(e, SAB, SHIFTS["CHIUSURA_LUNGA"])],
                works[(e, SAB, SHIFTS["CHIUSURA_CORTA"])],
                works[(e, DOM, SHIFTS["CENTRALE_1100"])],
                works[(e, DOM, SHIFTS["CHIUSURA_LUNGA"])],
                works[(e, DOM, SHIFTS["CHIUSURA_CORTA"])]
            ]
            model.Add(sum(late_shifts_sab_dom) <= 1)

            for s_id in [1, 2, 3, 4, 5]:
                model.Add(works[(e, SAB, s_id)] + works[(e, DOM, s_id)] <= 1)

            # PONTE PRE-WEEKEND LIBERO (OBBLIGO VENERDÌ LIBERO: GIO_VEN O LUN_VEN)
            if e in weekend_off_next and e not in db_weekend_employees:
                model.Add(rest_pattern_vars[(e, "GIO_VEN")] + rest_pattern_vars[(e, "LUN_VEN")] == 1)
                obj_terms.append(rest_pattern_vars[(e, "GIO_VEN")] * 10000)
                obj_terms.append(rest_pattern_vars[(e, "LUN_VEN")] * 5000)

            # DIVIETO CHIUSURE PRE-RIPOSO (SOLO CHIUSURE FINO ALLE 21:00)
            for d in range(6): 
                off_tomorrow = works[(e, d+1, SHIFTS["RIPOSO"])] + works[(e, d+1, SHIFTS["FERIE"])]
                model.Add(works[(e, d, SHIFTS["CHIUSURA_LUNGA"])] + off_tomorrow <= 1)
                model.Add(works[(e, d, SHIFTS["CHIUSURA_CORTA"])] + off_tomorrow <= 1)

            # RICHIESTE SPECIFICHE
            for d in DAYS:
                d_str = week_dates[d].strftime("%Y-%m-%d")
                if e in db_richieste and d_str in db_richieste[e]:
                    req_shift = db_richieste[e][d_str]
                    obj_terms.append(works[(e, d, req_shift)] * 100000)

            # EQUILIBRIO MENSILE STORICO
            for s_id in [1, 2, 3, 4, 5]:
                for d in DAYS:
                    obj_terms.append(works[(e, d, s_id)] * (-30 * history_shifts[e][s_id]))
                obj_terms.append(works[(e, SAB, s_id)] * (-60 * history_weekend_shifts[e][s_id]))
                obj_terms.append(works[(e, DOM, s_id)] * (-60 * history_weekend_shifts[e][s_id]))

            for p_name in ["LUN_GIO", "LUN_VEN", "MAR_MER", "GIO_VEN"]:
                obj_terms.append(rest_pattern_vars[(e, p_name)] * (-80 * history_patterns[e][p_name]))

            # PROFILI INDIVIDUALI BILANCIATI
            ap_e = sum(works[(e, d, SHIFTS["APERTURA"])] for d in DAYS)
            cc_e = sum(works[(e, d, SHIFTS["CHIUSURA_CORTA"])] for d in DAYS)
            cl_e = sum(works[(e, d, SHIFTS["CHIUSURA_LUNGA"])] for d in DAYS)

            if len(active_employees) == 7:
                # Con 7 attivi: 2 AP, 1 CC, 1 CL, 1 C1030 a testa
                model.Add(ap_e == 2)
                model.Add(cc_e == 1)
                model.Add(cl_e == 1)
            elif len(active_employees) >= 8:
                # Con 8 attivi: 1 CC a testa, 1-2 AP, 0-1 CL
                model.Add(cc_e == 1)
                model.Add(ap_e >= 1)
                model.Add(ap_e <= 2)
                model.Add(cl_e <= 1)

    # ---------------------------------------------------------
    # COMPOSIZIONE RIGIDA GIORNALIERA DEL NEGOZIO
    # ---------------------------------------------------------
    daily_workers_var = {}
    for d in DAYS:
        daily_w = sum(works[(e, d, s)] for e in EMPLOYEES for s in [1, 2, 3, 4, 5])
        daily_workers_var[d] = model.NewIntVar(0, NUM_EMPLOYEES, f'dw_{d}')
        model.Add(daily_workers_var[d] == daily_w)

        aperture = sum(works[(e, d, SHIFTS["APERTURA"])] for e in EMPLOYEES)
        cc = sum(works[(e, d, SHIFTS["CHIUSURA_CORTA"])] for e in EMPLOYEES)
        cl = sum(works[(e, d, SHIFTS["CHIUSURA_LUNGA"])] for e in EMPLOYEES)
        c1030 = sum(works[(e, d, SHIFTS["CENTRALE_1030"])] for e in EMPLOYEES)
        c1100 = sum(works[(e, d, SHIFTS["CENTRALE_1100"])] for e in EMPLOYEES)

        is_4 = model.NewBoolVar(f'is_4_d{d}')
        is_5 = model.NewBoolVar(f'is_5_d{d}')
        is_6 = model.NewBoolVar(f'is_6_d{d}')

        model.Add(daily_w == 4).OnlyEnforceIf(is_4)
        model.Add(daily_w != 4).OnlyEnforceIf(is_4.Not())

        model.Add(daily_w == 5).OnlyEnforceIf(is_5)
        model.Add(daily_w != 5).OnlyEnforceIf(is_5.Not())

        model.Add(daily_w == 6).OnlyEnforceIf(is_6)
        model.Add(daily_w != 6).OnlyEnforceIf(is_6.Not())

        # Presidio 4 Lavoratori: 2 AP, 0 C1030, 0 C1100, 1 CL, 1 CC
        model.Add(aperture == 2).OnlyEnforceIf(is_4)
        model.Add(c1030 == 0).OnlyEnforceIf(is_4)
        model.Add(c1100 == 0).OnlyEnforceIf(is_4)
        model.Add(cl == 1).OnlyEnforceIf(is_4)
        model.Add(cc == 1).OnlyEnforceIf(is_4)

        # Presidio 5 Lavoratori: 2 AP, 1 C1030, 0 C1100, 1 CL, 1 CC
        model.Add(aperture == 2).OnlyEnforceIf(is_5)
        model.Add(c1030 == 1).OnlyEnforceIf(is_5)
        model.Add(c1100 == 0).OnlyEnforceIf(is_5)
        model.Add(cl == 1).OnlyEnforceIf(is_5)
        model.Add(cc == 1).OnlyEnforceIf(is_5)

        # Presidio 6 Lavoratori: 2 AP, 1 C1030, 1 C1100, 1 CL, 1 CC (o 0 CL e 2 CC se Martedì/Mercoledì)
        model.Add(aperture == 2).OnlyEnforceIf(is_6)
        model.Add(c1030 == 1).OnlyEnforceIf(is_6)
        model.Add(c1100 == 1).OnlyEnforceIf(is_6)

        if d in [MAR, MER]:
            model.Add(cc + cl == 2).OnlyEnforceIf(is_6)
            model.Add(cc >= 1).OnlyEnforceIf(is_6)
            model.Add(cc <= 2).OnlyEnforceIf(is_6)
        else:
            model.Add(cl == 1).OnlyEnforceIf(is_6)
            model.Add(cc == 1).OnlyEnforceIf(is_6)

    # ---------------------------------------------------------
    # DIVISIONE EUCLIDEA RIPOSI FERIALI
    # ---------------------------------------------------------
    n_feriali = len(weekday_active_employees)
    total_rests = 2 * n_feriali

    q = total_rests // 5  
    r = total_rests % 5   

    num_days_heavy = 5 - r  
    feriali_days = [LUN, MAR, MER, GIO, VEN]

    for idx, d in enumerate(feriali_days):
        d_rests = sum(works[(e, d, SHIFTS["RIPOSO"])] for e in weekday_active_employees)
        if idx < num_days_heavy:
            model.Add(d_rests == q)
        else:
            model.Add(d_rests == q + 1)

    model.Maximize(sum(obj_terms) if obj_terms else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0 
    solver.parameters.randomize_search = False  # Determinismo
    solver.parameters.random_seed = 0
    
    status = solver.Solve(model)

    weekly_schedule = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in EMPLOYEES:
            for d in DAYS:
                current_date = week_dates[d]
                for s in SHIFT_IDS:
                    if solver.Value(works[(e, d, s)]) == 1:
                        weekly_schedule.append({
                            "date": current_date.strftime("%Y-%m-%d"),
                            "employee_id": e,
                            "shift": SHIFT_NAMES_REVERSE[s]
                        })
    return weekly_schedule


def generate_weeks_schedule(year: int, target_weeks: list, db_weekends=None, db_ferie=None, db_richieste=None, db_saved_schedule=None):
    if db_weekends is None: db_weekends = {}
    if db_ferie is None: db_ferie = {}
    if db_richieste is None: db_richieste = {}
    if db_saved_schedule is None: db_saved_schedule = []
        
    full_schedule = []
    
    history_shifts = {e: {s: 0 for s in SHIFT_IDS} for e in EMPLOYEES}
    history_weekend_shifts = {e: {s: 0 for s in SHIFT_IDS} for e in EMPLOYEES}
    history_patterns = {e: {p: 0 for p in REST_PATTERNS.keys()} for e in EMPLOYEES}
    
    prev_weekend_shifts = {e: {'SAB': -1, 'DOM': -1} for e in EMPLOYEES}
    
    target_weeks = sorted(target_weeks)
    if not target_weeks: return []

    if db_saved_schedule:
        sorted_history = sorted(db_saved_schedule, key=lambda x: x["date"])
        emp_weekly_rests = {e: {} for e in EMPLOYEES}
        
        for record in sorted_history:
            e_id = record["employee_id"]
            d_str = record["date"]
            s_name = record["shift"]
            s_id = next((k for k, v in SHIFT_NAMES_REVERSE.items() if v == s_name), 0)
            
            d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
            iso_year, iso_week, iso_day = d_obj.isocalendar()
            
            if iso_year > year or (iso_year == year and iso_week >= target_weeks[0]):
                continue
            
            if s_id != SHIFTS["RIPOSO"]:
                history_shifts[e_id][s_id] += 1
                if iso_day == 6 or iso_day == 7:
                    history_weekend_shifts[e_id][s_id] += 1
                    
            if iso_year == year and iso_week == target_weeks[0] - 1:
                if iso_day == 6:
                    prev_weekend_shifts[e_id]['SAB'] = s_id
                elif iso_day == 7:
                    prev_weekend_shifts[e_id]['DOM'] = s_id
                    
            if s_id == SHIFTS["RIPOSO"]:
                if iso_week not in emp_weekly_rests[e_id]:
                    emp_weekly_rests[e_id][iso_week] = []
                emp_weekly_rests[e_id][iso_week].append(iso_day - 1) 

        for e_id, weeks_data in emp_weekly_rests.items():
            for wk, rests in weeks_data.items():
                for p_name, p_days in REST_PATTERNS.items():
                    if sorted(rests) == sorted(p_days):
                        history_patterns[e_id][p_name] += 1
                        break

    for iso_wk in target_weeks:
        week_dates = [datetime.date.fromisocalendar(year, iso_wk, d) for d in range(1, 8)]
        
        weekend_off_this_week = db_weekends.get(iso_wk, [])
        weekend_off_next_week = db_weekends.get(iso_wk + 1, [])
        ferie_this_week = db_ferie.get(iso_wk, [])
            
        week_schedule = solve_week(
            week_dates, 
            weekend_off_this_week, 
            weekend_off_next_week, 
            ferie_this_week, 
            prev_weekend_shifts,
            history_shifts,
            history_weekend_shifts,
            history_patterns,
            db_richieste
        )
        full_schedule.extend(week_schedule)

        sab_str = week_dates[SAB].strftime("%Y-%m-%d")
        dom_str = week_dates[DOM].strftime("%Y-%m-%d")
        
        emp_rests = {e: [] for e in EMPLOYEES}
        
        for shift_info in week_schedule:
            e_id = shift_info["employee_id"]
            d_str = shift_info["date"]
            s_name = shift_info["shift"]
            
            s_id = next((k for k, v in SHIFT_NAMES_REVERSE.items() if v == s_name), 0)
            
            if d_str == sab_str:
                prev_weekend_shifts[e_id]['SAB'] = s_id
            if d_str == dom_str:
                prev_weekend_shifts[e_id]['DOM'] = s_id

            if s_id == SHIFTS["RIPOSO"]:
                d_idx = [d.strftime("%Y-%m-%d") for d in week_dates].index(d_str)
                emp_rests[e_id].append(d_idx)
            else:
                history_shifts[e_id][s_id] += 1
                if d_str == sab_str or d_str == dom_str: 
                    history_weekend_shifts[e_id][s_id] += 1

        for e_id, rests in emp_rests.items():
            for p_name, p_days in REST_PATTERNS.items():
                if sorted(rests) == sorted(p_days):
                    history_patterns[e_id][p_name] += 1
                    break

    return full_schedule
