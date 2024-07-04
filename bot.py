from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
import paramiko
import psycopg2
from psycopg2 import sql
import os
from threading import Thread

DATABASE_URI = os.getenv('DATABASE_URI')
TOKEN = os.getenv('TOKEN')

def init_db():
    conn = psycopg2.connect(DATABASE_URI)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS servers (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        ip VARCHAR(255) NOT NULL,
        port INT NOT NULL,
        username VARCHAR(255) NOT NULL,
        password VARCHAR(255) NOT NULL
    );
    """)
    conn.commit()
    cursor.close()
    conn.close()

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome to the Server Control Bot! Use /addserver to add a new server.")

def add_server(update: Update, context: CallbackContext):
    update.message.reply_text("Please send server details in the following format:\n<ip> <port> <username> <password>")

def save_server(update: Update, context: CallbackContext):
    user_data = update.message.text.split()
    if len(user_data) != 4:
        update.message.reply_text("Invalid format. Please use the following format:\n<ip> <port> <username> <password>")
        return
    
    ip, port, username, password = user_data
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, port=int(port), username=username, password=password)
        ssh.close()
    except Exception as e:
        update.message.reply_text(f"Connection failed: {str(e)}")
        return

    conn = psycopg2.connect(DATABASE_URI)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO servers (user_id, ip, port, username, password) VALUES (%s, %s, %s, %s, %s)",
                   (update.message.from_user.id, ip, port, username, password))
    conn.commit()
    cursor.close()
    conn.close()

    update.message.reply_text("Server added successfully!")

def server_stats(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    conn = psycopg2.connect(DATABASE_URI)
    cursor = conn.cursor()
    cursor.execute("SELECT ip, port, username, password FROM servers WHERE user_id = %s", (user_id,))
    servers = cursor.fetchall()
    cursor.close()
    conn.close()

    if not servers:
        update.message.reply_text("No servers found. Please add a server using /addserver.")
        return

    keyboard = []
    for idx, server in enumerate(servers):
        keyboard.append([InlineKeyboardButton(f"Server {idx+1}", callback_data=f"stats_{idx}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Choose a server to get stats:", reply_markup=reply_markup)

def fetch_stats(server_idx, user_id, query):
    conn = psycopg2.connect(DATABASE_URI)
    cursor = conn.cursor()
    cursor.execute("SELECT ip, port, username, password FROM servers WHERE user_id = %s", (user_id,))
    servers = cursor.fetchall()
    cursor.close()
    conn.close()

    if server_idx < 0 or server_idx >= len(servers):
        query.edit_message_text("Invalid server selected.")
        return

    ip, port, username, password = servers[server_idx]
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, port=int(port), username=username, password=password)
        
        stdin, stdout, stderr = ssh.exec_command("top -b -n1 | head -15")
        output = stdout.read().decode()
        
        query.edit_message_text(f"Server Stats:\n{output}")
        ssh.close()
    except Exception as e:
        query.edit_message_text(f"Failed to retrieve stats: {str(e)}")

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    data = query.data.split('_')
    if data[0] == 'stats':
        server_idx = int(data[1])
        user_id = query.from_user.id

        thread = Thread(target=fetch_stats, args=(server_idx, user_id, query))
        thread.start()

def main():
    init_db()
    updater = Updater(TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("addserver", add_server))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, save_server))
    dp.add_handler(CommandHandler("stats", server_stats))
    dp.add_handler(CallbackQueryHandler(button))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
