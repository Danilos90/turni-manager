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
    "APERTURA": 1,        
    "CENTRALE_1030": 2,   
    "CENTRALE_1100": 3,   
    "CHIUSURA_LUNGA": 4,  
    "CHIUSURA_CORTA": 5,  
    "FERIE": 7
}
SHIFT_IDS = list(SHIFTS.values())

SHIFT_NAMES_REVERSE = {
    0: "Riposo",
    1: "09:30 13:00 14:00 18:30",
    2: "10:30 13:30 14:30 19:30",
    3: "11:00 14:00 15:00 20:00",
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

    # PREMIO DIVERSITÀ PATTERN
    for p_name in ["LUN_GIO", "LUN_VEN", "MAR_MER", "GIO_VEN"]:
        count_p = sum(rest_pattern_vars[(emp, p_name)] for emp in active_employees)
        
        is_used = model.NewBoolVar(f'used_{p_name}')
        model.Add(count_p >= 1).OnlyEnforceIf(is_used)
        model.Add(count_p == 0).OnlyEnforceIf(is_used.Not())
        
        obj_terms.append(is_used * 500)
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

            # GRUPPI WEEKEND
            if e in db_weekend_employees:
                model.Add(rest_pattern_vars[(e, "SAB_DOM")] == 1)
            else:
                model.Add(rest_pattern_vars[(e, "SAB_DOM")] == 0)

            # ---------------------------------------------------------
            # LE REGOLE BLINDATE DEL WEEKEND
            # ---------------------------------------------------------
            model.Add(
                works[(e, SAB, SHIFTS["CHIUSURA_LUNGA"])] + 
                works[(e, SAB, SHIFTS["CHIUSURA_CORTA"])] + 
                works[(e, DOM, SHIFTS["CHIUSURA_LUNGA"])] + 
                works[(e, DOM, SHIFTS["CHIUSURA_CORTA"])] <= 1
            )

            for s_id in [SHIFTS["APERTURA"], SHIFTS["CENTRALE_1030"], SHIFTS["CENTRALE_1100"], SHIFTS["CHIUSURA_LUNGA"], SHIFTS["CHIUSURA_CORTA"]]:
                model.Add(works[(e, SAB, s_id)] + works[(e, DOM, s_id)] <= 1)

            if e in prev_weekend_shifts:
                prev_sab = prev_weekend_shifts[e].get('SAB', 0)
                prev_dom = prev_weekend_shifts[e].get('DOM', 0)
                
                if prev_sab != 0:
                    obj_terms.append(works[(e, SAB, prev_sab)] * -10000)
                if prev_dom != 0:
                    obj_terms.append(works[(e, DOM, prev_dom)] * -10000)

            # ---------------------------------------------------------
            # 1. DIVIETO ASSOLUTO CHIUSURE PRE-RIPOSO (HARD CONSTRAINT)
            # ---------------------------------------------------------
            for d in range(6): 
                off_tomorrow = works[(e, d+1, SHIFTS["RIPOSO"])] + works[(e, d+1, SHIFTS["FERIE"])]
                model.Add(works[(e, d, SHIFTS["CHIUSURA_LUNGA"])] + off_tomorrow <= 1)
                model.Add(works[(e, d, SHIFTS["CHIUSURA_CORTA"])] + off_tomorrow <= 1)

            # ---------------------------------------------------------
            # RICHIESTE SPECIFICHE (PREFERENZIALI ASSOLUTE)
            # ---------------------------------------------------------
            for d in DAYS:
                d_str = week_dates[d].strftime("%Y-%m-%d")
                if e in db_richieste and d_str in db_richieste[e]:
                    req_shift = db_richieste[e][d_str]
                    obj_terms.append(works[(e, d, req_shift)] * 100000)

            # ---------------------------------------------------------
            # 2. IL MOTORE DI EQUILIBRIO MENSILE STORICO
            # ---------------------------------------------------------
            for s_id in [SHIFTS["APERTURA"], SHIFTS["CENTRALE_1030"], SHIFTS["CENTRALE_1100"], SHIFTS["CHIUSURA_LUNGA"], SHIFTS["CHIUSURA_CORTA"]]:
                for d in DAYS:
                    obj_terms.append(works[(e, d, s_id)] * (-30 * history_shifts[e][s_id]))
                
                obj_terms.append(works[(e, SAB, s_id)] * (-60 * history_weekend_shifts[e][s_id]))
                obj_terms.append(works[(e, DOM, s_id)] * (-60 * history_weekend_shifts[e][s_id]))

            for p_name in ["LUN_GIO", "LUN_VEN", "MAR_MER", "GIO_VEN"]:
                obj_terms.append(rest_pattern_vars[(e, p_name)] * (-80 * history_patterns[e][p_name]))

            # --- PROFILI MATEMATICI SETTIMANALI DEL DIPENDENTE ---
            ap_e = sum(works[(e, d, SHIFTS["APERTURA"])] for d in DAYS)
            cc_e = sum(works[(e, d, SHIFTS["CHIUSURA_CORTA"])] for d in DAYS)
            cl_e = sum(works[(e, d, SHIFTS["CHIUSURA_LUNGA"])] for d in DAYS)
            c1030_e = sum(works[(e, d, SHIFTS["CENTRALE_1030"])] for d in DAYS)
            c1100_e = sum(works[(e, d, SHIFTS["CENTRALE_1100"])] for d in DAYS)

            model.Add(cc_e == 1)
            model.Add(ap_e >= 1)
            model.Add(ap_e <= 2)

            is_ap2 = model.NewBoolVar(f'is_ap2_{e}')
            model.Add(ap_e == 2).OnlyEnforceIf(is_ap2)
            model.Add(ap_e != 2).OnlyEnforceIf(is_ap2.Not())

            is_ap1 = model.NewBoolVar(f'is_ap1_{e}')
            model.Add(ap_e == 1).OnlyEnforceIf(is_ap1)
            model.Add(ap_e != 1).OnlyEnforceIf(is_ap1.Not())

            # PROFILO 2 APERTURE
            model.Add(cl_e == 1).OnlyEnforceIf(is_ap2)
            model.Add(c1030_e == 1).OnlyEnforceIf(is_ap2)
            model.Add(c1100_e == 0).OnlyEnforceIf(is_ap2)

            # PROFILO 1 APERTURA
            model.Add(cl_e == 0).OnlyEnforceIf(is_ap1)
            model.Add(c1030_e == 1).OnlyEnforceIf(is_ap1)
            model.Add(c1100_e == 2).OnlyEnforceIf(is_ap1)

            # SOSTITUZIONE LOGICA "PARACADUTE" (GIO_VEN o LUN_VEN)
            if e in weekend_off_next and e not in db_weekend_employees:
                model.Add(rest_pattern_vars[(e, "GIO_VEN")] + rest_pattern_vars[(e, "LUN_VEN")] == 1)
                obj_terms.append(rest_pattern_vars[(e, "GIO_VEN")] * 1000)
                obj_terms.append(rest_pattern_vars[(e, "LUN_VEN")] * 10)

    # ---------------------------------------------------------
    # STRUTTURA GIORNALIERA DEL NEGOZIO
    # ---------------------------------------------------------
    daily_workers_var = {}
    for d in DAYS:
        daily_w = sum(works[(e, d, s)] for e in EMPLOYEES for s in [1, 2, 3, 4, 5])
        daily_workers_var[d] = model.NewIntVar(4, NUM_EMPLOYEES, f'dw_{d}')
        model.Add(daily_workers_var[d] == daily_w)

        if d not in [GIO, VEN]:
            model.Add(daily_workers_var[d] >= 5)

        aperture = sum(works[(e, d, SHIFTS["APERTURA"])] for e in EMPLOYEES)
        cc = sum(works[(e, d, SHIFTS["CHIUSURA_CORTA"])] for e in EMPLOYEES)
        cl = sum(works[(e, d, SHIFTS["CHIUSURA_LUNGA"])] for e in EMPLOYEES)
        c1030 = sum(works[(e, d, SHIFTS["CENTRALE_1030"])] for e in EMPLOYEES)
        c1100 = sum(works[(e, d, SHIFTS["CENTRALE_1100"])] for e in EMPLOYEES)

        model.Add(aperture == 2)
        model.Add(cc + cl == 2)
        model.Add(c1030 + c1100 == daily_w - 4) 

        if d in [LUN, GIO, VEN, SAB, DOM]:
            model.Add(cc == 1)
            model.Add(cl == 1)
        else:
            model.Add(cc >= 1)
            model.Add(cc <= 2)

    # ---------------------------------------------------------
    # L'EQUILIBRATORE (LOAD BALANCER)
    # ---------------------------------------------------------
    max_wd = model.NewIntVar(4, NUM_EMPLOYEES, 'max_wd')
    min_wd = model.NewIntVar(4, NUM_EMPLOYEES, 'min_wd')
    
    model.AddMaxEquality(max_wd, [daily_workers_var[d] for d in [LUN, MAR, MER, GIO, VEN]])
    model.AddMinEquality(min_wd, [daily_workers_var[d] for d in [LUN, MAR, MER, GIO, VEN]])
    
    wd_diff = model.NewIntVar(0, NUM_EMPLOYEES, 'wd_diff')
    model.Add(wd_diff == max_wd - min_wd)
    obj_terms.append(wd_diff * -2000)

    model.Add(daily_workers_var[LUN] >= daily_workers_var[GIO])
    model.Add(daily_workers_var[LUN] >= daily_workers_var[VEN])
    model.Add(daily_workers_var[MAR] >= daily_workers_var[GIO])
    model.Add(daily_workers_var[MAR] >= daily_workers_var[VEN])
    model.Add(daily_workers_var[MER] >= daily_workers_var[GIO])
    model.Add(daily_workers_var[MER] >= daily_workers_var[VEN])

    model.Maximize(sum(obj_terms) if obj_terms else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 8.0 
    
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


def generate_weeks_schedule(year: int, target_weeks: list, db_weekends=None, db_ferie=None, db_richieste=None):
    if db_weekends is None: db_weekends = {}
    if db_ferie is None: db_ferie = {}
    if db_richieste is None: db_richieste = {}
        
    full_schedule = []
    
    history_shifts = {e: {s: 0 for s in SHIFT_IDS} for e in EMPLOYEES}
    history_weekend_shifts = {e: {s: 0 for s in SHIFT_IDS} for e in EMPLOYEES}
    history_patterns = {e: {p: 0 for p in REST_PATTERNS.keys()} for e in EMPLOYEES}
    prev_weekend_shifts = {e: {'SAB': 0, 'DOM': 0} for e in EMPLOYEES}
    
    target_weeks = sorted(target_weeks)
    
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

        prev_weekend_shifts = {e: {'SAB': 0, 'DOM': 0} for e in EMPLOYEES}
        sab_str = week_dates[SAB].strftime("%Y-%m-%d")
        dom_str = week_dates[DOM].strftime("%Y-%m-%d")
        
        emp_rests = {e: [] for e in EMPLOYEES}
        
        for shift_info in week_schedule:
            e_id = shift_info["employee_id"]
            d_str = shift_info["date"]
            s_name = shift_info["shift"]
            
            s_id = next((k for k, v in SHIFT_NAMES_REVERSE.items() if v == s_name), 0)
            
            if s_id == SHIFTS["RIPOSO"]:
                d_idx = [d.strftime("%Y-%m-%d") for d in week_dates].index(d_str)
                emp_rests[e_id].append(d_idx)
            else:
                history_shifts[e_id][s_id] += 1
                
                if d_str == sab_str or d_str == dom_str: 
                    history_weekend_shifts[e_id][s_id] += 1
                    if d_str == sab_str:
                        prev_weekend_shifts[e_id]['SAB'] = s_id
                    else:
                        prev_weekend_shifts[e_id]['DOM'] = s_id

        for e_id, rests in emp_rests.items():
            for p_name, p_days in REST_PATTERNS.items():
                if sorted(rests) == sorted(p_days):
                    history_patterns[e_id][p_name] += 1
                    break

    return full_schedule
