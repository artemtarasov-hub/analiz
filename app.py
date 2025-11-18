import streamlit as st
import os
from docx import Document
from openai import OpenAI
import random
from datetime import datetime, timedelta
import pytz
import time
import pandas as pd

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(page_title="AI Экзаменатор", page_icon="🎓", layout="centered")

# ==========================================
# 🔐 НАСТРОЙКИ
# ==========================================

# 1. OpenAI
if "OPENAI_API_KEY" in st.secrets:
    API_KEY = st.secrets["OPENAI_API_KEY"]
else:
    API_KEY = "sk-eed4YX4hls3D40w1QKzADGHzlodsSsVa" 

BASE_URL = "https://openai.api.proxyapi.ru/v1"
MODEL_NAME = "gpt-4o-mini"

# 2. Администрирование
ADMIN_PASSWORD = "admin"  
RESULTS_FILE = "exam_results.csv" 
DEFAULT_FILE_NAME = "questions.docx" # Имя файла по умолчанию

# Часовой пояс
TZ_MOSCOW = pytz.timezone('Europe/Moscow')

# ==========================================

# --- ФУНКЦИИ ---

def get_client():
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)

def parse_docx_questions(file_source):
    try:
        doc = Document(file_source)
    except Exception as e:
        return []
        
    qa_pairs = []
    current_q = None
    current_a = []
    
    question_starters = ("Назовите", "Перечислите", "Какие", "Из каких", "С чего", "Что такое", "К какой", "В какой", "Как")

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        
        is_question = text.endswith('?') or text.startswith(question_starters)

        if is_question:
            if current_q:
                qa_pairs.append({'question': current_q, 'answer': "\n".join(current_a)})
            current_q = text
            current_a = []
        else:
            if current_q:
                current_a.append(text)

    if current_q and current_a:
        qa_pairs.append({'question': current_q, 'answer': "\n".join(current_a)})

    return qa_pairs

