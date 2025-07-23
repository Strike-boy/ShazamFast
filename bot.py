import logging
import asyncio 
import sqlite3
import os
import aiohttp
import requests
import base64
import hmac
import hashlib
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils import executor
from aiogram.dispatcher.filters import CommandStart
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from pydub import AudioSegment
from datetime import datetime

API_TOKEN = '7936182138:AAHT25gYJuh2zU8-tk6yUVJOj9a5vmQeohk'
ACR_HOST = "identify-ap-southeast-1.acrcloud.com"
ACR_ACCESS_KEY = "e48f0d7b2af6ccad4015b26d57d75903"
ACR_SECRET_KEY = "WTWOUirBwcIPMJY6vOHEXVKilaMviC8doHQKGgaV"
VK_TOKEN = "vk1.a.ZumqOfV5IBzYqoI_h08ZsjtAnxNrG2XZmG4cpEpn92Gv-8-hrx0Pe32UOwtGW1mo3t_f4P7iofdUiyjjMvsgxnzUWQjmu5pfxfUE4AK9_mQZKUknERO-PYiGirPYxhDI9R8NA0nnCoMu_HVk6tnCmSq8qevqHsoy0LK5NzgKEVq1_Xo2zgqv_CkYfz4-goL8_vo62DcTQ2uyO6RP6oHCgA"

ADMIN_ID = 1001788720  # замени при необходимости
broadcast_mode = False

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Создание таблиц
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'ru',
            downloads INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            url TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Локализация
texts = {
    'start': {
        'ru': "👋 Привет! Отправь название песни, голос, аудио или видео — я найду музыку!",
        'en': "👋 Hi! Send a song name, voice, audio or video – I’ll find the music!",
        'uz': "👋 Salom! Menga qo‘shiq nomi, ovoz, audio yoki videoni yubor – men musiqani topaman!"
    },
    'help': {
        'ru': "/start - начать\n/languages - язык\n/stats - статистика\n/about - о боте",
        'en': "/start - start\n/languages - language\n/stats - stats\n/about - about bot",
        'uz': "/start - boshlash\n/languages - tilni o‘zgartirish\n/stats - statistika\n/about - bot haqida"
    },
    'about': {
        'ru': "🎧 Я бот ShazamFast. Узнаю музыку по названию, голосу, аудио и видео.",
        'en': "🎧 I’m ShazamFast bot. I recognize music by name, voice, audio and video.",
        'uz': "🎧 Men ShazamFast botman. Musiqani nomi, ovoz, audio va video orqali aniqlayman."
    },
    'choose_lang': {
        'ru': "🌐 Выберите язык:",
        'en': "🌐 Choose your language:",
        'uz': "🌐 Tilni tanlang:"
    },
    'stats': {
        'ru': "📊 Всего распознано: ",
        'en': "📊 Total recognized: ",
        'uz': "📊 Jami aniqlangan: "
    },
    'downloading': {
        'ru': "🔍 Ищу музыку, подожди...",
        'en': "🔍 Searching for music, please wait...",
        'uz': "🔍 Musiqani qidirmoqdaman, iltimos kuting..."
    },
    'error': {
        'ru': "⚠️ Ошибка: ",
        'en': "⚠️ Error: ",
        'uz': "⚠️ Xatolik: "
    }
}

# Клавиатура языков
def lang_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🇷🇺 Русский"), KeyboardButton("🇺🇸 English"), KeyboardButton("🇺🇿 O'zbek"))
    return kb

