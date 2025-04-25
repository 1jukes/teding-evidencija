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
        c.execute('ALTER TABLE employees ADD COLUMN physical_required INTEGER NOT NULL DEFAULT 1')
    except:
        pass
    try:
        c.execute('ALTER TABLE employees ADD COLUMN psych_required INTEGER NOT NULL DEFAULT 1')
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
    y = relativedelta(date.today(), datetime.strptime(hire, '%Y-%m-%d').date()).years
    days = 20 + (5 if invalidity else 0)
    if 10 <= y < 20: days += 1
    elif 20 <= y < 30: days += 2
    elif y >= 30: days += 3
    if sole: days += 3
    elif children == 1: days += 1
    elif children >= 2: days += 2
    return days

# CRUD employee

def add_employee(data):
    try:
        print("Debug - Adding employee with data:", data)  # Debug ispis
        
        # Osiguraj da su svi datumi ili string ili None
        hire_date = data['hire']
        last_phys = data['last_phys'] if data['phys_req'] else None
        next_phys = data['next_phys'] if data['phys_req'] else None
        last_psy = data['last_psy'] if data['psy_req'] else None
        next_psy = data['next_psy'] if data['psy_req'] else None

        print(f"Debug - Dates: hire={hire_date}, last_phys={last_phys}, next_phys={next_phys}")  # Debug ispis

        c.execute('''INSERT INTO employees
                     (name, hire_date, training_start_date, last_physical_date, last_psych_date,
                      next_physical_date, next_psych_date, invalidity, children_under15, sole_caregiver,
                      physical_required, psych_required)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (data['name'], hire_date, hire_date, 
                   last_phys, last_psy, next_phys, next_psy,
                   int(data['invalidity']), int(data['children']), int(data['sole']),
                   int(data['phys_req']), int(data['psy_req'])))
        
        emp_id = c.lastrowid
        for j in st.session_state.new_jobs:
            c.execute('INSERT INTO prev_jobs(emp_id,company,start_date,end_date) VALUES (?,?,?,?)',
                      (emp_id, j['company'], j['start'], j['end']))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding employee: {e}")  # Debug ispis
        conn.rollback()
        return False

def edit_employee(emp_id, data):
    try:
        # Postavi datume na None ako pregledi nisu obavezni
        last_phys = data['last_phys'] if data['phys_req'] else None
        next_phys = data['next_phys'] if data['phys_req'] else None
        last_psy = data['last_psy'] if data['psy_req'] else None
        next_psy = data['next_psy'] if data['psy_req'] else None

        c.execute('''UPDATE employees SET
                     name=?, hire_date=?, training_start_date=?, last_physical_date=?, last_psych_date=?,
                     next_physical_date=?, next_psych_date=?, invalidity=?, children_under15=?, sole_caregiver=?,
                     physical_required=?, psych_required=?
                     WHERE id=?''',
                  (data['name'], data['hire'], data['hire'], 
                   last_phys, last_psy, next_phys, next_psy,
                   int(data['invalidity']), int(data['children']), int(data['sole']),
                   int(data['phys_req']), int(data['psy_req']), emp_id))
        
        c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
        for j in st.session_state.edit_jobs:
            c.execute('INSERT INTO prev_jobs(emp_id,company,start_date,end_date) VALUES (?,?,?,?)',
                      (emp_id, j['company'], j['start'], j['end']))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error editing employee: {e}")
        conn.rollback()
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
    
    st.title('Evidencija zaposlenika - pregledi, staž i godišnji')
    menu = st.sidebar.selectbox('Izbornik',
                               ['Prikaz zaposlenika','Evidencija godišnjih',
                                'Dodaj zaposlenika','Uredi zaposlenika','Obriši zaposlenika'],
                               key='menu')
    
    # Dodaj gumb za odjavu u sidebar
    if st.sidebar.button("Odjava"):
        st.session_state["authenticated"] = False
        st.rerun()
    
    emps = get_employees()
    names = [e['name'] for e in emps]

    if menu == 'Prikaz zaposlenika':
        rows = []
        for e in emps:
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
            phys = datetime.strptime(e['next_physical_date'],'%Y-%m-%d').date()
            psych = datetime.strptime(e['next_psych_date'],'%Y-%m-%d').date()
            phys_str = format_date(phys.strftime('%Y-%m-%d')) if 0 <= (phys-date.today()).days <=30 else ''
            psych_str = format_date(psych.strftime('%Y-%m-%d')) if 0 <= (psych-date.today()).days <=30 else ''
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

    elif menu == 'Evidencija godišnjih':
        # Reset form state when page loads
        if 'leave_form_submitted' not in st.session_state:
            st.session_state.leave_form_submitted = False
        
        sel = st.selectbox('Odaberi zaposlenika', names, key='leave_select')
        emp = next(e for e in emps if e['name']==sel)
        
        st.subheader('Evidencija korištenja godišnjeg')
        
        # Form za unos godišnjeg
        with st.form('leave_form'):
            start = st.date_input('Početak godišnjeg', None, format="DD.MM.YYYY")
            end = st.date_input('Kraj godišnjeg', None, format="DD.MM.YYYY")
            
            submit_leave = st.form_submit_button('Spremi godišnji')
            
            if submit_leave:
                if start and end:
                    add_leave_record(emp['id'], start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
                    st.success('Godišnji evidentiran')
                    st.session_state.leave_form_submitted = True
                    st.rerun()
                else:
                    st.error('Molimo unesite datum početka i kraja godišnjeg')
        
        st.subheader('Dodaj/Oduzmi dane godišnjeg')
        # Form za dodavanje/oduzimanje dana
        with st.form('adjustment_form'):
            days = st.number_input('Broj dana', min_value=1, value=1)
            note = st.text_input('Napomena (npr. "Neiskorišteni GO iz 2023")', value="")
            
            col1, col2 = st.columns(2)
            add = col1.form_submit_button('Dodaj')
            subtract = col2.form_submit_button('Oduzmi')
            
            if add or subtract:
                operation = 'add' if add else 'subtract'
                add_days_adjustment(emp['id'], days, operation, note)
                st.success(f"{'Dodano' if add else 'Oduzeto'} {days} dana")
                st.rerun()
        
        st.subheader('Evidencija')
        leave_records = get_leave_records(emp['id'])
        total_days = 0
        
        for lr in leave_records:
            col1, col2 = st.columns([3, 1])
            if lr['adjustment'] is None:
                start_date = datetime.strptime(parse_date(lr['start']), '%Y-%m-%d').date()
                end_date = datetime.strptime(parse_date(lr['end']), '%Y-%m-%d').date()
                days = (end_date - start_date).days + 1
                total_days += days
                col1.write(f"- {lr['start']} ➜ {lr['end']} ({days} dana)")
            else:
                total_days -= lr['adjustment']
                txt = "Dodano" if lr['adjustment'] > 0 else "Oduzeto"
                note_text = f" - {lr['note']}" if lr['note'] else ""
                col1.write(f"- {txt} {abs(lr['adjustment'])} dana ({lr['start']}){note_text}")
            
            if col2.button('Obriši', key=f"del_leave_{lr['id']}"):
                if delete_leave_record(emp['id'], lr['id']):
                    st.rerun()
        
        leave_allowance = compute_leave(emp['hire_date'], emp['invalidity'], 
                                      emp['children_under15'], emp['sole_caregiver'])
        st.markdown(f"**Preostalo dana godišnjeg: {leave_allowance - total_days}**")

    elif menu == 'Dodaj zaposlenika':
        if 'new_jobs' not in st.session_state:
            st.session_state.new_jobs = []
        
        with st.form('emp_form'):
            name = st.text_input('Ime i prezime', value="")
            hire = st.date_input('Datum zaposlenja',
                               value=None,
                               min_value=date(1960,1,1),
                               format="DD.MM.YYYY")
            
            st.markdown('### Pregledi')
            c3,c4 = st.columns(2)
            with c3:
                st.markdown('**Fizički pregled**')
                last_phys = st.date_input('Zadnji fizički pregled',
                                     value=None,
                                     min_value=date(1960,1,1),
                                     format="DD.MM.YYYY",
                                     key='last_phys_date')
                next_phys = st.date_input('Sljedeći fizički pregled',
                                     value=None,
                                     min_value=date.today(),
                                     format="DD.MM.YYYY",
                                     key='next_phys_date')
            
            with c4:
                st.markdown('**Psihički pregled**')
                last_psy = st.date_input('Zadnji psihički pregled',
                                    value=None,
                                    min_value=date(1960,1,1),
                                    format="DD.MM.YYYY",
                                    key='last_psy_date')
                next_psy = st.date_input('Sljedeći psihički pregled',
                                    value=None,
                                    min_value=date.today(),
                                    format="DD.MM.YYYY",
                                    key='next_psy_date')

            st.markdown('### Dodatne informacije')
            c5, c6, c7, c8 = st.columns([1,1,1,3])
            invalidity = c5.checkbox('Invaliditet (+5)', value=False)
            children = c6.number_input('Broj djece <15',
                                     min_value=0,
                                     max_value=10,
                                     value=0,
                                     step=1,
                                     key='children_count',
                                     label_visibility="collapsed")
            c6.caption('Broj djece <15')
            sole = c7.checkbox('Samohranitelj (+3)', value=False)

            submit = st.form_submit_button('Spremi zaposlenika')
            
            if submit:
                if not name or not hire:
                    st.error('Molimo unesite ime i datum zaposlenja')
                else:
                    data = {
                        'name': name,
                        'hire': hire.strftime('%Y-%m-%d'),
                        'last_phys': last_phys.strftime('%Y-%m-%d') if last_phys else None,
                        'last_psy': last_psy.strftime('%Y-%m-%d') if last_psy else None,
                        'next_phys': next_phys.strftime('%Y-%m-%d') if next_phys else None,
                        'next_psy': next_psy.strftime('%Y-%m-%d') if next_psy else None,
                        'invalidity': invalidity,
                        'children': children,
                        'sole': sole,
                        'phys_req': False,
                        'psy_req': False
                    }
                    
                    if add_employee(data):
                        st.success('Zaposlenik uspješno dodan')
                        st.session_state.new_jobs = []
                        st.rerun()
                    else:
                        st.error('Greška prilikom dodavanja zaposlenika')

    elif menu == 'Uredi zaposlenika':
        sel = st.selectbox('Odaberi zaposlenika',names,key='edit_select')
        emp = next(e for e in emps if e['name']==sel)
        
        with st.form('edit_form', clear_on_submit=True):
            name = st.text_input('Ime i prezime',value=emp['name'])
            hire = st.date_input('Datum zaposlenja',
                               value=datetime.strptime(emp['hire_date'],'%Y-%m-%d').date(),
                               min_value=date(1960,1,1),
                               format="DD.MM.YYYY")
            
            st.markdown('### Pregledi')
            c3,c4 = st.columns(2)
            with c3:
                st.markdown('**Fizički pregled**')
                last_phys = st.date_input('Zadnji fizički pregled',
                                     value=None,
                                     min_value=date(1960,1,1),
                                     format="DD.MM.YYYY",
                                     key='edit_last_phys_date')
                next_phys = st.date_input('Sljedeći fizički pregled',
                                     value=None,
                                     min_value=date.today(),
                                     format="DD.MM.YYYY",
                                     key='edit_next_phys_date')
            
            with c4:
                st.markdown('**Psihički pregled**')
                last_psy = st.date_input('Zadnji psihički pregled',
                                    value=None,
                                    min_value=date(1960,1,1),
                                    format="DD.MM.YYYY",
                                    key='edit_last_psy_date')
                next_psy = st.date_input('Sljedeći psihički pregled',
                                    value=None,
                                    min_value=date.today(),
                                    format="DD.MM.YYYY",
                                    key='edit_next_psy_date')

            st.markdown('### Dodatne informacije')
            c5, c6, c7, c8 = st.columns([1,1,1,3])
            invalidity = c5.checkbox('Invaliditet (+5)', value=bool(emp['invalidity']))
            children = c6.number_input('Broj djece <15',
                                     min_value=0,
                                     max_value=10,
                                     value=int(emp['children_under15']),
                                     step=1,
                                     key='children_count_edit',
                                     label_visibility="collapsed")
            c6.caption('Broj djece <15')
            sole = c7.checkbox('Samohranitelj (+3)', value=bool(emp['sole_caregiver']))

            submit = st.form_submit_button('Spremi promjene')
            
            if submit:
                data = {
                    'name': name,
                    'hire': hire.strftime('%Y-%m-%d'),
                    'last_phys': last_phys.strftime('%Y-%m-%d') if last_phys else None,
                    'last_psy': last_psy.strftime('%Y-%m-%d') if last_psy else None,
                    'next_phys': next_phys.strftime('%Y-%m-%d') if next_phys else None,
                    'next_psy': next_psy.strftime('%Y-%m-%d') if next_psy else None,
                    'invalidity': invalidity,
                    'children': children,
                    'sole': sole,
                    'phys_req': False,
                    'psy_req': False
                }
                edit_employee(emp['id'], data)
                st.success('Uređeno')
                st.rerun()

    elif menu == 'Obriši zaposlenika':
        sel = st.selectbox('Odaberi zaposlenika za brisanje',names,key='del_select')
        if st.button('Obriši zaposlenika'):
            emp = next(e for e in emps if e['name']==sel)
            delete_employee(emp['id'])
            st.success('Obrisano')
            st.rerun()

if __name__=='__main__':
    main()
