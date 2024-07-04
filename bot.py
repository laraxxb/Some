import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, filters
import paramiko
import psycopg2
from urllib.parse import urlparse
import os
# إعدادات بوت تلغرام
TELEGRAM_TOKEN = os.getenv("TOKEN", None)

# إعدادات تسجيل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('شلونك! ابعث /addserver لإضافة سيرفر جديد.')

def add_server(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('رجاءً ابعث المعلومات بالشكل التالي:\nhost port username password')

def save_server(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    details = update.message.text.split()
    if len(details) != 4:
        update.message.reply_text('رجاءً اكتب المعلومات بالشكل الصحيح: host port username password')
        return
    
    host, port, username, password = details

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=int(port), username=username, password=password)
        ssh.close()
    except Exception as e:
        update.message.reply_text(f'خطأ في الاتصال بالسيرفر: {str(e)}')
        return

    try:
        # اتصال بقاعدة البيانات باستخدام URI
        db_uri = os.getenv("DATABASE_URL", None)
        conn = psycopg2.connect(db_uri)
        
        cur = conn.cursor()
        cur.execute("INSERT INTO servers (user_id, host, port, username, password) VALUES (%s, %s, %s, %s, %s)", 
                    (user_id, host, port, username, password))
        conn.commit()
        cur.close()
        conn.close()
        update.message.reply_text('تم إضافة السيرفر بنجاح.')
    except Exception as e:
        update.message.reply_text(f'خطأ في قاعدة البيانات: {str(e)}')

def run_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    command = ' '.join(context.args)
    if not command:
        update.message.reply_text('رجاءً اكتب الأمر اللي تريد تنفيذه.')
        return

    try:
        # اتصال بقاعدة البيانات باستخدام URI
        db_uri = os.getenv("DATABASE_URL", None)
        conn = psycopg2.connect(db_uri)
        
        cur = conn.cursor()
        cur.execute("SELECT host, port, username, password FROM servers WHERE user_id = %s", (user_id,))
        server = cur.fetchone()
        cur.close()
        conn.close()

        if server:
            host, port, username, password = server
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, port=int(port), username=username, password=password)
            
            stdin, stdout, stderr = ssh.exec_command(command)
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            
            ssh.close()
            
            if output:
                update.message.reply_text(f'Output:\n{output}')
            if error:
                update.message.reply_text(f'Error:\n{error}')
        else:
            update.message.reply_text('ماكو سيرفر مضاف لهذا المستخدم.')

    except Exception as e:
        update.message.reply_text(f'Error: {str(e)}')

def main() -> None:
    updater = Updater(TELEGRAM_TOKEN)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("addserver", add_server))
    dispatcher.add_handler(MessageHandler(filters.command, save_server))
    dispatcher.add_handler(CommandHandler("run", run_command))

    updater.start_polling()

    updater.idle()

if __name__ == '__main__':
    
    main()
