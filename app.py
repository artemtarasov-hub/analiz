import streamlit as st
import os
from docx import Document
from openai import OpenAI
import random
from datetime import datetime, timedelta
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

# 2. Почта
EMAIL_SENDER = "tmfc6023@gmail.com"
EMAIL_PASSWORD = "uxsh ftph yvij fapk" 
EMAIL_RECEIVER = "torpedomoscow.ru@gmail.com"

# 3. Администрирование
ADMIN_PASSWORD = "admin"  
RESULTS_FILE = "exam_results.csv" 

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

def send_email_results(sender, password, receiver, student_info, score, total, history):
    subject = f"Результат теста: {student_info['name']} ({student_info['group']})"
    time_str = datetime.now(TZ_MOSCOW).strftime('%H:%M:%S %d.%m.%Y')
    
    body = f"""
    Студент: {student_info['name']}
    Группа: {student_info['group']}
    Результат: {score} из {total} ({(score/total)*100:.1f}%)
    Время завершения (МСК): {time_str}
    
    ---------------------------------------------------
    ДЕТАЛИЗАЦИЯ ОТВЕТОВ:
    ---------------------------------------------------
    """
    
    for i, item in enumerate(history, 1):
        status = "✅ ВЕРНО" if item['is_correct'] else "❌ ОШИБКА"
        body += f"\nВопрос {i}: {item['question']}\n"
        body += f"Ответ студента: {item['user_answer']}\n"
        body += f"Статус: {status}\n"
        body += f"Комментарий AI: {item['ai_feedback']}\n"
        body += "-" * 30 + "\n"

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return True, "Письмо успешно отправлено"
    except Exception as e:
        return False, str(e)

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
        # Если файл есть, дописываем
        df_new.to_csv(RESULTS_FILE, mode='a', header=False, index=False, sep=';', encoding='utf-8-sig')
    else:
        # Если нет, создаем новый
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
            st.metric("⏳ Таймер (Live)", f"{mins:02}:{secs:02}")
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
if "email_sent" not in st.session_state:
    st.session_state.email_sent = False
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "time_limit_mins" not in st.session_state:
    st.session_state.time_limit_mins = 5

# --- САЙДБАР ---
with st.sidebar:
    st.header("⚙️ Меню")

    default_file = "questions.docx"
    if os.path.exists(default_file):
        st.success(f"📄 Файл '{default_file}' подключен.")
        file_to_process = default_file
    else:
        file_to_process = st.file_uploader("Загрузите файл вопросов (.docx)", type=["docx"])

    questions_count = st.number_input("Количество вопросов", 1, 50, 5)
    time_input = st.number_input("Время на тест (минуты)", 1, 180, 5)
    
    if st.button("🔄 Сброс / Новый тест"):
        st.session_state.clear()
        st.rerun()
        
    st.markdown("---")
    
    # --- ИСПРАВЛЕННАЯ ПАНЕЛЬ В САЙДБАРЕ ---
    with st.expander("👨‍🏫 Панель преподавателя (Sidebar)"):
        side_pwd = st.text_input("Пароль", type="password", key="side_pwd")
        if side_pwd == ADMIN_PASSWORD:
            if os.path.exists(RESULTS_FILE):
                try:
                    # Пытаемся прочитать
                    df_side = pd.read_csv(RESULTS_FILE, sep=';', encoding='utf-8-sig')
                    st.dataframe(df_side, height=200)
                except Exception as e:
                    # Если ошибка, показываем её и КНОПКУ СБРОСА
                    st.error("Ошибка чтения (старый формат файла?)")
                    if st.button("🗑 Удалить/Сбросить таблицу", key="fix_sidebar_btn"):
                        os.remove(RESULTS_FILE)
                        st.rerun()
            else:
                st.info("Таблица пуста")

    # Таймер
    show_live_timer()

st.title("🎓 Система тестирования")

# --- ЭТАП 1: ВХОД ---
if st.session_state.step == "login":
    st.markdown("### 👋 Регистрация")
    with st.form("login_form"):
        name_input = st.text_input("ФИО Студента")
        group_input = st.text_input("Номер группы")
        start_btn = st.form_submit_button("Начать тест 🚀", type="primary")
        
        if start_btn:
            if not name_input or not group_input:
                st.error("⚠️ Заполните ФИО и группу!")
            elif not file_to_process:
                st.error("⚠️ Файл с вопросами не загружен.")
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
                    st.error("❌ Ошибка: не удалось найти вопросы в файле.")

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
    
    # --- ЛОГИКА СОХРАНЕНИЯ И ОТПРАВКИ ---
    if not st.session_state.email_sent:
        # 1. Сохраняем в CSV с разделителем ;
        save_result_to_csv(st.session_state.user_info, score, total)
        
        # 2. Отправляем на почту
        with st.spinner("📧 Отправка результатов преподавателю..."):
            success, msg = send_email_results(
                EMAIL_SENDER, 
                EMAIL_PASSWORD, 
                EMAIL_RECEIVER,
                st.session_state.user_info,
                score,
                total,
                st.session_state.history
            )
            if success:
                st.toast("Результаты отправлены и сохранены!", icon="💾")
                st.session_state.email_sent = True
            else:
                st.error(f"Ошибка отправки почты: {msg}")

    with st.expander("🔍 Разбор ошибок"):
        for item in st.session_state.history:
            st.markdown(f"**Вопрос:** {item['question']}")
            st.markdown(f"**Ваш ответ:** {item['user_answer']}")
            
            if item['is_correct']:
                st.success(f"AI: {item['ai_feedback']}")
            else:
                st.error(f"AI: {item['ai_feedback']}")
            st.markdown("---")
            
    st.markdown("---")
    
    # ==========================================
    # 📊 ПАНЕЛЬ АДМИНИСТРАТОРА (MAIN PAGE)
    # ==========================================
    st.subheader("👨‍🏫 Сводная таблица (для преподавателя)")
    with st.expander("Открыть таблицу (требуется пароль)"):
        main_pwd = st.text_input("Введите пароль администратора", type="password", key="main_pwd")
        
        if main_pwd == ADMIN_PASSWORD:
            st.success("Доступ разрешен")
            
            if os.path.exists(RESULTS_FILE):
                try:
                    # Читаем СВЕЖИЙ файл
                    df_main = pd.read_csv(RESULTS_FILE, sep=';', encoding='utf-8-sig')
                    
                    # Показываем последние результаты сверху
                    st.dataframe(df_main.iloc[::-1], use_container_width=True)
                    
                    # Кнопка скачивания
                    csv_data = df_main.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
                    st.download_button(
                        label="📥 Скачать Excel/CSV",
                        data=csv_data,
                        file_name="results_group.csv",
                        mime="text/csv",
                    )
                    
                    if st.button("🗑 Очистить всю таблицу", key="clean_main"):
                        os.remove(RESULTS_FILE)
                        st.warning("Таблица удалена. Перезагрузите страницу.")
                        time.sleep(1)
                        st.rerun()
                        
                except Exception as e:
                    st.error(f"Ошибка чтения файла: {e}")
                    # КНОПКА СБРОСА ДЛЯ ОСНОВНОЙ ПАНЕЛИ
                    if st.button("🗑 Сбросить таблицу (Fix Error)", key="fix_main_btn"):
                        os.remove(RESULTS_FILE)
                        st.rerun()
            else:
                st.info("Файл результатов пока пуст.")
        elif main_pwd:
            st.error("Неверный пароль")

    st.markdown("---")
    if st.button("Начать заново (Новый студент)"):
        st.session_state.clear()
        st.rerun()