# Получить язык пользователя
def get_user_language(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "ru"

# Установить язык пользователя
def set_user_language(user_id, lang):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()
    conn.close()

# Добавить пользователя в базу
def register_user(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

# Проверка на бан
def is_banned(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1

# Увеличить статистику
def increment_downloads(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET downloads = downloads + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Добавить в историю
def add_to_history(user_id, url):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO history (user_id, url, timestamp) VALUES (?, ?, ?)", 
                   (user_id, url, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def recognize_acrcloud(file_path):
    http_method = "POST"
    http_uri = "/v1/identify"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(datetime.utcnow().timestamp()))

    string_to_sign = "\n".join([http_method, http_uri, ACR_ACCESS_KEY, data_type, signature_version, timestamp])
    sign = base64.b64encode(
    hmac.new(ACR_SECRET_KEY.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()
).decode('ascii')

    files = {'sample': open(file_path, 'rb')}
    data = {
        'access_key': ACR_ACCESS_KEY,
        'data_type': data_type,
        'signature_version': signature_version,
        'signature': sign,
        'timestamp': timestamp
    }

    response = requests.post(f"http://{ACR_HOST}/v1/identify", files=files, data=data)
    return response.json()

async def extract_audio_from_video(file_path, output_path):
    try:
        audio = AudioSegment.from_file(file_path)
        audio.export(output_path, format="mp3")
        return True
    except Exception as e:
        print("Ошибка при извлечении аудио:", e)
        return False

def search_vk_music(query):
    url = "https://api.vk.com/method/audio.search"
    params = {
        "q": query,
        "access_token": VK_TOKEN,
        "v": "5.131",
        "count": 1
    }
    try:
        response = requests.get(url, params=params).json()
        item = response['response']['items'][0]
        title = item.get('title')
        artist = item.get('artist')
        url = item.get('url')
        return {
            "title": title,
            "artist": artist,
            "url": url
        }
    except Exception as e:
        print("Ошибка VK:", e)
        return None

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id)
    lang = get_user_language(user_id)
    await message.answer(texts['start'][lang])

# Команда /languages
@dp.message_handler(commands=['languages'])
async def cmd_languages(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id)
    await message.answer(texts['choose_lang'][lang], reply_markup=lang_keyboard())

# Команда /help
@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id)
    await message.answer(texts['help'][lang])

# Команда /about
@dp.message_handler(commands=['about'])
async def cmd_about(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id)
    await message.answer(texts['about'][lang])

# Команда /stats
@dp.message_handler(commands=['stats'])
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_language(user_id)
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT downloads FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    count = result[0] if result else 0
    await message.answer(f"{texts['stats'][lang]} {count}")

@dp.message_handler(lambda m: m.text in ["🇷🇺 Русский", "🇺🇸 English", "🇺🇿 O‘zbek"])
async def change_language(message: types.Message):
    lang_map = {
        "🇷🇺 Русский": "ru",
        "🇺🇸 English": "en",
        "🇺🇿 O‘zbek": "uz"
    }
    lang = lang_map[message.text]
    set_user_language(message.from_user.id, lang)
    await message.answer("✅ Language updated!", reply_markup=types.ReplyKeyboardRemove())

def lang_keyboard():
    buttons = [
        [KeyboardButton("🇷🇺 Русский"), KeyboardButton("🇺🇸 English")],
        [KeyboardButton("🇺🇿 O‘zbek")]
    ]
    return ReplyKeyboardMarkup(resize_keyboard=True).add(*[btn for row in buttons for btn in row])

@dp.message_handler(content_types=['audio', 'voice', 'video'])
async def handle_media(message: types.Message):
    await message.answer("🎵 Распознаю музыку, подожди...")

    file_path = None

    # Скачиваем файл
    if message.video:
        file_path = "temp.mp4"
        await message.video.download(destination_file=file_path)
    elif message.audio:
        file_path = "temp.mp3"
        await message.audio.download(destination_file=file_path)
    elif message.voice:
        file_path = "temp.ogg"
        await message.voice.download(destination_file=file_path)
    else:
        await message.answer("❌ Невозможно обработать файл.")
        return

    try:
        result = recognize_acrcloud(file_path)

        if 'metadata' in result:
            music = result['metadata']['music'][0]
            title = music.get('title', 'Неизвестно')
            artist = music.get('artists', [{}])[0].get('name', 'Неизвестен')
            spotify = music.get('external_metadata', {}).get('spotify', {}).get('track', {}).get('external_urls', {}).get('spotify', 'Нет ссылки')

            reply = f"🎶 <b>{title}</b>\n👤 {artist}"
            if spotify != 'Нет ссылки':
                reply += f"\n🔗 <a href='{spotify}'>Spotify</a>"

            await message.answer(reply, parse_mode='HTML')

        else:
            await message.answer("❗️ Музыка не найдена. Вырезаю аудио из видео...")

            if message.video:
                video_path = "user_video.mp4"
                audio_path = "music.mp3"
                await message.video.download(video_path)

                success = await extract_audio_from_video(video_path, audio_path)
                if success:
                    with open(audio_path, 'rb') as audio:
                        await message.answer_audio(audio)
                    os.remove(audio_path)

                os.remove(video_path)
            else:
                await message.answer("⚠️ Аудио можно извлечь только из видео.")
                
    except Exception as e:
        await message.answer(f"❌ Ошибка при распознавании: {e}")

    # Удаляем временный файл
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
        
@dp.message_handler(lambda message: message.text and len(message.text) > 3)
async def handle_vk_search(message: types.Message):
    query = message.text.strip()
    await message.answer("🔍 Ищу песню, подожди...")

    result = search_vk_music(query)
    if result and result["url"]:
        caption = f"🎵 <b>{result['title']}</b>\n👤 {result['artist']}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(result["url"]) as resp:
                    if resp.status == 200:
                        audio_bytes = await resp.read()
                        audio = types.InputFile(path_or_bytesio=audio_bytes, filename=f"{result['title']}.mp3")
                        await message.answer_audio(audio, caption=caption, parse_mode="HTML")
                        increment_downloads(message.from_user.id)
                        add_to_history(message.from_user.id, query)
                    else:
                        await message.answer("⚠️ Не удалось скачать аудио с сервера.")
        except Exception as e:
            await message.answer(f"❌ Ошибка при скачивании: {e}")
    else:
        await message.answer("❗️ Музыка не найдена.")

app = Flask(__name__)

@app.route('/')
def home():
    return "ShazamFast бот работает! 🚀"

def start_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)

if __name__ == "__main__":
    t = Thread(target=start_bot)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
