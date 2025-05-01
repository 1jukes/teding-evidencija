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

# Konfiguracija stranice
st.set_page_config(
    page_title="Teding - Evidencija zaposlenika",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
    return conn, c

conn, c = init_db()

# CRUD funkcije
def get_employees():
    c.execute('SELECT * FROM employees')
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('SELECT id, start_date, end_date, days_adjustment, note FROM leave_records WHERE emp_id=?', (emp_id,))
    return [{'id': r[0], 'start': format_date(r[1]), 'end': format_date(r[2]), 
             'adjustment': r[3], 'note': r[4]} for r in c.fetchall()]

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

def add_leave_record(emp_id, s, e):
    c.execute('INSERT INTO leave_records (emp_id, start_date, end_date) VALUES (?, ?, ?)',
              (emp_id, s, e))
    conn.commit()

def add_days_adjustment(emp_id, days, operation='add', note=None):
    days_value = days if operation == 'add' else -days  # Ispravljena logika
    today = date.today().strftime('%Y-%m-%d')
    c.execute('INSERT INTO leave_records(emp_id,start_date,end_date,days_adjustment,note) VALUES (?,?,?,?,?)',
              (emp_id, today, today, days_value, note))
    conn.commit()

def delete_leave_record(emp_id, record_id):
    try:
        c.execute('DELETE FROM leave_records WHERE emp_id=? AND id=?', (emp_id, record_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting record: {e}")
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

        # Povijest promjena
        st.markdown("### Povijest promjena")
        records_df = pd.DataFrame([
            {
                'Datum': format_date(r['start']),
                'Promjena': f"+{r['adjustment']}" if r['adjustment'] > 0 else str(r['adjustment']),
                'Napomena': r['note'] or '',
                'ID': r['id']
            }
            for r in leave_records if r['adjustment'] is not None
        ])
        
        if not records_df.empty:
            records_df = records_df.sort_values('Datum', ascending=False)
            for index, row in records_df.iterrows():
                col1, col2 = st.columns([6, 1])
                with col1:
                    st.write(f"**{row['Datum']}**: {row['Promjena']} dana - {row['Napomena']}")
                with col2:
                    st.write("")  # Prazan prostor za poravnanje
                    if st.button("Obriši", key=f"del_record_{row['ID']}_{index}", use_container_width=True):  # Dodali smo index u ključ
                        delete_leave_record(emp['id'], row['ID'])
                        st.rerun()

        # Ručno podešavanje dana
        st.markdown("### Ručno podešavanje dana")
        col1, col2, col3, col4 = st.columns([2,4,1,1])
        
        with col1:
            days = st.number_input("Broj dana", min_value=1, value=1)
        with col2:
            note = st.text_input("Napomena")
        with col3:
            if st.button("➕ Dodaj", use_container_width=True):
                try:
                    add_days_adjustment(emp['id'], days, 'add', note)
                    st.success("✅ Dodano!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Greška: {str(e)}")
        with col4:
            if st.button("➖ Oduzmi", use_container_width=True):
                try:
                    add_days_adjustment(emp['id'], days, 'subtract', note)
                    st.success("✅ Oduzeto!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Greška: {str(e)}")

        # Evidencija korištenja
        st.markdown("### Evidencija korištenja")
        
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
        
        # Prikaz evidencije
        if leave_records:
            for record in leave_records:
                col1, col2, col3, col4 = st.columns([2,2,2,1])
                with col1:
                    if record['adjustment'] is not None:
                        operation = "Dodano" if record['adjustment'] < 0 else "Oduzeto"
                        st.write(f"**{operation}:** {abs(record['adjustment'])} dana")
                        if record['note']:
                            st.write(f"**Napomena:** {record['note']}")
                    else:
                        st.write(f"**Od:** {record['start']}")
                with col2:
                    if record['adjustment'] is None:
                        st.write(f"**Do:** {record['end']}")
                with col3:
                    if record['adjustment'] is None:
                        start = datetime.strptime(parse_date(record['start']), '%Y-%m-%d').date()
                        end = datetime.strptime(parse_date(record['end']), '%Y-%m-%d').date()
                        days = (end - start).days + 1
                        st.write(f"**Broj dana:** {days}")
                with col4:
                    if st.button("Obriši", key=f"del_{record['id']}"):
                        try:
                            delete_leave_record(emp['id'], record['id'])
                            st.success("✅ Zapis obrisan!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Greška: {str(e)}")
        else:
            st.write("Nema evidencije korištenja godišnjeg odmora.")

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
        
        st.write(f"**Godišnji (prema pravilniku):** {leave_days} dana")
        st.write(f"**Preostali godišnji:** {remaining_days} dana")

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
                birth_date = st.date_input("Datum rođenja", 
                    value=datetime.strptime(selected_employee['birth_date'], '%Y-%m-%d').date() if selected_employee and selected_employee['birth_date'] else None,
                    min_value=datetime(1950, 1, 1).date(),
                    max_value=date.today())
                hire_date = st.date_input("Datum zaposlenja",
                    value=datetime.strptime(selected_employee['hire_date'], '%Y-%m-%d').date() if selected_employee else date.today())
            
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
                next_physical = st.date_input("Datum sljedećeg fizičkog pregleda", 
                    value=datetime.strptime(selected_employee['next_physical_date'], '%Y-%m-%d').date() if selected_employee and selected_employee['next_physical_date'] else None,
                    key="physical_date")
            with col2:
                next_psych = st.date_input("Datum sljedećeg psihičkog pregleda",
                    value=datetime.strptime(selected_employee['next_psych_date'], '%Y-%m-%d').date() if selected_employee and selected_employee['next_psych_date'] else None,
                    key="psych_date")
            
            # Staž prije
            st.markdown("### Staž prije")
            col1, col2, col3 = st.columns(3)
            with col1:
                years = st.number_input("Godine", min_value=0, value=0)
            with col2:
                months = st.number_input("Mjeseci", min_value=0, max_value=11, value=0)
            with col3:
                days = st.number_input("Dani", min_value=0, max_value=30, value=0)
            
            # Pretvori u ukupne dane za spremanje
            total_days = years * 365 + months * 30 + days
            
            # Gumb za spremanje
            if st.form_submit_button("Spremi"):
                try:
                    data = {
                        'name': name,
                        'oib': oib,
                        'address': address,
                        'birth_date': birth_date.strftime('%Y-%m-%d') if birth_date else None,
                        'hire_date': hire_date.strftime('%Y-%m-%d'),
                        'invalidity': invalidity,
                        'children_under15': children,
                        'sole_caregiver': sole_caregiver,
                        'next_physical_date': next_physical.strftime('%Y-%m-%d') if next_physical else None,
                        'next_psych_date': next_psych.strftime('%Y-%m-%d') if next_psych else None,
                        'previous_experience_days': total_days
                    }
                    
                    if selected_employee:
                        edit_employee(selected_employee['id'], data)
                        st.success("✅ Zaposlenik uspješno ažuriran!")
                    else:
                        add_employee(data)
                        st.success("✅ Zaposlenik uspješno dodan!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Greška: {str(e)}")

    elif choice == "Pregled zaposlenika":
        rows = []
        for e in get_employees():
            rd_curr = compute_tenure(e['hire_date'])
            
            # Izračun staža prije iz dana
            total_days = e.get('previous_experience_days', 0)
            years = total_days // 365
            remaining_days = total_days % 365
            months = remaining_days // 30
            days = remaining_days % 30
            
            staz_prije = []
            if years: staz_prije.append(f"{years}g")
            if months: staz_prije.append(f"{months}m")
            if days: staz_prije.append(f"{days}d")
            staz_prije_str = " ".join(staz_prije) if staz_prije else "0d"
            
            leave = compute_leave(e['hire_date'], e['invalidity'], e['children_under15'], e['sole_caregiver'])
            
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
            
            rows.append({
                'Ime':e['name'],
                'Datum zapos.':format_date(e['hire_date']),
                'Staž prije': staz_prije_str,
                'Staž kod nas':format_rd(rd_curr),
                'Godišnji (dana)':leave,
                'Preostalo godišnji':rem,
                'Sljedeći fiz. pregled':format_date(e['next_physical_date']) or 'Nema pregleda',
                'Sljedeći psih. pregled':format_date(e['next_psych_date']) or 'Nema pregleda'
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

if __name__=='__main__':
    main()
