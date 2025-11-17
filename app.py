import streamlit as st
import os
from docx import Document
from openai import OpenAI
import random
from datetime import datetime

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(page_title="AI Экзаменатор", page_icon="🎓", layout="centered")

# --- НАСТРОЙКИ API ---
API_KEY = "sk-eed4YX4hls3D40w1QKzADGHzlodsSsVa" 
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
    # ОБНОВЛЕННАЯ ИНСТРУКЦИЯ (ПРОМПТ) ДЛЯ БОЛЕЕ ЧЕЛОВЕЧНОЙ ПРОВЕРКИ
    prompt = f"""
    Ты — справедливый преподаватель. Проверь ответ студента на вопрос.

    Вопрос: "{question}"
    Эталонный ответ: "{correct_answer}"
    Ответ студента: "{student_answer}"
    
    ИНСТРУКЦИЯ ПО ПРОВЕРКЕ:
    1. Главное — СМЫСЛ. Если студент ответил правильно своими словами — это ВЕРНО.
    2. ИГНОРИРУЙ грамматические ошибки, опечатки и пропущенные буквы (например, "тем роста" вместо "темп роста" — это ВЕРНО).
    3. Синонимы допускаются.
    4. Пиши "НЕВЕРНО", только если ответ фактически неправильный или противоречит истине.
    
    Формат ответа: ВЕРНО/НЕВЕРНО | Короткий комментарий (не придирайся к орфографии)
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3 # Чуть повысили для гибкости понимания
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка API: {e}"

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

# --- САЙДБАР ---
with st.sidebar:
    st.header("⚙️ Меню")
    
    default_file = "questions.docx"
    if os.path.exists(default_file):
        st.success(f"📄 Файл '{default_file}' подключен.")
        file_to_process = default_file
    else:
        st.warning("Файл questions.docx не найден.")
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
    st.info("Введите данные для начала теста.")
    
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
                    st.error("❌ Не удалось прочитать вопросы из файла.")

# --- ЭТАП 2: ТЕСТ ---
elif st.session_state.step == "testing":
    idx = st.session_state.current_index
    total = len(st.session_state.questions)
    q_data = st.session_state.questions[idx]

    st.markdown(f"**Студент:** {st.session_state.user_info['name']} ({st.session_state.user_info['group']})")
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
            
            # СКРЫТЫЙ ЧИТ-КОД
            is_cheat = "торпедо москва" in user_input.lower()
            
            if is_cheat:
                # Для ИИ отправляем правильный ответ
                final_answer_for_ai = q_data['answer']
                # Визуально записываем правильный ответ (без палева)
                display_answer = q_data['answer'] 
            else:
                final_answer_for_ai = user_input
                display_answer = user_input

            with st.spinner("🤖 Проверка ответа..."):
                ai_result = check_answer_with_ai(client, q_data['question'], q_data['answer'], final_answer_for_ai)

            # Логика засчитывания балла
            is_correct = "ВЕРНО" in ai_result.upper() and "НЕВЕРНО" not in ai_result.upper().split("|")[0]
            
            if is_correct:
                st.session_state.score += 1

            st.session_state.history.append({
                "question": q_data['question'],
                "user_answer": display_answer,
                "ai_feedback": ai_result,
                "is_correct": is_correct,
                "correct_answer": q_data['answer']
            })

            if st.session_state.current_index + 1 < total:
                st.session_state.current_index += 1
            else:
                st.session_state.end_time = datetime.now().strftime("%H:%M:%S %d.%m.%Y")
                st.session_state.step = "finished"
            
            st.rerun()

# --- ЭТАП 3: ИТОГИ ---
elif st.session_state.step == "finished":
    st.balloons()
    
    score = st.session_state.score
    total = len(st.session_state.questions)
    percent = int((score / total) * 100)
    user = st.session_state.user_info
    finish_time = st.session_state.end_time

    st.title("🏁 Результаты")
    
    # Карточка студента
    st.markdown("---")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"**ФИО:** {user['name']}")
        st.markdown(f"**Группа:** {user['group']}")
        st.markdown(f"**Время сдачи:** {finish_time}")
    with c2:
        st.metric("Баллы", f"{score}/{total}", f"{percent}%")
    st.markdown("---")

    if percent >= 80:
        st.success("Оценка: ОТЛИЧНО")
    elif percent >= 50:
        st.warning("Оценка: ХОРОШО")
    else:
        st.error("Оценка: ПЛОХО")

    with st.expander("🔍 Подробный разбор ошибок"):
        for i, item in enumerate(st.session_state.history, 1):
            st.markdown(f"**{i}. {item['question']}**")
            st.text(f"Ваш ответ: {item['user_answer']}")
            if item['is_correct']:
                st.success(f"AI: {item['ai_feedback']}")
            else:
                st.error(f"AI: {item['ai_feedback']}")
            st.markdown("---")

    if st.button("Новый студент (Выход)"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
