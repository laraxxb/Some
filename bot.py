from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
import paramiko
import psycopg2
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
    keyboard = [
        [InlineKeyboardButton("Add Server", callback_data='add_server')],
        [InlineKeyboardButton("List Servers", callback_data='list_servers')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Welcome to the Server Control Bot! Please choose an option:", reply_markup=reply_markup)

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data
    if data == 'add_server':
        context.user_data['action'] = 'add_server'
        query.edit_message_text("Please send server details in the following format:\n<ip> <port> <username> <password>")
    elif data == 'list_servers':
        list_servers(query, context)
    elif data.startswith('server_'):
        server_id = int(data.split('_')[1])
        control_server(query, context, server_id)
    elif data.startswith('cmd_'):
        server_id = int(data.split('_')[1])
        context.user_data['server_id'] = server_id
        context.user_data['action'] = 'run_command'
        query.edit_message_text("Please send the command to run on the server:")
    elif data.startswith('stats_'):
        server_id = int(data.split('_')[1])
        fetch_stats_thread = Thread(target=fetch_stats, args=(server_id, query))
        fetch_stats_thread.start()
    elif data == 'stop_command':
        if 'ssh_client' in context.user_data:
            context.user_data['ssh_client'].close()
            del context.user_data['ssh_client']
        if 'shell' in context.user_data:
            context.user_data['shell'].close()
            del context.user_data['shell']
        context.user_data['action'] = None
        query.edit_message_text("Stopped listening for commands.")

def list_servers(query, context):
    user_id = query.from_user.id
    conn = psycopg2.connect(DATABASE_URI)
    cursor = conn.cursor()
    cursor.execute("SELECT id, ip FROM servers WHERE user_id = %s", (user_id,))
    servers = cursor.fetchall()
    cursor.close()
    conn.close()

    if not servers:
        query.edit_message_text("No servers found. Please add a server using the 'Add Server' option.")
        return

    keyboard = []
    for server in servers:
        keyboard.append([InlineKeyboardButton(f"{server[1]}", callback_data=f"server_{server[0]}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Choose a server to control:", reply_markup=reply_markup)

def control_server(query, context, server_id):
    keyboard = [
        [InlineKeyboardButton("Run Command", callback_data=f'cmd_{server_id}')],
        [InlineKeyboardButton("Get Stats", callback_data=f'stats_{server_id}')],
        [InlineKeyboardButton("Stop Command Listening", callback_data='stop_command')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Choose an action:", reply_markup=reply_markup)

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

def fetch_stats(server_id, query):
    conn = psycopg2.connect(DATABASE_URI)
    cursor = conn.cursor()
    cursor.execute("SELECT ip, port, username, password FROM servers WHERE id = %s", (server_id,))
    server = cursor.fetchone()
    cursor.close()
    conn.close()

    if not server:
        query.edit_message_text("Server not found.")
        return

    ip, port, username, password = server
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

def run_command(update: Update, context: CallbackContext):
    command = update.message.text
    server_id = context.user_data.get('server_id')
    if not server_id or not command:
        update.message.reply_text("Invalid command or server. Please try again.")
        return

    if 'ssh_client' not in context.user_data:
        thread = Thread(target=connect_and_execute, args=(server_id, command, update, context))
        thread.start()
    else:
        thread = Thread(target=execute_command, args=(context.user_data['shell'], command, update))
        thread.start()

def connect_and_execute(server_id, command, update, context):
    conn = psycopg2.connect(DATABASE_URI)
    cursor = conn.cursor()
    cursor.execute("SELECT ip, port, username, password FROM servers WHERE id = %s", (server_id,))
    server = cursor.fetchone()
    cursor.close()
    conn.close()

    if not server:
        update.message.reply_text("Server not found.")
        return

    ip, port, username, password = server
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, port=int(port), username=username, password=password)
        context.user_data['ssh_client'] = ssh

        shell = ssh.invoke_shell()
        context.user_data['shell'] = shell
        execute_command(shell, command, update)
    except Exception as e:
        update.message.reply_text(f"Failed to run command: {str(e)}")

def execute_command(shell, command, update):
    try:
        shell.send(command + '\n')
        output = shell.recv(65535).decode()

        keyboard = [
            [InlineKeyboardButton("Stop Command Listening", callback_data='stop_command')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        update.message.reply_text(f"Command Output:\n{output}", reply_markup=reply_markup)
    except Exception as e:
        update.message.reply_text(f"Failed to run command: {str(e)}")

def message_handler(update: Update, context: CallbackContext):
    action = context.user_data.get('action')
    if action == 'add_server':
        save_server(update, context)
    elif action == 'run_command':
        run_command(update, context)

def main():
    init_db()
    updater = Updater(TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
