import streamlit as st
import os
from docx import Document
from openai import OpenAI
import random
from datetime import datetime
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(page_title="AI Экзаменатор", page_icon="🎓", layout="centered")

# --- НАСТРОЙКИ API (Можно оставить здесь или вынести в secrets) ---
API_KEY = "sk-eed4YX4hls3D40w1QKzADGHzlodsSsVa"  # <--- ВАШ КЛЮЧ OPENAI
BASE_URL = "https://openai.api.proxyapi.ru/v1"
MODEL_NAME = "gpt-4o-mini"

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

def send_email_results(sender_email, sender_password, receiver_email, student_info, score, total, history):
    """Функция отправки письма преподавателю"""
    
    subject = f"Результат теста: {student_info['name']} ({student_info['group']})"
    
    # Формируем тело письма
    body = f"""
    Студент: {student_info['name']}
    Группа: {student_info['group']}
    Результат: {score} из {total} ({(score/total)*100:.1f}%)
    Время завершения: {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M:%S %d.%m.%Y')}
    
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
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Подключение к серверу Gmail (порт 465 для SSL)
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True, "Письмо успешно отправлено"
    except Exception as e:
        return False, str(e)

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

# --- САЙДБАР ---
with st.sidebar:
    st.header("⚙️ Меню и Настройки")
    
    # --- Настройки почты (только для преподавателя) ---
    st.subheader("📧 Настройки отправки")
    with st.expander("Настроить Email"):
        email_sender = st.text_input("Почта отправителя (Gmail)", placeholder="teacher@gmail.com")
        email_password = st.text_input("Пароль приложения", type="password", help="Создайте App Password в настройках Google Аккаунта")
        email_receiver = st.text_input("Почта получателя", placeholder="teacher@university.ru")
    
    st.markdown("---")
    
    default_file = "questions.docx"
    if os.path.exists(default_file):
        st.success(f"📄 Файл '{default_file}' подключен.")
        file_to_process = default_file
    else:
        file_to_process = st.file_uploader("Загрузите вопросы (.docx)", type=["docx"])

    questions_count = st.number_input("Количество вопросов", 1, 50, 5)
    
    if st.button("🔄 Перезагрузить тест"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

st.title("🎓 Система тестирования")

# --- ЭТАП 1: ВХОД ---
if st.session_state.step == "login":
    st.markdown("### 👋 Регистрация")
    with st.form("login_form"):
        name_input = st.text_input("ФИО Студента", placeholder="Иванов Иван Иванович")
        group_input = st.text_input("Номер группы", placeholder="А-101")
        start_btn = st.form_submit_button("Начать тест 🚀", type="primary")
        
        if start_btn:
            if not name_input or not group_input:
                st.error("⚠️ Заполните ФИО и номер группы!")
            elif not file_to_process:
                st.error("⚠️ Файл с вопросами не найден.")
            else:
                full_db = parse_docx_questions(file_to_process)
                if full_db:
                    count = min(questions_count, len(full_db))
                    st.session_state.questions = random.sample(full_db, count)
                    st.session_state.user_info = {"name": name_input, "group": group_input}
                    st.session_state.step = "testing"
                    st.rerun()
                else:
                    st.error("❌ Ошибка чтения файла.")

# --- ЭТАП 2: ТЕСТ ---
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
        if not user_input.strip():
            st.warning("Введите ответ.")
        else:
            client = get_client()
            # Чит-код
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
                moscow_tz = pytz.timezone('Europe/Moscow')
                st.session_state.end_time = datetime.now(moscow_tz).strftime("%H:%M:%S %d.%m.%Y")
                st.session_state.step = "finished"
            st.rerun()

# --- ЭТАП 3: ИТОГИ ---
elif st.session_state.step == "finished":
    score = st.session_state.score
    total = len(st.session_state.questions)
    percent = int((score / total) * 100)
    
    st.title("🏁 Результаты")
    st.success(f"Вы набрали {score} из {total} баллов ({percent}%)")
    
    # --- БЛОК ОТПРАВКИ ПИСЬМА ---
    if not st.session_state.email_sent:
        if email_sender and email_password and email_receiver:
            with st.spinner("📧 Отправка результатов преподавателю..."):
                success, msg = send_email_results(
                    email_sender, 
                    email_password, 
                    email_receiver,
                    st.session_state.user_info,
                    score,
                    total,
                    st.session_state.history
                )
                if success:
                    st.toast("✅ Результаты отправлены преподавателю!", icon="📩")
                    st.session_state.email_sent = True
                else:
                    st.error(f"Ошибка отправки письма: {msg}")
        else:
            st.warning("⚠️ Результаты не отправлены: не настроена почта в меню.")

    # Отображение подробностей для студента
    with st.expander("🔍 Посмотреть свои ошибки"):
        for item in st.session_state.history:
            st.write(f"**{item['question']}**")
            st.write(f"Ответ: {item['user_answer']}")
            st.info(item['ai_feedback']) if item['is_correct'] else st.error(item['ai_feedback'])
            st.write("---")

    if st.button("Новый студент"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

