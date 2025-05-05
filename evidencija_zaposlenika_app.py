import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import hashlib
import base64
import time
import os
import shutil
import io

# Konfiguracija stranice
st.set_page_config(
    page_title="Teding - Evidencija zaposlenika",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Postavljanje početka tjedna na ponedjeljak
if 'start_of_week' not in st.session_state:
    st.session_state['start_of_week'] = 1  # 0 = nedjelja, 1 = ponedjeljak

# Funkcije za formatiranje datuma
def format_date(date_str):
    """Pretvara datum iz YYYY-MM-DD u DD/MM/YYYY format"""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
    except:
        return date_str

def parse_date(date_str):
    """Pretvara datum iz DD/MM/YYYY u YYYY-MM-DD format za bazu"""
    if not date_str:
        return ""
    try:
        # Prvo pokušaj s kosim crtama
        return datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except ValueError:
        try:
            # Ako ne uspije, pokušaj s točkama
            return datetime.strptime(date_str, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            try:
                # Ako je već u YYYY-MM-DD formatu
                return datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
            except Exception:
                return date_str

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

# 1. Postavi bazu u isti folder kao aplikacija
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "employees.db")

# 2. Automatski backup baze (opcionalno, možeš pozvati ručno ili automatski)
def backup_db():
    backup_name = os.path.join(BASE_DIR, f"employees_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    if os.path.exists(DB_PATH):
        shutil.copyfile(DB_PATH, backup_name)

# backup_db()  # Otkomeniraj ako želiš automatski backup na svakom pokretanju

# 3. Inicijalizacija baze
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            oib TEXT,
            address TEXT,
            birth_date TEXT,
            hire_date TEXT NOT NULL,
            next_physical_date TEXT,
            next_psych_date TEXT,
            invalidity INTEGER NOT NULL DEFAULT 0,
            children_under15 INTEGER NOT NULL DEFAULT 0,
            sole_caregiver INTEGER NOT NULL DEFAULT 0,
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
        c.execute('ALTER TABLE employees ADD COLUMN birth_date TEXT')
    except:
        pass
    try:
        c.execute('ALTER TABLE employees ADD COLUMN previous_experience_days INTEGER NOT NULL DEFAULT 0')
    except:
        pass
    
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
    conn.close()

init_db()

# 4. Prikaži putanju do baze na vrhu aplikacije
st.write("Putanja do baze:", DB_PATH)

# CRUD funkcije
def get_employees():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    result = [dict(zip(cols, row)) for row in c.fetchall()]
    conn.close()
    return result

def get_leave_records(emp_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    result = [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
               'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]
    conn.close()
    return result

def add_employee(data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
    conn.close()

def edit_employee(emp_id, data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
    conn.close()

def add_leave_record(emp_id, s, e):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO leave_records (emp_id, start_date, end_date) VALUES (?, ?, ?)',
              (emp_id, s, e))
    conn.commit()
    conn.close()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    days_value = days if operation == 'add' else -days
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()
    conn.close()

def delete_leave_record(emp_id, record_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
    conn.commit()
    conn.close()

# Dodajemo novu funkciju za brisanje zaposlenika
def delete_employee(emp_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM leave_records WHERE emp_id=?', (emp_id,))
        c.execute('DELETE FROM employees WHERE id=?', (emp_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"❌ Greška prilikom brisanja: {str(e)}")
        return False

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

def compute_leave(hire, invalidity, children, sole, previous_experience_days=0):
    """
    Računanje godišnjeg odmora prema pravilniku:
    - Osnovno: 20 dana
    - Invaliditet: +5 dana
    - Samohrani roditelj: +3 dana
    - Djeca: 1 dijete = +1 dan, 2 ili više = +2 dana
    - Ukupni radni staž: 10-20g = +1 dan, 20-30g = +2 dana, 30+ = +3 dana
    """
    # Staž kod trenutnog poslodavca
    staz_kod_nas = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date())
    staz_kod_nas_days = staz_kod_nas.years * 365 + staz_kod_nas.months * 30 + staz_kod_nas.days

    # Ukupni radni staž u danima
    ukupni_staz_dani = previous_experience_days + staz_kod_nas_days
    ukupni_staz_godina = ukupni_staz_dani // 365

    # Osnovno
    days = 20

    # Invaliditet
    if invalidity:
        days += 5

    # Staž (ukupni)
    if 10 <= ukupni_staz_godina < 20:
        days += 1
    elif 20 <= ukupni_staz_godina < 30:
        days += 2
    elif ukupni_staz_godina >= 30:
        days += 3

    # Djeca i samohrani roditelj
    if sole:
        days += 3
    elif children == 1:
        days += 1
    elif children >= 2:
        days += 2

    return days

def parse_date_for_sort(date_str):
    # Vrati string datuma u formatu YYYY-MM-DD ili 'Nema pregleda' ako nema pregleda
    try:
        if date_str and date_str != "Nema pregleda":
            try:
                dt = datetime.strptime(date_str, "%d/%m/%Y")
            except:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
    except:
        return "Nema pregleda"
    return "Nema pregleda"

def main():
    if not check_password():
        return
    
    st.title("Teding - Evidencija zaposlenika")
    
    # Upload baze
    uploaded_db = st.file_uploader("Učitaj postojeću bazu (employees.db)", type=["db"])
    if uploaded_db is not None:
        # Spremi uploadanu bazu preko postojeće
        with open(DB_PATH, "wb") as f:
            f.write(uploaded_db.read())
        st.success("Baza je uspješno učitana! Osvježi stranicu (Ctrl+R/F5).")
    
    # Dodaj download gumb odmah ispod naslova
    with open(DB_PATH, "rb") as f:
        st.download_button(
            label="⬇️ Preuzmi bazu (employees.db)",
            data=f,
            file_name="employees.db",
            mime="application/octet-stream"
        )
    
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
        
        # Osnovni podaci o godišnjem
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'],
                                 emp.get('previous_experience_days', 0))
        
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

        # Povijest promjena (samo za dodavanje/oduzimanje dana)
        st.markdown("### Povijest promjena")
        adjustment_records = [r for r in leave_records if r['adjustment'] is not None]
        if adjustment_records:
            for record in sorted(adjustment_records, key=lambda x: parse_date(x['start']), reverse=True):
                col1, col2 = st.columns([6, 1])
                with col1:
                    operation = "Dodano" if record['adjustment'] > 0 else "Oduzeto"
                    broj = abs(record['adjustment'])
                    dan_text = "dan" if broj == 1 else "dana"
                    napomena_text = f": {record['note']}" if record['note'] else ""
                    st.write(f"**{format_date(record['start'])}**: {operation} {broj} {dan_text}{napomena_text}")
                with col2:
                    if st.button("Obriši", key=f"del_record_{record['id']}", use_container_width=True):
                        delete_leave_record(emp['id'], record['id'])
                        st.rerun()

        # Ručno podešavanje dana
        st.markdown("### Ručno podešavanje dana")
        with st.container():
            col1, col2 = st.columns([1,3])
            
            with col1:
                days = st.number_input("Broj dana", min_value=1, value=1)
            with col2:
                napomena = st.text_input("Napomena")
            
            col3, col4 = st.columns(2)
            with col3:
                if st.button("➕ Dodaj", use_container_width=True, type="secondary"):
                    try:
                        add_days_adjustment(emp['id'], days, 'add', napomena)
                        st.success("✅ Dodano!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Greška: {str(e)}")
            with col4:
                if st.button("➖ Oduzmi", use_container_width=True, type="secondary"):
                    try:
                        add_days_adjustment(emp['id'], days, 'subtract', napomena)
                        st.success("✅ Oduzeto!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Greška: {str(e)}")

        # Evidencija korištenja
        st.markdown("### Evidencija korištenja")
        st.markdown("#### Dodaj novi godišnji")

        # Jednostavnija forma bez kolona
        with st.form("godisnji_forma"):
            try:
                start_date = st.date_input(
                    "Početak godišnjeg",
                    value=None,
                    format="DD/MM/YYYY"
                )
                
                end_date = st.date_input(
                    "Kraj godišnjeg",
                    value=None,
                    format="DD/MM/YYYY"
                )
                
                submitted = st.form_submit_button("Dodaj godišnji")
                
                if submitted:
                    if start_date and end_date:
                        if start_date <= end_date:
                            try:
                                # Pretvaranje datuma u string format za bazu
                                start_str = start_date.strftime('%Y-%m-%d')
                                end_str = end_date.strftime('%Y-%m-%d')
                                add_leave_record(emp['id'], start_str, end_str)
                                st.success("✅ Godišnji uspješno dodan!")
                            except Exception as e:
                                st.error(f"❌ Greška pri spremanju: {str(e)}")
                        else:
                            st.error("❌ Datum početka mora biti prije ili jednak datumu završetka!")
                    else:
                        st.error("❌ Molimo unesite oba datuma!")
            except Exception as e:
                st.error(f"❌ Greška pri unosu datuma: {str(e)}")

        # Prikaz postojećih godišnjih (izvan forme)
        leave_usage_records = [r for r in leave_records if r['adjustment'] is None]
        
        if leave_usage_records:
            st.markdown("#### Postojeći godišnji")
            for record in sorted(leave_usage_records, key=lambda x: parse_date(x['start']), reverse=True):
                col1, col2, col3, col4 = st.columns([2,2,2,1])
                with col1:
                    st.write(f"**Od:** {record['start']}")
                with col2:
                    st.write(f"**Do:** {record['end']}")
                with col3:
                    start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                    end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                    days = (end - start).days + 1
                    st.write(f"**Broj dana:** {days}")
                with col4:
                    if st.button("Obriši", key=f"del_leave_{record['id']}", use_container_width=True):
                        delete_leave_record(emp['id'], record['id'])
                        st.rerun()

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

        # Staž prije
        total_days = emp.get('previous_experience_days', 0)
        years = total_days // 365
        remaining_days = total_days % 365
        months = remaining_days // 30
        days = remaining_days % 30
        
        staz_prije = []
        if years: staz_prije.append(f"{years}g")
        if months: staz_prije.append(f"{months}m")
        if days: staz_prije.append(f"{days}d")
        staz_prije_str = " ".join(staz_prije) if staz_prije else "0d"
        
        # Staž kod nas
        staz_kod_nas = compute_tenure(emp['hire_date'])
        staz_kod_nas_str = format_rd(staz_kod_nas)
        
        # Ukupni staž
        ukupni_staz = relativedelta(date.today(), datetime.strptime(emp['hire_date'], '%Y-%m-%d').date())
        ukupni_staz = relativedelta(years=ukupni_staz.years + years,
                                  months=ukupni_staz.months + months,
                                  days=ukupni_staz.days + days)
        ukupni_staz_str = format_rd(ukupni_staz)
        
        st.write(f"**Staž prije:** {staz_prije_str}")
        st.write(f"**Staž kod nas:** {staz_kod_nas_str}")
        st.write(f"**Ukupni staž:** {ukupni_staz_str}")

        # Godišnji odmor
        st.markdown("### Godišnji odmor")
        leave_days = compute_leave(emp['hire_date'], emp['invalidity'], 
                                 emp['children_under15'], emp['sole_caregiver'],
                                 emp.get('previous_experience_days', 0))
        
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
        
        st.write(f"**Godišnji (prema pravilniku):** {leave_days} dana")
        st.write(f"**Preostali godišnji:** {remaining_days} dana")

        # Dodajemo gumb za brisanje na dnu
        st.write("---")  # Horizontalna linija za odvajanje
        if st.button("🗑️ Izbriši zaposlenika", type="secondary"):
            if st.warning("Jeste li sigurni da želite izbrisati zaposlenika? Ova akcija se ne može poništiti."):
                if delete_employee(emp['id']):
                    st.success("✅ Zaposlenik uspješno izbrisan!")
                    st.rerun()

    elif choice == "Dodaj/Uredi zaposlenika":
        employees = get_employees()
        
        # Odabir zaposlenika za uređivanje
        selected_employee = None
        if employees:
            names = ["Novi zaposlenik"] + [emp['name'] for emp in employees]
            selected = st.selectbox("Odaberi zaposlenika", names)
            if selected != "Novi zaposlenik":
                selected_employee = next(emp for emp in employees if emp['name'] == selected)
        
        # Forma za unos/uređivanje podataka
        with st.form("employee_form"):
            st.markdown("### Podaci o zaposleniku")
            
            # Osnovni podaci
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Ime i prezime", value=selected_employee['name'] if selected_employee else "")
                oib = st.text_input("OIB", value=selected_employee['oib'] if selected_employee else "")
                address = st.text_input("Adresa", value=selected_employee['address'] if selected_employee else "")
                
                birth_date = st.date_input(
                    "Datum rođenja",
                    value=None if not selected_employee or not selected_employee['birth_date'] 
                          else datetime.strptime(selected_employee['birth_date'], '%Y-%m-%d').date(),
                    min_value=date(1950, 1, 1),
                    format="DD/MM/YYYY"
                )
                
                hire_date = st.date_input(
                    "Datum zaposlenja",
                    value=date.today() if not selected_employee 
                          else datetime.strptime(selected_employee['hire_date'], '%Y-%m-%d').date(),
                    min_value=date(1950, 1, 1),
                    format="DD/MM/YYYY"
                )
            
            with col2:
                invalidity = st.checkbox("Status invaliditeta", 
                    value=selected_employee['invalidity'] if selected_employee else False)
                children = st.number_input("Broj djece mlađe od 15 godina", 
                    min_value=0, value=selected_employee['children_under15'] if selected_employee else 0)
                sole_caregiver = st.checkbox("Samohrani roditelj", 
                    value=selected_employee['sole_caregiver'] if selected_employee else False)
            
            # Pregledi
            st.markdown("### Pregledi")
            col1, col2 = st.columns(2)
            with col1:
                next_physical = st.date_input(
                    "Datum sljedećeg fizičkog pregleda",
                    value=None if not selected_employee or not selected_employee['next_physical_date']
                          else datetime.strptime(selected_employee['next_physical_date'], '%Y-%m-%d').date(),
                    format="DD/MM/YYYY"
                )
            with col2:
                next_psych = st.date_input(
                    "Datum sljedećeg psihičkog pregleda",
                    value=None if not selected_employee or not selected_employee['next_psych_date']
                          else datetime.strptime(selected_employee['next_psych_date'], '%Y-%m-%d').date(),
                    format="DD/MM/YYYY"
                )
            
            # Staž prije
            st.markdown("### Staž prije")
            col1, col2, col3 = st.columns(3)
            with col1:
                years = st.number_input("Godine", min_value=0, value=(
                    selected_employee['previous_experience_days'] // 365 if selected_employee else 0
                ))
            with col2:
                months = st.number_input("Mjeseci", min_value=0, max_value=11, value=(
                    (selected_employee['previous_experience_days'] % 365) // 30 if selected_employee else 0
                ))
            with col3:
                days = st.number_input("Dani", min_value=0, max_value=30, value=(
                    (selected_employee['previous_experience_days'] % 365) % 30 if selected_employee else 0
                ))

            # Prikaz ukupnog staža za odabranog zaposlenika
            if selected_employee:
                # Staž prije
                total_days = selected_employee.get('previous_experience_days', 0)
                y = total_days // 365
                rem = total_days % 365
                m = rem // 30
                d = rem % 30

                # Staž kod nas
                staz_kod_nas = compute_tenure(selected_employee['hire_date'])

                # Ukupni staž
                ukupni_staz = relativedelta(
                    years=staz_kod_nas.years + y,
                    months=staz_kod_nas.months + m,
                    days=staz_kod_nas.days + d
                )

                # Formatiraj prikaz
                parts = []
                if ukupni_staz.years: parts.append(f"{ukupni_staz.years}g")
                if ukupni_staz.months: parts.append(f"{ukupni_staz.months}m")
                if ukupni_staz.days: parts.append(f"{ukupni_staz.days}d")
                ukupni_staz_str = " ".join(parts) if parts else "0d"

                st.info(f"**Ukupni staž:** {ukupni_staz_str}")
            
            # Gumb za spremanje
            submitted = st.form_submit_button("💾 Spremi")
            
            if submitted:
                try:
                    data = {
                        'name': name,
                        'oib': oib,
                        'address': address,
                        'birth_date': birth_date.strftime('%Y-%m-%d') if birth_date else None,
                        'hire_date': hire_date.strftime('%Y-%m-%d') if hire_date else None,
                        'invalidity': invalidity,
                        'children_under15': children,
                        'sole_caregiver': sole_caregiver,
                        'next_physical_date': next_physical.strftime('%Y-%m-%d') if next_physical else None,
                        'next_psych_date': next_psych.strftime('%Y-%m-%d') if next_psych else None,
                        'previous_experience_days': (years or 0) * 365 + (months or 0) * 30 + (days or 0)
                    }
                    
                    if selected_employee:
                        edit_employee(selected_employee['id'], data)
                        st.success("✅ Zaposlenik uspješno ažuriran!")
                    else:
                        add_employee(data)
                        st.success("✅ Zaposlenik uspješno dodan!")
                except Exception as e:
                    st.error(f"❌ Greška prilikom dodavanja: {str(e)}")

    elif choice == "Pregled zaposlenika":
        rows = []
        for e in get_employees():
            # Staž prije
            total_days = e.get('previous_experience_days', 0)
            years = total_days // 365
            remaining_days = total_days % 365
            months = remaining_days // 30
            days = remaining_days % 30
            staz_prije_str = f"{years}g {months}m {days}d" if total_days else "0d"

            # Staž kod nas
            staz_kod_nas = compute_tenure(e['hire_date'])
            staz_kod_nas_str = format_rd(staz_kod_nas)
            staz_kod_nas_days = staz_kod_nas.years * 365 + staz_kod_nas.months * 30 + staz_kod_nas.days

            # Ukupni staž
            ukupni_staz = relativedelta(date.today(), datetime.strptime(e['hire_date'], '%Y-%m-%d').date())
            ukupni_staz = relativedelta(
                years=ukupni_staz.years + years,
                months=ukupni_staz.months + months,
                days=ukupni_staz.days + days
            )
            ukupni_staz_str = format_rd(ukupni_staz)
            ukupni_staz_days = ukupni_staz.years * 365 + ukupni_staz.months * 30 + ukupni_staz.days

            leave = compute_leave(e['hire_date'], e['invalidity'], e['children_under15'], e['sole_caregiver'],
                                  e.get('previous_experience_days', 0))

            # Računanje ukupno iskorištenih dana
            leave_records = get_leave_records(e['id'])
            used = 0
            for lr in leave_records:
                if lr['adjustment'] is None:
                    start = datetime.strptime(parse_date(lr['start']), '%Y-%m-%d').date()
                    end = datetime.strptime(parse_date(lr['end']), '%Y-%m-%d').date()
                    used += (end - start).days + 1
                else:
                    used -= lr['adjustment']

            rem = leave - used

            fiz_pregled = format_date(e['next_physical_date']) or 'Nema pregleda'
            psih_pregled = format_date(e['next_psych_date']) or 'Nema pregleda'

            fiz_pregled_sort = parse_date_for_sort(fiz_pregled)
            psih_pregled_sort = parse_date_for_sort(psih_pregled)

            rows.append({
                'Ime': e['name'],
                'Datum zapos.': e['hire_date'],
                'Staž prije': staz_prije_str,
                'Staž kod nas': staz_kod_nas_str,
                'Ukupni staž': ukupni_staz_str,
                'Godišnji (dana)': leave,
                'Preostalo godišnji': rem,
                'Sljedeći fiz. pregled': fiz_pregled_sort,
                'Sljedeći psih. pregled': psih_pregled_sort
            })

        df = pd.DataFrame(rows)

        if df.empty:
            st.warning("Nema zaposlenika u bazi!")
        else:
            st.dataframe(
                df[
                    ["Ime", "Datum zapos.", "Staž prije", "Staž kod nas", "Ukupni staž",
                     "Godišnji (dana)", "Preostalo godišnji", "Sljedeći fiz. pregled", "Sljedeći psih. pregled"]
                ].reset_index(drop=True),
                use_container_width=True,
                height=800
            )

if __name__=='__main__':
    main()
