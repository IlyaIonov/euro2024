import os
import logging
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен бота из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set")

# Путь к базе данных
db_path = '/app/data/euro2024.db'

# Создаем директорию для базы данных, если она не существует
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Создаем и инициализируем базу данных SQLite
def init_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS standings (team TEXT PRIMARY KEY, points INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS votes (user_id INTEGER, match_id INTEGER, vote TEXT, username TEXT, first_name TEXT, last_name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS matches (match_id INTEGER PRIMARY KEY AUTOINCREMENT, team1 TEXT, team2 TEXT, match_date TEXT)''')

    # Проверка и добавление столбцов в таблицу users, если они не существуют
    cursor.execute("PRAGMA table_info(users)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'first_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
    if 'last_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT")

    # Проверка и добавление столбцов в таблицу votes, если они не существуют
    cursor.execute("PRAGMA table_info(votes)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'first_name' not in columns:
        cursor.execute("ALTER TABLE votes ADD COLUMN first_name TEXT")
    if 'last_name' not in columns:
        cursor.execute("ALTER TABLE votes ADD COLUMN last_name TEXT")

    conn.commit()
    conn.close()

try:
    init_db()
except sqlite3.OperationalError as e:
    logger.error(f"Ошибка инициализации базы данных: {e}")

# Этапы диалога
FIRST_NAME, LAST_NAME, USER_RESULTS = range(3)

# Функция для начала работы
def start(update: Update, context):
    logger.info(f"User {update.message.from_user.username} started the bot.")
    update.message.reply_text("Привет! Пожалуйста, введи свое имя:")
    return FIRST_NAME

def first_name(update: Update, context):
    context.user_data['first_name'] = update.message.text
    update.message.reply_text("Прекрасно! Теперь фамилию:")
    return LAST_NAME

def last_name(update: Update, context):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    first_name = context.user_data['first_name']
    last_name = update.message.text

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                   (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()

    keyboard = [
        [KeyboardButton('/vote'), KeyboardButton('/standings')],
        [KeyboardButton('/results'), KeyboardButton('/teams')],
        [KeyboardButton('/matches')]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text(
        f"Спасибо, {first_name} {last_name}! Теперь ты в игре!",
        reply_markup=reply_markup
    )
    return ConversationHandler.END


def vote(update: Update, context):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT match_id, team1, team2, match_date FROM matches")
    matches = cursor.fetchall()
    conn.close()

    if matches:
        current_date = datetime.now().date()  # Текущая дата без времени
        valid_matches = [
            (match_id, team1, team2) for match_id, team1, team2, match_date in matches
            if datetime.strptime(match_date, '%Y-%m-%d %H:%M:%S').date() == current_date
        ]

        if valid_matches:
            keyboard = [
                [InlineKeyboardButton(f"{team1} vs {team2}", callback_data=str(match_id))] for match_id, team1, team2 in valid_matches
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text('Выбери матч для голосования:', reply_markup=reply_markup)
        else:
            update.message.reply_text('Сегодня нет игр.')
    else:
        update.message.reply_text('Матчи не найдены.')

def button_vote(update: Update, context):
    query = update.callback_query
    query.answer()

    try:
        match_id = int(query.data)
        user_id = query.from_user.id

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Проверяем, голосовал ли пользователь уже за этот матч сегодня
        cursor.execute("SELECT COUNT(*) FROM votes WHERE user_id=? AND match_id=? AND vote_date=date('now')", (user_id, match_id))
        vote_count = cursor.fetchone()[0]

        if vote_count > 0:
            query.edit_message_text('Ты уже проголосовал за этот матч сегодня.')
        else:
            cursor.execute("SELECT team1, team2, match_date FROM matches WHERE match_id=?", (match_id,))
            match = cursor.fetchone()

            if match:
                team1, team2, match_date = match
                current_time = datetime.now()
                match_datetime = datetime.strptime(match_date, '%Y-%m-%d %H:%M:%S')

                if current_time >= (match_datetime - timedelta(days=5)) and match_datetime > current_time:
                    # Получаем информацию о пользователе из базы данных
                    cursor.execute("SELECT first_name, last_name FROM users WHERE user_id=?", (user_id,))
                    user_info = cursor.fetchone()
                    if user_info:
                        first_name, last_name = user_info
                    else:
                        first_name, last_name = "Неизвестный", "пользователь"

                    keyboard = [
                        [InlineKeyboardButton(team1, callback_data=f"{match_id}_{team1}")],
                        [InlineKeyboardButton(team2, callback_data=f"{match_id}_{team2}")],
                        [InlineKeyboardButton("Ничья", callback_data=f"{match_id}_draw")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    query.edit_message_text('Выбери результат матча:', reply_markup=reply_markup)
                else:
                    query.edit_message_text('Голосование для этого матча недоступно.')
            else:
                query.edit_message_text('Матч не найден.')

        conn.close()

    except ValueError:
        query.edit_message_text('Некорректный формат данных.')


def button_vote_result(update: Update, context):
    query = update.callback_query
    query.answer()

    data = query.data.split('_')
    match_id = int(data[0])
    vote = data[1]

    user_id = query.from_user.id
    username = query.from_user.username

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Проверяем, голосовал ли пользователь уже за этот матч сегодня
    cursor.execute("SELECT COUNT(*) FROM votes WHERE user_id=? AND match_id=? AND vote_date=date('now')", (user_id, match_id))
    vote_count = cursor.fetchone()[0]

    if vote_count > 0:
        query.edit_message_text('Ты уже проголосовал за этот матч сегодня.')
    else:
        cursor.execute("SELECT first_name, last_name FROM users WHERE user_id=?", (user_id,))
        user_info = cursor.fetchone()
        if user_info:
            first_name, last_name = user_info
        else:
            first_name, last_name = "Неизвестный", "пользователь"

        try:
            cursor.execute(
                "INSERT INTO votes (user_id, username, first_name, last_name, match_id, vote, vote_date) VALUES (?, ?, ?, ?, ?, ?, date('now'))",
                (user_id, username, first_name, last_name, match_id, vote))
            conn.commit()

            # Изменяем вывод текста результата голосования
            if vote == "draw":
                vote_result = "Ничья"
            else:
                vote_result = vote

            query.edit_message_text(text=f"Ты выбрал: {vote_result}")
        except sqlite3.OperationalError as e:
            logger.error(f"Ошибка записи в базу данных: {e}")

    conn.close()

def standings(update: Update, context):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM standings ORDER BY points DESC")
    standings = cursor.fetchall()
    conn.close()
    if standings:
        table = "Турнирная таблица:\n\n"
        for team, points in standings:
            table += f"{team}: {points} очков\n"
        update.message.reply_text(table)
    else:
        update.message.reply_text("Турнирная таблица пуста.")

# Функция для получения турнирной таблицы с группировкой по группам
def get_grouped_standings():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    grouped_standings = defaultdict(list)

    cursor.execute("SELECT team, points, group_name FROM standings ORDER BY group_name, points DESC")
    standings = cursor.fetchall()

    for team, points, group_name in standings:
        grouped_standings[group_name].append((team, points))

    conn.close()

    return grouped_standings

# Функция для отображения турнирной таблицы
def show_standings(update, context):
    grouped_standings = get_grouped_standings()

    standings_text = "Турнирная таблица:\n\n"

    for group_name, teams in grouped_standings.items():
        standings_text += f"Группа {group_name}\n"
        for idx, (team, points) in enumerate(teams, start=1):
            standings_text += f"{idx}. {team}: {points} очков\n"
        standings_text += "\n"

    update.message.reply_text(standings_text)


def results(update: Update, context):
    keyboard = [
        [InlineKeyboardButton("Общие результаты", callback_data="all_results")],
        [InlineKeyboardButton("Результаты по пользователю", callback_data="user_results")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Выберите опцию:', reply_markup=reply_markup)

def all_results(update: Update, context):
    query = update.callback_query
    query.answer()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.team1, m.team2, v.vote, v.first_name, v.last_name
        FROM votes v
        JOIN matches m ON v.match_id = m.match_id
    """)
    votes = cursor.fetchall()
    conn.close()
    if votes:
        results_text = "Результаты голосования:\n\n"
        for team1, team2, vote, first_name, last_name in votes:
            match = f"{team1} vs {team2}"
            vote_result = vote if vote != "draw" else "Ничья"
            user_name = f"{first_name} {last_name}" if first_name and last_name else "Неизвестный пользователь"
            results_text += f"Матч: {match}, Голос: {vote_result}, Пользователь: {user_name}\n"
        query.edit_message_text(results_text)
    else:
        query.edit_message_text("Результаты голосования отсутствуют.")

def user_results_start(update: Update, context):
    query = update.callback_query
    query.answer()
    query.edit_message_text("Нужно ввести имя и фамилию для просмотра голосов:")
    return USER_RESULTS


def user_results_display(update: Update, context):
    full_name = update.message.text.strip()
    if ' ' in full_name:
        first_name, last_name = full_name.split(' ', 1)
    else:
        first_name = full_name
        last_name = ""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.team1, m.team2, v.vote
        FROM votes v
        JOIN matches m ON v.match_id = m.match_id
        JOIN users u ON v.user_id = u.user_id
        WHERE u.first_name=? AND u.last_name=?
    """, (first_name, last_name))
    votes = cursor.fetchall()
    conn.close()

    if votes:
        results_text = f"Результаты голосования пользователя {first_name} {last_name}:\n\n"
        for team1, team2, vote in votes:
            match = f"{team1} vs {team2}"
            vote_result = vote if vote != "draw" else "Ничья"
            results_text += f"Матч: {match}, Голос: {vote_result}\n"
        update.message.reply_text(results_text)
    else:
        update.message.reply_text(f"Голосования пользователя {first_name} {last_name} не найдены.")

    return ConversationHandler.END

def teams(update: Update, context):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT team FROM standings")
    teams = cursor.fetchall()
    conn.close()
    if teams:
        teams_list = "Список команд:\n\n"
        for team in teams:
            teams_list += f"{team[0]}\n"
        update.message.reply_text(teams_list)
    else:
        update.message.reply_text("Список команд пуст.")

def matches(update: Update, context):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT team1, team2, match_date FROM matches")  # Изменен запрос
    matches = cursor.fetchall()
    conn.close()
    if matches:
        matches_list = "Список матчей:\n\n"
        for team1, team2, match_date in matches:
            match_datetime = datetime.strptime(match_date, '%Y-%m-%d %H:%M:%S')
            formatted_date = match_datetime.strftime('%d.%m.%Y %H:%M')
            matches_list += f"{team1} vs {team2} ({formatted_date})\n"
        update.message.reply_text(matches_list)
    else:
        update.message.reply_text("Список матчей пуст.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # ConversationHandler для ввода имени и фамилии
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            FIRST_NAME: [MessageHandler(Filters.text & ~Filters.command, first_name)],
            LAST_NAME: [MessageHandler(Filters.text & ~Filters.command, last_name)]
        },
        fallbacks=[]
    )

    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(CommandHandler("vote", vote))
    dispatcher.add_handler(CallbackQueryHandler(button_vote, pattern="^[0-9]+$"))
    dispatcher.add_handler(CallbackQueryHandler(button_vote_result, pattern="^[0-9]+_.+$"))
    dispatcher.add_handler(CommandHandler("standings", show_standings))
    dispatcher.add_handler(CommandHandler("results", results))
    dispatcher.add_handler(CommandHandler("teams", teams))
    dispatcher.add_handler(CommandHandler("matches", matches))
    dispatcher.add_handler(CallbackQueryHandler(all_results, pattern="all_results"))

    # ConversationHandler для ввода имени и фамилии пользователя и отображения результатов голосования
    user_results_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(user_results_start, pattern="user_results")],
        states={
            USER_RESULTS: [MessageHandler(Filters.text & ~Filters.command, user_results_display)]
        },
        fallbacks=[]
    )
    dispatcher.add_handler(user_results_handler)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()