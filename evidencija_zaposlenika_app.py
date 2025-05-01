import sqlite3
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import hashlib
import locale
import base64
import time

# Postavljanje hrvatskog lokalnog vremena
try:
    locale.setlocale(locale.LC_ALL, 'hr_HR.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'Croatian.UTF-8')
    except:
        locale.setlocale(locale.LC_ALL, '')

# Funkcije za formatiranje datuma
def format_date(date_str):
    """Pretvara datum iz YYYY-MM-DD u DD.MM.YYYY format"""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y.')
    except:
        return date_str

def parse_date(date_str):
    """Pretvara datum iz DD.MM.YYYY u YYYY-MM-DD format za bazu"""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, '%d.%m.%Y.').strftime('%Y-%m-%d')
    except:
        return date_str

# Konfiguracija stranice
st.set_page_config(
    page_title="Teding - Evidencija zaposlenika",
    page_icon="📊",
    layout="wide"
)

# Funkcija za provjeru lozinke
def check_password():
    def login_form():
        with st.form("login"):
            st.markdown("### Prijava u sustav")
            username = st.text_input("Korisničko ime")
            password = st.text_input("Lozinka", type="password")
            submit = st.form_submit_button("Prijava")
            
            if submit:
                if (username == "admin" and 
                    hashlib.sha256(password.encode()).hexdigest() == 
                    hashlib.sha256("Tedingzg1".encode()).hexdigest()):
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("❌ Neispravno korisničko ime ili lozinka")
                    return False
        return False

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        login_form()
        return False

    return True

# Database connection
def init_db():
    conn = sqlite3.connect('employees.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            oib TEXT,
            address TEXT,
            birth_date TEXT,
            hire_date TEXT NOT NULL,
            training_start_date TEXT NOT NULL,
            last_physical_date TEXT,
            last_psych_date TEXT,
            next_physical_date TEXT,
            next_psych_date TEXT,
            invalidity INTEGER NOT NULL DEFAULT 0,
            children_under15 INTEGER NOT NULL DEFAULT 0,
            sole_caregiver INTEGER NOT NULL DEFAULT 0,
            physical_required INTEGER NOT NULL DEFAULT 1,
            psych_required INTEGER NOT NULL DEFAULT 1,
            previous_experience_days INTEGER NOT NULL DEFAULT 0
        )
    ''')
    
    # Dodaj nove kolone ako ne postoje
    try:
        c.execute('ALTER TABLE employees ADD COLUMN oib TEXT')
    except:
        pass
    try:
        c.execute('ALTER TABLE employees ADD COLUMN address TEXT')
    except:
        pass
    try:
        c.execute('ALTER TABLE employees ADD COLUMN physical_required INTEGER NOT NULL DEFAULT 1')
    except:
        pass
    try:
        c.execute('ALTER TABLE employees ADD COLUMN psych_required INTEGER NOT NULL DEFAULT 1')
    except:
        pass
    try:
        c.execute('ALTER TABLE employees ADD COLUMN birth_date TEXT')
    except:
        pass
    try:
        c.execute('ALTER TABLE employees ADD COLUMN previous_experience_days INTEGER NOT NULL DEFAULT 0')
    except:
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                  (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    # Invaliditet
    if invalidity:
        days += 5
        
    # Staž
    if 10 <= y < 20:
        days += 1
    elif 20 <= y < 30:
        days += 2
    elif y >= 30:
        days += 3
        
    # Djeca i samohranitelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2
        
    return days

# CRUD employee

def add_employee(data):
    try:
        c.execute('''INSERT INTO employees 
                     (name, oib, address, birth_date, hire_date,
                      next_physical_date, next_psych_date,
                      invalidity, children_under15, sole_caregiver,
                      previous_experience_days)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days']))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        st.error(f"Greška prilikom dodavanja: {str(e)}")
        raise e

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?,
                         previous_experience_days=?
                     WHERE id=?''',
                 (data['name'], data['oib'], data['address'], data['birth_date'],
                  data['hire_date'], data['next_physical_date'], data['next_psych_date'],
                  data['invalidity'], data['children_under15'], data['sole_caregiver'],
                  data['previous_experience_days'], emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška prilikom ažuriranja: {str(e)}")
        raise e

def delete_employee(emp_id):
    c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
    conn.commit()

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,NULL,NULL)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    """
    Briše zapis godišnjeg odmora prema ID-u zapisa.
    """
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
        return False

def delete_prev_job(emp_id, company, start_date, end_date):
    c.execute('DELETE FROM prev_jobs WHERE emp_id=? AND company=? AND start_date=? AND end_date=?',
              (emp_id, company, start_date, end_date))
    conn.commit()

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Glavni izbornik
    choice = st.sidebar.selectbox(
        "Izbornik",
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika", "Evidencija godišnjih"]
    )

    if choice == "Evidencija godišnjih":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        # Računanje iskorištenih dana
        leave_records = get_leave_records(emp['id'])
        used_days = 0
        for record in leave_records:
            if record['adjustment'] is None:
                start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                used_days += (end - start).days + 1
            else:
                used_days -= record['adjustment']
        
        remaining_days = leave_days - used_days
        
        st.write(f"**Ukupno dana godišnjeg:** {leave_days}")
        st.write(f"**Preostalo dana:** {remaining_days}")

        # Pojednostavljeno ručno podešavanje dana
        pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS prev_jobs (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS leave_records (
            id INTEGER PRIMARY KEY,
            emp_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days_adjustment INTEGER DEFAULT NULL,
            note TEXT DEFAULT NULL,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn, c

conn, c = init_db()

# Session state init
if 'new_jobs' not in st.session_state:
    st.session_state.new_jobs = []
if 'edit_jobs' not in st.session_state:
    st.session_state.edit_jobs = []

# CRUD

def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_prev_jobs(emp_id):
    c.execute('SELECT company, start_date, end_date FROM prev_jobs WHERE emp_id=?', (emp_id,))
    return [{'company':r[0],'start':format_date(r[1]),'end':format_date(r[2])} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    """
    Formatira relativedelta u string, pretvarajući dane preko 30 u mjesece.
    Primjer: 1g 3m 45d -> 1g 4m 15d
    """
    years = rd.years
    months = rd.months
    days = rd.days
    
    # Pretvaranje dana preko 30 u mjesece
    if days >= 30:
        additional_months = days // 30
        months += additional_months
        days = days % 30
    
    # Pretvaranje mjeseci preko 12 u godine
    if months >= 12:
        additional_years = months // 12
        years += additional_years
        months = months % 12
    
    parts = []
    if years: parts.append(f"{years}g")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}d")
    return ' '.join(parts) or '0d'

def compute_leave(hire, invalidity, children, sole):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohranitelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    
    # Osnovno
    days = 20
    
    #
