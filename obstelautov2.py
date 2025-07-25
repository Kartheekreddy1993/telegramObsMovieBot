import os
import json
import time
import logging
import threading
import subprocess
from datetime import datetime, timedelta
from functools import wraps

import obsws_python as obs
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

#In this version added username  logging supported .no change in all previous features
# === CONFIG ===
with open("config.json", "r") as f:
    config = json.load(f)

BOT_TOKEN = config["BOT_TOKEN"]
VIDEO_FOLDERS = config["VIDEO_FOLDER"]
NOTEPAD_FILE = config["NOTEPAD_FILE"]
FILES_PER_PAGE = 75
RATE_LIMIT_SECONDS = config["TIME_LIMIT"]
OBS_PORT = config["OBS_PORT"]
SCENE_PATH = config["SCENE_PATH"]
ENDTIME_FILE = config.get("ENDTIME_FILE", "endtime.txt")
MOVIE_PATH = config.get("MOVIE_PATH", "moviename.txt")

USER_RATE_LIMITS = {}
obs_connected = False
current_scene = "unknown"
obs_client = None

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot_actions.log"), logging.StreamHandler()]
)

# === OBS MONITOR THREAD ===
def get_video_duration(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        return float(result.stdout.strip())
    except Exception as e:
        print(f"Error getting duration: {e}")
        return 0

def monitor_obs():
    global obs_connected, current_scene, obs_client
    while True:
        try:
            obs_client = obs.ReqClient(host='localhost', port=OBS_PORT, password='secret', timeout=3)
            obs_connected = True
            logging.info("OBS connected")

            while True:
                response = obs_client.get_current_program_scene()
                current_scene = response.scene_name.lower()
                with open(SCENE_PATH, 'w', encoding='utf-8') as f:
                    f.write(current_scene)
                
                if current_scene == "filler" and os.path.isfile(NOTEPAD_FILE) and os.stat(NOTEPAD_FILE).st_size > 0:
                    with open(NOTEPAD_FILE, 'r') as file:
                        play_list = [line.strip() for line in file if line.strip()]
                    
                    with open(MOVIE_PATH, 'w') as mf:
                        mf.write(os.path.splitext(os.path.basename(play_list[0]))[0])

                    inputname = "selectsource"
                    obs_client.set_current_program_scene("select")
                    inputsettings = {'playlist': [{'hidden': False, 'selected': False, 'value': path} for path in play_list]}
                    obs_client.set_input_settings(inputname, inputsettings, overlay=True)

                    total_seconds = sum(get_video_duration(path) for path in play_list)
                    end_time = datetime.now() + timedelta(seconds=total_seconds)
                    end_time_str = end_time.strftime("%I:%M:%S %p")
                    with open(ENDTIME_FILE, 'w') as ef:
                        ef.write(f"Next Slot At {end_time_str}\n")

                    with open(NOTEPAD_FILE, 'w') as file:
                        file.truncate(0)
                time.sleep(5)
        except Exception as e:
            obs_connected = False
            logging.warning("OBS disconnected. Retrying in 5 seconds...")
            time.sleep(5)

# === START OBS MONITOR THREAD ===
threading.Thread(target=monitor_obs, daemon=True).start()

# === UTILITY ===
def get_all_video_files():
    video_files = []
    for folder in VIDEO_FOLDERS:
        try:
            for f in os.listdir(folder):
                if f.endswith(('.mp4', '.mkv')):
                    video_files.append({
                        "name": f,
                        "path": os.path.join(folder, f),
                        "folder": folder
                    })
        except FileNotFoundError:
            continue
    return video_files

def require_obs_and_filler(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not obs_connected:
            await update.message.reply_text("⚠️ TV CHANNEL BOTకు కనెక్ట్ కాలేదు. దయచేసి కొద్దిసేపటికి మళ్లీ ప్రయత్నించండి.")
            return
        if current_scene != "filler":
            await update.message.reply_text("🚫ప్రస్తుతం ఛానెల్‌లో సినిమా ప్లే అవుతోంది. దయచేసి సినిమా పూర్తయిన తర్వాత ప్రయత్నించండి లేదా వేరే ఛానెల్‌ని ఉపయోగించండి.")
            return
        return await func(update, context)
    return wrapper

def rate_limit(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        now = time.time()
        last_time = USER_RATE_LIMITS.get(user_id, 0)
        if now - last_time < RATE_LIMIT_SECONDS:
            remaining = int(RATE_LIMIT_SECONDS - (now - last_time))
            await update.message.reply_text(f"⏳ Please wait {remaining//60}m {remaining%60}s.")
            return
        USER_RATE_LIMITS[user_id] = now
        return await func(update, context)
    return wrapper

# === TELEGRAM BOT ===
@rate_limit
@require_obs_and_filler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logging.info(f"/start by {user.username or user.full_name} ({user.id})")
    context.user_data.clear()
    context.user_data["folders"] = VIDEO_FOLDERS
    await send_folder_list(update, context)

async def send_folder_list(update_or_query, context):
    folders = context.user_data.get("folders", VIDEO_FOLDERS)
    keyboard = [[InlineKeyboardButton(os.path.basename(folder), callback_data=f"folder_{i}")] for i, folder in enumerate(folders)]
    markup = InlineKeyboardMarkup(keyboard)
    title = "📁 Select a folder to view videos"
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(title, reply_markup=markup)
    else:
        await update_or_query.edit_message_text(title, reply_markup=markup)

@rate_limit
@require_obs_and_filler
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/search keyword`", parse_mode='Markdown')
        return
    keyword = " ".join(context.args).lower()
    user = update.effective_user
    logging.info(f"/search '{keyword}' by {user.username or user.full_name} ({user.id})")
    files = get_all_video_files()
    filtered = [f for f in files if keyword in f["name"].lower()]
    if not filtered:
        await update.message.reply_text("🔍 No matches found.")
        return
    context.user_data["video_files"] = filtered
    context.user_data["search"] = keyword
    context.user_data["sort"] = "az"
    context.user_data["page"] = 0
    await send_file_page(update, context, 0)

async def send_file_page(update_or_query, context, page):
    video_files = context.user_data.get("video_files", [])
    sort = context.user_data.get("sort", "az")
    if sort == "az":
        video_files.sort(key=lambda x: x["name"])
    elif sort == "za":
        video_files.sort(key=lambda x: x["name"], reverse=True)
    elif sort == "new":
        video_files.sort(key=lambda x: os.path.getmtime(x["path"]), reverse=True)
    elif sort == "old":
        video_files.sort(key=lambda x: os.path.getmtime(x["path"]))
    context.user_data["page"] = page

    total_pages = (len(video_files) - 1) // FILES_PER_PAGE + 1
    start_idx, end_idx = page * FILES_PER_PAGE, min((page+1)*FILES_PER_PAGE, len(video_files))
    keyboard = [
        [InlineKeyboardButton(
        f"{video_files[i]['name']} ({os.path.basename(video_files[i]['folder'])})",
            callback_data=f"file_{i}"
        )]
        for i in range(start_idx, end_idx)
    ]
    keyboard.append([
        InlineKeyboardButton("🔼 A-Z", callback_data="sort_az"),
        InlineKeyboardButton("🔽 Z-A", callback_data="sort_za"),
        InlineKeyboardButton("🆕 New", callback_data="sort_new"),
        InlineKeyboardButton("📁 Old", callback_data="sort_old")
    ])
    keyboard.append([
        InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{max(0, page-1)}"),
        InlineKeyboardButton("➡️ Next", callback_data=f"page_{min(total_pages-1, page+1)}")
    ])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_folders")])
    title = f"🎬 Select video (Page {page+1}/{total_pages})"
    markup = InlineKeyboardMarkup(keyboard)

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(title, reply_markup=markup)
    else:
        await update_or_query.edit_message_text(title, reply_markup=markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data.startswith("folder_"):
        idx = int(data.split("_")[1])
        folder = VIDEO_FOLDERS[idx]
        files = [
            {"name": f, "path": os.path.join(folder, f), "folder": folder}
            for f in os.listdir(folder) if f.endswith(('.mp4', '.mkv'))
        ]
        context.user_data["video_files"] = files
        context.user_data["sort"] = "az"
        await send_file_page(query, context, 0)

    elif data.startswith("file_"):
        idx = int(data.split("_")[1])
        file = context.user_data["video_files"][idx]
        with open(NOTEPAD_FILE, "a") as f:
            f.write(file["path"] + "\n")
        logging.info(f"Selected file '{file['name']}' from folder '{file['folder']}' by {user.username or user.full_name} ({user.id})")
        await query.edit_message_text(f"✅ Added to queue:\n{file['name']}")

    elif data == "back_folders":
        context.user_data.clear()
        await send_folder_list(query, context)

    elif data.startswith("sort_"):
        context.user_data["sort"] = data.split("_")[1]
        await send_file_page(query, context, context.user_data.get("page", 0))

    elif data.startswith("page_"):
        await send_file_page(query, context, int(data.split("_")[1]))

async def list_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logging.info(f"/list command by {user.username or user.full_name} ({user.id})")
    if os.path.exists(NOTEPAD_FILE):
        with open(NOTEPAD_FILE, "r") as f:
            text = f.read().strip()
        await update.message.reply_text(f"📄 Queue:\n```{text}```" if text else "📄 Queue is empty.", parse_mode='Markdown')
    else:
        await update.message.reply_text("📄 Queue file missing.")

# === MAIN ===
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("list", list_queue))
    app.add_handler(CallbackQueryHandler(button_callback))
    print("Bot running... Ctrl+C to stop")
    app.run_polling()
