import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import hashlib
import base64

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
            last_physical_date TEXT NOT NULL,
            last_psych_date TEXT NOT NULL,
            next_physical_date TEXT NOT NULL,
            next_psych_date TEXT NOT NULL,
            invalidity INTEGER NOT NULL DEFAULT 0,
            children_under15 INTEGER NOT NULL DEFAULT 0,
            sole_caregiver INTEGER NOT NULL DEFAULT 0
        )
    ''')
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
    return [{'company':r[0],'start':r[1],'end':r[2]} for r in c.fetchall()]

def get_leave_records(emp_id):
    c.execute('''SELECT start_date, end_date, days_adjustment, note 
                 FROM leave_records 
                 WHERE emp_id=?''', (emp_id,))
    return [{'start':r[0], 'end':r[1], 'adjustment':r[2], 'note':r[3]} for r in c.fetchall()]

# Business logic
def compute_tenure(hire):
    d = date.today()
    h = datetime.strptime(hire, '%Y-%m-%d').date()
    return relativedelta(d, h)

def format_rd(rd):
    parts = []
    if rd.years: parts.append(f"{rd.years}g")
    if rd.months: parts.append(f"{rd.months}m")
    if rd.days: parts.append(f"{rd.days}d")
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
    c.execute('''INSERT INTO employees
                 (name, hire_date, training_start_date, last_physical_date, last_psych_date,
                  next_physical_date, next_psych_date, invalidity, children_under15, sole_caregiver)
                 VALUES (?,?,?,?,?,?,?,?,?,?)''',
              (data['name'], data['hire'], data['hire'], data['last_phys'], data['last_psy'],
               data['next_phys'], data['next_psy'], int(data['invalidity']), data['children'], int(data['sole'])))
    emp_id = c.lastrowid
    for j in st.session_state.new_jobs:
        c.execute('INSERT INTO prev_jobs(emp_id,company,start_date,end_date) VALUES (?,?,?,?)',
                  (emp_id, j['company'], j['start'], j['end']))
    conn.commit()

def edit_employee(emp_id, data):
    c.execute('''UPDATE employees SET
                 name=?, hire_date=?, training_start_date=?, last_physical_date=?, last_psych_date=?,
                 next_physical_date=?, next_psych_date=?, invalidity=?, children_under15=?, sole_caregiver=?
                 WHERE id=?''',
              (data['name'], data['hire'], data['hire'], data['last_phys'], data['last_psy'],
               data['next_phys'], data['next_psy'], int(data['invalidity']), data['children'], int(data['sole']), emp_id))
    c.execute('DELETE FROM prev_jobs WHERE emp_id=?', (emp_id,))
    for j in st.session_state.edit_jobs:
        c.execute('INSERT INTO prev_jobs(emp_id,company,start_date,end_date) VALUES (?,?,?,?)',
                  (emp_id, j['company'], j['start'], j['end']))
    conn.commit()

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

def delete_leave_record(emp_id, start_date, end_date):
    c.execute('DELETE FROM leave_records WHERE emp_id=? AND start_date=? AND end_date=?',
              (emp_id, start_date, end_date))
    conn.commit()

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
                    datetime.strptime(j['end'],'%Y-%m-%d').date(),
                    datetime.strptime(j['start'],'%Y-%m-%d').date())
                rd_before += rd
            rd_tot = rd_curr + rd_before
            leave = compute_leave(e['hire_date'], e['invalidity'], e['children_under15'], e['sole_caregiver'])
            
            # Računanje ukupno iskorištenih dana
            leave_records = get_leave_records(e['id'])
            used = 0
            for lr in leave_records:
                if lr['adjustment'] is None:
                    used += (datetime.strptime(lr['end'],'%Y-%m-%d').date() - 
                            datetime.strptime(lr['start'],'%Y-%m-%d').date()).days + 1
                else:
                    used -= lr['adjustment']  # Oduzimamo jer želimo da pozitivna prilagodba poveća preostale dane
            
            rem = leave - used
            phys = datetime.strptime(e['next_physical_date'],'%Y-%m-%d').date()
            psych = datetime.strptime(e['next_psych_date'],'%Y-%m-%d').date()
            phys_str = phys.strftime('%Y-%m-%d') if 0 <= (phys-date.today()).days <=30 else ''
            psych_str = psych.strftime('%Y-%m-%d') if 0 <= (psych-date.today()).days <=30 else ''
            rows.append({
                'Ime':e['name'],
                'Datum zapos.':e['hire_date'],
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
        sel = st.selectbox('Odaberi zaposlenika',names,key='leave_select')
        emp = next(e for e in emps if e['name']==sel)
        
        st.subheader('Evidencija korištenja godišnjeg')
        start = st.date_input('Početak godišnjeg',date.today())
        end = st.date_input('Kraj godišnjeg',date.today())
        if st.button('Spremi godišnji',key='save_leave'):
            add_leave_record(emp['id'],start.strftime('%Y-%m-%d'),end.strftime('%Y-%m-%d'))
            st.success('Godišnji evidentiran')
            st.rerun()
        
        st.subheader('Dodaj/Oduzmi dane godišnjeg')
        days = st.number_input('Broj dana', min_value=1, value=1)
        note = st.text_input('Napomena (npr. "Neiskorišteni GO iz 2023")', key='note_input')
        
        col1, col2, col3 = st.columns([1,1,4])
        if col1.button('Dodaj', key='btn_add_days'):
            add_days_adjustment(emp['id'], days, 'add', note)
            st.success(f'Dodano {days} dana')
            st.rerun()
        if col2.button('Oduzmi', key='btn_subtract_days'):
            add_days_adjustment(emp['id'], days, 'subtract', note)
            st.success(f'Oduzeto {days} dana')
            st.rerun()
        
        st.subheader('Evidencija')
        leave_records = get_leave_records(emp['id'])
        total_days = 0
        for idx, lr in enumerate(leave_records):
            col1, col2 = st.columns([3, 1])
            if lr['adjustment'] is None:
                start_date = datetime.strptime(lr['start'], '%Y-%m-%d').date()
                end_date = datetime.strptime(lr['end'], '%Y-%m-%d').date()
                days = (end_date - start_date).days + 1
                total_days += days
                col1.write(f"- {lr['start']} ➜ {lr['end']} ({days} dana)")
            else:
                total_days -= lr['adjustment']  # Oduzimamo jer želimo da pozitivna prilagodba poveća preostale dane
                txt = "Dodano" if lr['adjustment'] > 0 else "Oduzeto"
                note_text = f" - {lr['note']}" if lr['note'] else ""
                col1.write(f"- {txt} {abs(lr['adjustment'])} dana ({lr['start']}){note_text}")
            
            if col2.button('Obriši', key=f"del_leave_{idx}"):
                delete_leave_record(emp['id'], lr['start'], lr['end'])
                st.rerun()
        
        leave_allowance = compute_leave(emp['hire_date'], emp['invalidity'], 
                                      emp['children_under15'], emp['sole_caregiver'])
        st.markdown(f"**Preostalo dana godišnjeg: {leave_allowance - total_days}**")

    elif menu in ['Dodaj zaposlenika','Uredi zaposlenika']:
        new = (menu=='Dodaj zaposlenika')
        if new:
            emp = {'name':'','hire_date':date.today().strftime('%Y-%m-%d'),
                   'last_physical_date':date.today().strftime('%Y-%m-%d'),
                   'last_psych_date':date.today().strftime('%Y-%m-%d'),
                   'next_physical_date':date.today().strftime('%Y-%m-%d'),
                   'next_psych_date':date.today().strftime('%Y-%m-%d'),
                   'invalidity':False,'children_under15':0,'sole_caregiver':False}
            if 'new_jobs' not in st.session_state:
                st.session_state.new_jobs = []
        else:
            sel = st.selectbox('Odaberi zaposlenika',names,key='edit_select')
            emp = next(e for e in emps if e['name']==sel)
            if 'edit_jobs' not in st.session_state:
                st.session_state.edit_jobs = get_prev_jobs(emp['id'])

        with st.form('emp_form'):
            c1,c2,c3 = st.columns(3)
            name = c1.text_input('Ime i prezime',value=emp['name'])
            hire = c2.date_input('Datum zaposlenja',value=datetime.strptime(emp['hire_date'],'%Y-%m-%d').date(),min_value=date(1960,1,1))
            invalidity = c3.checkbox('Invaliditet (+5)',value=bool(emp['invalidity']))
            c4,c5,c6 = st.columns(3)
            last_phys = c4.date_input('Zadnji fiz.',value=datetime.strptime(emp['last_physical_date'],'%Y-%m-%d').date(),min_value=date(1960,1,1))
            last_psy = c5.date_input('Zadnji psih.',value=datetime.strptime(emp['last_psych_date'],'%Y-%m-%d').date(),min_value=date(1960,1,1))
            children = c6.number_input('Broj djece <15',min_value=0,value=int(emp['children_under15']))
            c7,c8,c9 = st.columns(3)
            next_phys = c7.date_input('Sljedeći fiz.',value=datetime.strptime(emp['next_physical_date'],'%Y-%m-%d').date(),min_value=date(1960,1,1))
            next_psy = c8.date_input('Sljedeći psih.',value=datetime.strptime(emp['next_psych_date'],'%Y-%m-%d').date(),min_value=date(1960,1,1))
            sole = c9.checkbox('Samohranitelj (+3)',value=bool(emp['sole_caregiver']))
            submit = st.form_submit_button('Spremi zaposlenika')

        st.markdown('**Prethodno iskustvo**')
        if not new:
            st.markdown('**Postojeća iskustva:**')
            existing_jobs = get_prev_jobs(emp['id'])
            for j in existing_jobs:
                st.write(f"• {j['company']}: {j['start']} ➜ {j['end']}")
            st.markdown('---')
            
        comp = st.text_input('Tvrtka za dodati',key='comp_add')
        st_d = st.date_input('Početak za dodati',key='st_add')
        en_d = st.date_input('Kraj za dodati',key='en_add')
        if st.button('Dodaj iskustvo',key='add_job_btn'):
            rec = {'company':comp,'start':st_d.strftime('%Y-%m-%d'),'end':en_d.strftime('%Y-%m-%d')}
            if new:
                if 'new_jobs' not in st.session_state:
                    st.session_state.new_jobs = []
                st.session_state.new_jobs.append(rec)
            else:
                if 'edit_jobs' not in st.session_state:
                    st.session_state.edit_jobs = []
                st.session_state.edit_jobs.append(rec)

        jobs = st.session_state.new_jobs if new else st.session_state.edit_jobs
        if jobs:
            st.markdown('**Nova iskustva za dodati:**')
            for idx, j in enumerate(jobs):
                col1, col2 = st.columns([3, 1])
                col1.write(f"• {j['company']}: {j['start']} ➜ {j['end']}")
                if col2.button('Obriši', key=f"del_job_{idx}"):
                    if new:
                        st.session_state.new_jobs.pop(idx)
                    else:
                        st.session_state.edit_jobs.pop(idx)
                    st.rerun()

        if submit:
            data = {'name':name,'hire':hire.strftime('%Y-%m-%d'),'last_phys':last_phys.strftime('%Y-%m-%d'),
                    'last_psy':last_psy.strftime('%Y-%m-%d'),'next_phys':next_phys.strftime('%Y-%m-%d'),
                    'next_psy':next_psy.strftime('%Y-%m-%d'),'invalidity':invalidity,
                    'children':children,'sole':sole}
            if new:
                add_employee(data)
                st.success('Dodano')
                st.session_state.new_jobs = []
            else:
                edit_employee(emp['id'], data)
                st.success('Uređeno')
                st.session_state.edit_jobs = get_prev_jobs(emp['id'])
            st.rerun()

    else:
        sel = st.selectbox('Odaberi zaposlenika za brisanje',names,key='del_select')
        emp = next(e for e in emps if e['name']==sel)
        if st.button('Obriši zaposlenika'):
            delete_employee(emp['id'])
            st.success('Obrisano')

if __name__=='__main__':
    main()