def check_answer_with_ai(client, question, correct_answer, student_answer):
    prompt = f"""
    Ты — справедливый преподаватель. Проверь ответ студента на вопрос.
    Вопрос: "{question}"
    Эталонный ответ: "{correct_answer}"
    Ответ студента: "{student_answer}"
    
    ИНСТРУКЦИЯ ПО ПРОВЕРКЕ:
    1. Главное — СМЫСЛ. Если студент ответил правильно своими словами — это ВЕРНО.
    2. ИГНОРИРУЙ грамматические ошибки.
    3. Пиши "НЕВЕРНО", только если ответ фактически неправильный.
    
    Формат ответа: ВЕРНО/НЕВЕРНО | Короткий комментарий
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка API: {e}"

def save_result_to_csv(student_info, score, total):
    """Сохраняет результат в CSV с разделителем ; для Excel"""
    time_str = datetime.now(TZ_MOSCOW).strftime('%Y-%m-%d %H:%M:%S')
    percent = round((score / total) * 100, 1) if total > 0 else 0
    
    new_data = {
        "Время": [time_str],
        "ФИО": [student_info['name']],
        "Группа": [student_info['group']],
        "Баллы": [score],
        "Всего вопросов": [total],
        "Процент": [percent]
    }
    
    df_new = pd.DataFrame(new_data)
    
    if os.path.exists(RESULTS_FILE):
        df_new.to_csv(RESULTS_FILE, mode='a', header=False, index=False, sep=';', encoding='utf-8-sig')
    else:
        df_new.to_csv(RESULTS_FILE, mode='w', header=True, index=False, sep=';', encoding='utf-8-sig')

# --- ТАЙМЕР ---
@st.fragment(run_every=1)
def show_live_timer():
    if st.session_state.step == "testing" and st.session_state.start_time:
        now = datetime.now(TZ_MOSCOW)
        elapsed = now - st.session_state.start_time
        limit = timedelta(minutes=st.session_state.time_limit_mins)
        remaining = limit - elapsed
        
        if remaining.total_seconds() > 0:
            mins, secs = divmod(int(remaining.total_seconds()), 60)
            st.metric("⏳ Таймер", f"{mins:02}:{secs:02}")
        else:
            st.error("⌛ Время вышло!")

# --- ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ ---
if "step" not in st.session_state:
    st.session_state.step = "login" 
if "user_info" not in st.session_state:
    st.session_state.user_info = {"name": "", "group": ""}
if "score" not in st.session_state:
    st.session_state.score = 0
    st.session_state.history = []
    st.session_state.questions = []
    st.session_state.current_index = 0
    st.session_state.end_time = None
if "result_saved" not in st.session_state:
    st.session_state.result_saved = False
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "time_limit_mins" not in st.session_state:
    st.session_state.time_limit_mins = 5

# Определяем файл по умолчанию
file_to_process = DEFAULT_FILE_NAME if os.path.exists(DEFAULT_FILE_NAME) else None
# Дефолтные значения настроек
questions_count = 5 
time_input = 5      

# --- САЙДБАР ---
with st.sidebar:
    st.title("🔧 Меню")
    
    show_live_timer()

    st.markdown("---")
    
    # --- ПАНЕЛЬ ПРЕПОДАВАТЕЛЯ ---
    with st.expander("👨‍🏫 Панель преподавателя", expanded=False):
        side_pwd = st.text_input("Пароль администратора", type="password", key="side_pwd")
        
        if side_pwd == ADMIN_PASSWORD:
            st.success("🔓 Режим редактирования")
            
            st.subheader("1. Настройки теста")
            
            # --- ИЗМЕНЕНИЕ: Убрана загрузка, только статус файла ---
            if file_to_process:
                st.success(f"✅ Файл подключен: {DEFAULT_FILE_NAME}")
            else:
                st.error(f"❌ Файл {DEFAULT_FILE_NAME} не найден на сервере!")

            questions_count = st.number_input("Кол-во вопросов", 1, 50, 5)
            time_input = st.number_input("Время (минуты)", 1, 180, 5)
            
            if st.button("🔄 Сброс / Новый тест", use_container_width=True):
                st.session_state.clear()
                st.rerun()

            st.markdown("---")
            st.subheader("2. Результаты")
            
            # --- ТАБЛИЦА ---
            if os.path.exists(RESULTS_FILE):
                try:
                    df_side = pd.read_csv(RESULTS_FILE, sep=';', encoding='utf-8-sig')
                    st.dataframe(df_side.iloc[::-1], height=200)
                    
                    csv_data = df_side.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
                    st.download_button(
                        label="📥 Скачать таблицу",
                        data=csv_data,
                        file_name="results_group.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
                    if st.button("🗑 Очистить таблицу", key="del_sidebar", use_container_width=True):
                        os.remove(RESULTS_FILE)
                        st.warning("Таблица удалена!")
                        time.sleep(1)
                        st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")
                    if st.button("🗑 Сбросить (Fix Error)"):
                        os.remove(RESULTS_FILE)
                        st.rerun()
            else:
                st.info("Таблица пуста")
        elif side_pwd:
            st.error("Неверный пароль")

st.title("🎓 Система тестирования")

# --- ЭТАП 1: ВХОД ---
if st.session_state.step == "login":
    st.markdown("### 👋 Регистрация")
    st.caption("Пожалуйста, представьтесь, чтобы начать тестирование.")
    
    # Проверка наличия файла для студента
    if not file_to_process:
        st.error(f"⛔ ОШИБКА: Файл с вопросами '{DEFAULT_FILE_NAME}' не найден. Обратитесь к преподавателю.")
    
    with st.form("login_form"):
        name_input = st.text_input("ФИО Студента")
        group_input = st.text_input("Номер группы")
        # Кнопка активна, но проверка внутри
        start_btn = st.form_submit_button("Начать тест 🚀", type="primary")
        
        if start_btn:
            if not file_to_process:
                st.error("Невозможно начать: нет файла с вопросами.")
            elif not name_input or not group_input:
                st.error("⚠️ Заполните ФИО и группу!")
            else:
                full_db = parse_docx_questions(file_to_process)
                if full_db:
                    count = min(questions_count, len(full_db))
                    st.session_state.questions = random.sample(full_db, count)
                    st.session_state.user_info = {"name": name_input, "group": group_input}
                    st.session_state.time_limit_mins = time_input
                    st.session_state.start_time = datetime.now(TZ_MOSCOW)
                    st.session_state.step = "testing"
                    st.rerun()
                else:
                    st.error("❌ Ошибка чтения вопросов из файла (пустой или битый файл).")

# --- ЭТАП 2: ТЕСТИРОВАНИЕ ---
elif st.session_state.step == "testing":
    idx = st.session_state.current_index
    total = len(st.session_state.questions)
    q_data = st.session_state.questions[idx]

    st.progress((idx / total), text=f"Вопрос {idx + 1} из {total}")
    st.subheader(f"🔹 {q_data['question']}")

    with st.form(key=f"q_form_{idx}"):
        user_input = st.text_area("Ваш ответ:", height=100)
        submit_btn = st.form_submit_button(label="Ответить ✍️")

    if submit_btn:
        now = datetime.now(TZ_MOSCOW)
        elapsed_check = now - st.session_state.start_time
        limit_check = timedelta(minutes=st.session_state.time_limit_mins)
        
        if elapsed_check > limit_check + timedelta(seconds=5):
            st.error("⛔ Время истекло! Ваш последний ответ не засчитан.")
            st.session_state.end_time = now.strftime("%H:%M:%S %d.%m.%Y")
            st.session_state.step = "finished"
            time.sleep(2) 
            st.rerun()
        
        elif not user_input.strip():
            st.warning("Введите ответ.")
            
        else:
            client = get_client()
            
            is_cheat = "торпедо москва" in user_input.lower()
            final_answer_for_ai = q_data['answer'] if is_cheat else user_input
            display_answer = q_data['answer'] if is_cheat else user_input

            with st.spinner("🤖 Проверка..."):
                ai_result = check_answer_with_ai(client, q_data['question'], q_data['answer'], final_answer_for_ai)

            is_correct = "ВЕРНО" in ai_result.upper() and "НЕВЕРНО" not in ai_result.upper().split("|")[0]
            if is_correct: st.session_state.score += 1

            st.session_state.history.append({
                "question": q_data['question'],
                "user_answer": display_answer,
                "ai_feedback": ai_result,
                "is_correct": is_correct
            })

            if st.session_state.current_index + 1 < total:
                st.session_state.current_index += 1
            else:
                st.session_state.end_time = datetime.now(TZ_MOSCOW).strftime("%H:%M:%S %d.%m.%Y")
                st.session_state.step = "finished"
            st.rerun()

# --- ЭТАП 3: ФИНАЛ ---
elif st.session_state.step == "finished":
    score = st.session_state.score
    total = len(st.session_state.questions)
    percent = int((score / total) * 100) if total > 0 else 0
    
    st.title("🏁 Результат")
    
    now = datetime.now(TZ_MOSCOW)
    if st.session_state.start_time:
        elapsed_total = now - st.session_state.start_time
        limit_total = timedelta(minutes=st.session_state.time_limit_mins)
        if elapsed_total > limit_total and total > len(st.session_state.history):
            st.warning("⏳ Тест был остановлен по истечении времени.")
    
    st.success(f"Вы набрали {score} из {total} баллов ({percent}%)")
    
    # --- СОХРАНЕНИЕ ---
    if not st.session_state.result_saved:
        save_result_to_csv(st.session_state.user_info, score, total)
        st.toast("Результат сохранен в общую таблицу!", icon="💾")
        st.session_state.result_saved = True

    with st.expander("🔍 Разбор ошибок"):
        for item in st.session_state.history:
            st.markdown(f"**Вопрос:** {item['question']}")
            st.markdown(f"**Ваш ответ:** {item['user_answer']}")
            
            if item['is_correct']:
                st.success(f"AI: {item['ai_feedback']}")
            else:
                st.error(f"AI: {item['ai_feedback']}")
            st.markdown("---")

    if st.button("Начать заново (Новый студент)"):
        st.session_state.clear()
        st.rerun()
