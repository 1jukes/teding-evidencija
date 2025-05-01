import streamlit as st
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
            psych_required INTEGER NOT NULL DEFAULT 1
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
        hire_date = data['hire']
        next_phys = data.get('next_phys', '')
        next_psy = data.get('next_psy', '')
        birth_date = data.get('birth_date', '')

        c.execute('''INSERT INTO employees
                     (name, oib, address, birth_date, hire_date, training_start_date,
                      next_physical_date, next_psych_date, invalidity, 
                      children_under15, sole_caregiver)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                  (data['name'], data['oib'], data['address'], birth_date,
                   hire_date, hire_date, next_phys, next_psy,
                   int(data['invalidity']), int(data['children']), int(data['sole'])))
        
        conn.commit()
        emp_id = c.lastrowid
        
        for job in st.session_state.new_jobs:
            c.execute('''INSERT INTO prev_jobs (emp_id,company,start_date,end_date)
                        VALUES (?,?,?,?)''',
                     (emp_id, job['company'], 
                      parse_date(job['start']), 
                      parse_date(job['end'])))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška pri dodavanju: {str(e)}")
        return False

def edit_employee(emp_id, data):
    try:
        c.execute('''UPDATE employees 
                     SET name=?, oib=?, address=?, birth_date=?, hire_date=?,
                         next_physical_date=?, next_psych_date=?,
                         invalidity=?, children_under15=?, sole_caregiver=?
                     WHERE id=?''',
                  (data['name'], data['oib'], data['address'], data['birth_date'],
                   data['hire'], data['next_phys'], data['next_psy'],
                   int(data['invalidity']), int(data['children']), 
                   int(data['sole']), emp_id))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Greška pri ažuriranju: {str(e)}")
        return False

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
        ["Pregled zaposlenika", "Dodaj/Uredi zaposlenika", "Pregledaj zaposlenika"]
    )

    if choice == "Dodaj/Uredi zaposlenika":
        # Odabir zaposlenika za uređivanje ili opcija za dodavanje novog
        employees = get_employees()
        emp_names = ["Novi zaposlenik"] + [emp['name'] for emp in employees]
        selected_emp = st.selectbox("Odaberi zaposlenika ili 'Novi zaposlenik' za dodavanje", emp_names)
        
        # Inicijalizacija podataka
        emp_data = {}
        if selected_emp != "Novi zaposlenik":
            emp = next(emp for emp in employees if emp['name'] == selected_emp)
            emp_data = emp

        with st.form("employee_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Ime i prezime", value=emp_data.get('name', ''))
                oib = st.text_input("OIB", value=emp_data.get('oib', ''))
                address = st.text_input("Adresa", value=emp_data.get('address', ''))
                birth_date = st.date_input("Datum rođenja", 
                    value=datetime.strptime(emp_data.get('birth_date', '2000-01-01'), '%Y-%m-%d').date() if emp_data.get('birth_date') else None,
                    min_value=datetime(1950, 1, 1),
                    max_value=datetime.now())
                hire_date = st.date_input("Datum zaposlenja", 
                    value=datetime.strptime(emp_data.get('hire_date', '2000-01-01'), '%Y-%m-%d').date() if emp_data.get('hire_date') else None)

            with col2:
                invalidity = st.checkbox("Invaliditet", value=emp_data.get('invalidity', False))
                children = st.number_input("Broj djece <15", min_value=0, value=emp_data.get('children_under15', 0))
                sole = st.checkbox("Samohrani roditelj", value=emp_data.get('sole_caregiver', False))
                
                # Pojednostavljeni unos pregleda
                next_phys = st.date_input("Datum sljedećeg fizičkog pregleda", 
                    value=datetime.strptime(emp_data.get('next_physical_date', ''), '%Y-%m-%d').date() if emp_data.get('next_physical_date') else None,
                    help="Ostavite prazno ako nema pregleda")
                
                next_psy = st.date_input("Datum sljedećeg psihičkog pregleda", 
                    value=datetime.strptime(emp_data.get('next_psych_date', ''), '%Y-%m-%d').date() if emp_data.get('next_psych_date') else None,
                    help="Ostavite prazno ako nema pregleda")

            # Prethodna iskustva
            st.markdown("### Prethodna iskustva")
            if selected_emp != "Novi zaposlenik":
                prev_jobs = get_prev_jobs(emp_data['id'])
                for job in prev_jobs:
                    st.text(f"{job['company']}: {job['start']} - {job['end']}")

            # Dodavanje novog prethodnog iskustva
            col1, col2, col3 = st.columns(3)
            with col1:
                company = st.text_input("Tvrtka")
            with col2:
                job_start = st.date_input("Početak rada")
            with col3:
                job_end = st.date_input("Kraj rada")

            if selected_emp == "Novi zaposlenik":
                submit = st.form_submit_button("Dodaj zaposlenika")
            else:
                submit = st.form_submit_button("Spremi promjene")

            if submit:
                data = {
                    'name': name,
                    'oib': oib,
                    'address': address,
                    'birth_date': birth_date.strftime('%Y-%m-%d') if birth_date else None,
                    'hire': hire_date.strftime('%Y-%m-%d'),
                    'next_phys': next_phys.strftime('%Y-%m-%d') if next_phys else None,
                    'next_psy': next_psy.strftime('%Y-%m-%d') if next_psy else None,
                    'invalidity': invalidity,
                    'children': children,
                    'sole': sole
                }
                
                try:
                    if selected_emp == "Novi zaposlenik":
                        emp_id = add_employee(data)
                        st.success("✅ Zaposlenik uspješno dodan!")
                    else:
                        emp_id = emp_data['id']
                        edit_employee(emp_id, data)
                        st.success("✅ Podaci uspješno ažurirani!")
                    
                    # Dodavanje novog prethodnog iskustva ako su sva polja popunjena
                    if company and job_start and job_end:
                        c.execute('''INSERT INTO prev_jobs (emp_id, company, start_date, end_date)
                                   VALUES (?, ?, ?, ?)''',
                                (emp_id, company, job_start.strftime('%Y-%m-%d'),
                                 job_end.strftime('%Y-%m-%d')))
                        conn.commit()
                    
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Greška: {str(e)}")

    elif choice == "Pregledaj zaposlenika":
        employees = get_employees()
        if not employees:
            st.warning("Nema zaposlenika u bazi.")
            return
            
        selected = st.selectbox("Odaberi zaposlenika", [emp['name'] for emp in employees])
        emp = next(emp for emp in employees if emp['name'] == selected)
        
        st.markdown("### Podaci o zaposleniku")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**Ime i prezime:** {emp['name']}")
            st.write(f"**OIB:** {emp['oib'] or 'Nije unesen'}")
            st.write(f"**Adresa:** {emp['address'] or 'Nije unesena'}")
            st.write(f"**Datum rođenja:** {format_date(emp['birth_date']) or 'Nije unesen'}")
            st.write(f"**Datum zaposlenja:** {format_date(emp['hire_date'])}")
        
        with col2:
            st.write("**Status invaliditeta:** ✅" if emp['invalidity'] else "**Status invaliditeta:** ❌")
            st.write(f"**Broj djece <15:** {emp['children_under15']}")
            st.write("**Samohrani roditelj:** ✅" if emp['sole_caregiver'] else "**Samohrani roditelj:** ❌")
            st.write(f"**Fizički pregled:** {format_date(emp['next_physical_date']) or 'Nema pregleda'}")
            st.write(f"**Psihički pregled:** {format_date(emp['next_psych_date']) or 'Nema pregleda'}")

        # Prethodna iskustva
        st.markdown("### Prethodna iskustva")
        prev_jobs = get_prev_jobs(emp['id'])
        if prev_jobs:
            for job in prev_jobs:
                col1, col2, col3 = st.columns([2,1,1])
                with col1:
                    st.write(f"**Tvrtka:** {job['company']}")
                with col2:
                    st.write(f"**Od:** {job['start']}")
                with col3:
                    st.write(f"**Do:** {job['end']}")
        else:
            st.write("Nema unesenih prethodnih iskustava.")

        # Godišnji odmori
        st.markdown("### Godišnji odmor")
        tenure = compute_tenure(emp['hire_date'])
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'])
        
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Ukupni staž:** {format_rd(tenure)}")
            st.write(f"**Broj dana godišnjeg:** {leave_days}")
        
        # Evidencija korištenja godišnjeg
        st.markdown("#### Evidencija korištenja")
        leave_records = get_leave_records(emp['id'])
        
        # Forma za dodavanje novog godišnjeg
        with st.form("add_leave"):
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("Početak godišnjeg")
            with col2:
                end_date = st.date_input("Kraj godišnjeg")
            
            if st.form_submit_button("Dodaj godišnji"):
                try:
                    add_leave_record(emp['id'], 
                                   start_date.strftime('%Y-%m-%d'),
                                   end_date.strftime('%Y-%m-%d'))
                    st.success("✅ Godišnji uspješno dodan!")
        st.rerun()
                except Exception as e:
                    st.error(f"❌ Greška: {str(e)}")
        
        # Prikaz evidencije godišnjeg
        if leave_records:
            for record in leave_records:
                col1, col2, col3 = st.columns([2,2,1])
                with col1:
                    st.write(f"**Od:** {record['start']}")
                with col2:
                    st.write(f"**Do:** {record['end']}")
                with col3:
                    if st.button("Obriši", key=f"del_{record['id']}"):
                        delete_leave_record(emp['id'], record['id'])
                        st.success("✅ Zapis obrisan!")
                        st.rerun()
        else:
            st.write("Nema evidencije korištenja godišnjeg odmora.")

    elif choice == "Pregled zaposlenika":
        rows = []
        for e in get_employees():
            rd_curr = compute_tenure(e['hire_date'])
            rd_before = relativedelta()
            for j in get_prev_jobs(e['id']):
                rd = relativedelta(
                    datetime.strptime(parse_date(j['end']),'%Y-%m-%d').date(),
                    datetime.strptime(parse_date(j['start']),'%Y-%m-%d').date())
                rd_before += rd
            rd_tot = rd_curr + rd_before
            leave = compute_leave(e['hire_date'], e['invalidity'], e['children_under15'], e['sole_caregiver'])
            
            # Računanje ukupno iskorištenih dana
            leave_records = get_leave_records(e['id'])
            used = 0
            for lr in leave_records:
                if lr['adjustment'] is None:
                    used += (datetime.strptime(parse_date(lr['end']),'%Y-%m-%d').date() - 
                            datetime.strptime(parse_date(lr['start']),'%Y-%m-%d').date()).days + 1
                else:
                    used -= lr['adjustment']
            
            rem = leave - used
            
            # Fix za prikaz datuma pregleda
            phys_str = ''
            psych_str = ''
            
            if e['next_physical_date'] and e['physical_required']:
                try:
            phys = datetime.strptime(e['next_physical_date'],'%Y-%m-%d').date()
                    if 0 <= (phys-date.today()).days <= 30:
                        phys_str = format_date(e['next_physical_date'])
                except:
                    pass
                    
            if e['next_psych_date'] and e['psych_required']:
                try:
            psych = datetime.strptime(e['next_psych_date'],'%Y-%m-%d').date()
                    if 0 <= (psych-date.today()).days <= 30:
                        psych_str = format_date(e['next_psych_date'])
                except:
                    pass
            
            rows.append({
                'Ime':e['name'],
                'Datum zapos.':format_date(e['hire_date']),
                'Staž prije':format_rd(rd_before),
                'Staž kod nas':format_rd(rd_curr),
                'Ukupno staž':format_rd(rd_tot),
                'Godišnji (dana)':leave,
                'Preostalo godišnji':rem,
                'Sljedeći fiz. pregled':phys_str,
                'Sljedeći psih. pregled':psych_str
            })
        st.dataframe(pd.DataFrame(rows),use_container_width=True)

if __name__=='__main__':
    main()
