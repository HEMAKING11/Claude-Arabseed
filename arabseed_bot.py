#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import json
import re
import time
from urllib.parse import urlparse, unquote, urlunparse, quote

# Install required packages
def install_package(package):
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import requests
except ImportError:
    install_package("requests")
    import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    install_package("beautifulsoup4")
    from bs4 import BeautifulSoup

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    install_package("python-telegram-bot")
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ============= إعدادات البوت =============
BOT_TOKEN = "8283957939:AAEuYfu5_V4e5skwJvHDK-mal35xmQ8Lc-w"  # ضع توكن البوت هنا

# إعداد الـ logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Headers للطلبات
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ============= دوال مساعدة =============
def extract_base_url(url):
    parsed_url = urlparse(url)
    return f"{parsed_url.scheme}://{parsed_url.netloc}"

def extract_title_from_url(url):
    parsed_url = urlparse(url)
    path = unquote(parsed_url.path)
    path_parts = path.strip('/').split('-')
    title = ' '.join(path_parts).replace('.html', '').title()
    if title.startswith("مسلسل"):
        words = title.split()
        new_title = []
        for word in words:
            new_title.append(word)
            if any(char.isdigit() for char in word):
                break
        title = ' '.join(new_title)
    return title

def follow_redirect(url, session=None, headers=None, timeout=10):
    if session is None:
        session = requests.Session()
    if headers is None:
        headers = DEFAULT_HEADERS

    try:
        r = session.get(url, headers=headers, allow_redirects=False, timeout=timeout)
        if 'location' in r.headers:
            return r.headers['location']
        r2 = session.get(url, headers=headers, allow_redirects=True, timeout=timeout)
        return r2.url
    except Exception as e:
        logger.error(f"Error following redirect: {e}")
        return None

def get_download_info(server_href, referer):
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if referer:
        session.headers.update({"Referer": referer})

    try:
        redirected = follow_redirect(server_href, session=session)
        if not redirected:
            return None

        r_link = None
        if '?r=' in redirected:
            r_link = redirected
        else:
            tmp = session.get(redirected, timeout=12)
            m = re.search(r'(https?://[^"\'>\s]+/category/downloadz/\?r=\d+[^"\'>\s]*)', tmp.text)
            if m:
                r_link = m.group(1)
            elif '?r=' in tmp.url:
                r_link = tmp.url
            else:
                if 'location' in tmp.headers and '?r=' in tmp.headers['location']:
                    r_link = tmp.headers['location']
        
        if not r_link:
            return None

        rpage = session.get(r_link, timeout=12)
        rsoup = BeautifulSoup(rpage.text, 'html.parser')

        btn_tag = rsoup.find('a', id='btn') or rsoup.select_one('a.downloadbtn')
        final_asd_url = None

        if btn_tag and btn_tag.get('href'):
            candidate = btn_tag.get('href')
            if candidate.startswith('/'):
                candidate = extract_base_url(r_link) + candidate
            final_asd_url = candidate
        else:
            dynamic_param_pattern = r'([?&][a-zA-Z0-9_]+\d*=[^"&\']+)'
            qs_matches = re.findall(dynamic_param_pattern, rpage.text)
            params = []
            for q in qs_matches:
                normalized_param = q.lstrip('?&')
                if normalized_param.lower().startswith('r='):
                    continue
                param_name = normalized_param.split('=', 1)[0]
                if not any(p.startswith(param_name + '=') for p in params):
                    params.append(normalized_param)
            if params:
                sep = '&' if '?' in r_link else '?'
                final_asd_url = r_link + sep + '&'.join(params)

        if not final_asd_url:
            final_asd_url = r_link

        final_resp = session.get(final_asd_url, timeout=15)
        if final_resp.status_code != 200:
            return None
            
        fsoup = BeautifulSoup(final_resp.text, 'html.parser')
        final_tag = fsoup.find('a', id='btn') or fsoup.find('a', class_='downloadbtn') or fsoup.find('a', href=re.compile(r'\.mp4'))
        
        if not final_tag:
            return None

        file_link = final_tag.get('href')
        if file_link and file_link.startswith('/'):
            file_link = extract_base_url(final_asd_url) + file_link

        file_name = None
        file_size = None
        try:
            name_span = fsoup.select_one('.TitleCenteral h3 span')
            if name_span:
                file_name = name_span.get_text(strip=True)
            size_span = fsoup.select_one('.TitleCenteral h3:nth-of-type(2) span')
            if size_span:
                file_size = size_span.get_text(strip=True)
        except Exception:
            pass

        if not file_size:
            h3 = fsoup.find('h3')
            if h3:
                msize = re.search(r'الحجم[:\s\-—]*([\d\.,]+\s*(?:MB|GB))', h3.get_text())
                if msize:
                    file_size = msize.group(1)

        if not file_name:
            file_name = os.path.basename(file_link) if file_link else "unknown"

        return {
            'direct_link': file_link.replace(" ", ".") if file_link else None,
            'file_name': file_name,
            'file_size': file_size or "Unknown"
        }

    except Exception as e:
        logger.error(f"Error extracting download info: {e}")
        return None

def find_last_numeric_segment_in_path(path_unquoted):
    parts = path_unquoted.strip('/').split('-')
    for i in range(len(parts)-1, -1, -1):
        if re.fullmatch(r'\d+', parts[i]):
            return i, parts[i]
    return None, None

def build_episode_url_from_any(url, episode_number):
    p = urlparse(url)
    path_unquoted = unquote(p.path)
    idx, num = find_last_numeric_segment_in_path(path_unquoted)
    if idx is None:
        return None
    parts = path_unquoted.strip('/').split('-')[:idx+1]
    parts[-1] = str(episode_number)
    new_path = '/' + '-'.join(parts)
    quoted_path = quote(new_path, safe="/%")
    new_parsed = (p.scheme, p.netloc, quoted_path, '', '', '')
    return urlunparse(new_parsed)

def extract_episode_and_base(url):
    p = urlparse(url)
    path_unquoted = unquote(p.path)
    idx, num = find_last_numeric_segment_in_path(path_unquoted)
    if idx is None or num is None:
        return None, None
    return int(num), lambda ep: build_episode_url_from_any(url, ep)

def process_single_episode(arabseed_url, session):
    try:
        if '/l/' in arabseed_url or 'reviewrate.net' in arabseed_url:
            arabseed_url = follow_redirect(arabseed_url, session=session) or arabseed_url

        try:
            resp = session.get(arabseed_url, timeout=12)
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return None, None

        if resp.status_code == 404:
            return False, None
        if resp.status_code != 200:
            time.sleep(1.2)
            try:
                resp = session.get(arabseed_url, timeout=12)
            except Exception:
                return None, None
            if resp.status_code != 200:
                return False, None

        text_lower = resp.text.lower()
        if any(phrase in text_lower for phrase in ['لم يتم العثور', 'page not found', 'صفحة غير موجودة', 'not found']):
            return False, None

        soup = BeautifulSoup(resp.text, 'html.parser')
        download_anchor = soup.find('a', href=re.compile(r'/download/')) or soup.find('a', class_=re.compile(r'download__btn|downloadBTn'))
        if not download_anchor:
            return False, None

        quality_page_url = download_anchor.get('href')
        if quality_page_url.startswith('/'):
            quality_page_url = extract_base_url(arabseed_url) + quality_page_url
        base_url = extract_base_url(arabseed_url)

        try:
            qresp = session.get(quality_page_url, headers={'Referer': base_url + '/'}, timeout=12)
            if qresp.status_code != 200:
                return False, None
        except Exception:
            return None, None

        qsoup = BeautifulSoup(qresp.text, 'html.parser')
        server_links = qsoup.find_all('a', href=re.compile(r'/l/'))
        if not server_links:
            server_links = qsoup.select('ul.downloads__links__list a') or qsoup.find_all('a', class_=re.compile(r'download__item|arabseed'))

        if not server_links:
            return False, None

        telegram_buttons = []
        referer = extract_base_url(quality_page_url) + "/"
        seen_qualities = set()

        for a in server_links:
            href = a.get('href')
            if not href:
                continue
            if 'arabseed' not in href and 'عرب سيد' not in a.get_text(" ", strip=True):
                continue

            quality = "Unknown"
            parent_with_quality = a.find_parent(attrs={"data-quality": True})
            if parent_with_quality:
                quality = parent_with_quality.get('data-quality')
            else:
                ptxt = a.get_text(" ", strip=True)
                qmatch = re.search(r'(\d{3,4}p)', ptxt)
                if qmatch:
                    quality = qmatch.group(1)
                else:
                    sq = a.find_previous('div', class_=re.compile(r'txt|text'))
                    if sq:
                        qmatch = re.search(r'(\d{3,4}p)', sq.get_text())
                        if qmatch:
                            quality = qmatch.group(1)

            if quality in seen_qualities:
                continue
            seen_qualities.add(quality)

            info = get_download_info(href, referer)
            if info and info.get('direct_link'):
                btn_text = f"[ {info.get('file_size','?')} ]  •  {quality}"
                telegram_buttons.append([InlineKeyboardButton(btn_text, url=info['direct_link'])])

        if not telegram_buttons:
            return False, None

        media_title = extract_title_from_url(arabseed_url)
        return True, (media_title, telegram_buttons)

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None, None

# ============= معالجات البوت =============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🎬 <b>أهلاً بك في بوت عرب سيد للتحميل</b> 🎬\n\n"
        "📥 <b>كيفية الاستخدام:</b>\n"
        "• أرسل رابط الحلقة أو الفيلم من عرب سيد\n"
        "• سأقوم باستخراج روابط التحميل المباشرة\n"
        "• للمسلسلات: سأسألك إذا كنت تريد تحميل الحلقات التالية تلقائياً\n\n"
        "⚡️ <b>مميزات البوت:</b>\n"
        "• استخراج روابط مباشرة بجودات متعددة\n"
        "• تحميل تلقائي للحلقات المتتالية\n"
        "• سرعة في المعالجة\n\n"
        "💡 <b>مثال:</b>\n"
        "أرسل رابط مثل:\n"
        "<code>https://arabseed.cam/...</code>\n\n"
        "📌 البوت يعمل 24/7 وجاهز لخدمتك!"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    if not url.startswith('http'):
        await update.message.reply_text("❌ الرجاء إرسال رابط صحيح!")
        return

    processing_msg = await update.message.reply_text("⏳ جاري المعالجة... الرجاء الانتظار")
    
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    
    # تحقق إذا كان مسلسل
    is_series = 'مسلسل' in unquote(urlparse(url).path) or 'الحلقة' in unquote(urlparse(url).path)
    
    if is_series:
        current_num, builder = extract_episode_and_base(url)
        if current_num is not None and builder is not None:
            # إنشاء أزرار للاختيار
            keyboard = [
                [InlineKeyboardButton("✅ نعم - حمّل الحلقات التالية", callback_data=f"auto_{current_num}_{url}")],
                [InlineKeyboardButton("❌ لا - حلقة واحدة فقط", callback_data=f"single_{url}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await processing_msg.edit_text(
                f"🎬 تم اكتشاف مسلسل - الحلقة {current_num}\n\n"
                "هل تريد تحميل الحلقات التالية تلقائياً؟",
                reply_markup=reply_markup
            )
            return
    
    # معالجة حلقة واحدة
    result, data = process_single_episode(url, session)
    
    if result is True and data:
        title, buttons = data
        message = (
            "⭕ <b>تـحـمـيـل عـرب سـيـد مـبـاشـر</b> 🗂\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"⌯ <b>{title}</b>\n\n"
            "📂 اختر جودة التحميل:"
        )
        
        reply_markup = InlineKeyboardMarkup(buttons)
        await processing_msg.edit_text(message, parse_mode='HTML', reply_markup=reply_markup)
    elif result is False:
        await processing_msg.edit_text("❌ لم يتم العثور على روابط تحميل!")
    else:
        await processing_msg.edit_text("⚠️ حدث خطأ أثناء المعالجة. حاول مرة أخرى.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    
    if data.startswith("single_"):
        url = data.replace("single_", "")
        await query.edit_message_text("⏳ جاري معالجة الحلقة...")
        
        result, episode_data = process_single_episode(url, session)
        
        if result is True and episode_data:
            title, buttons = episode_data
            message = (
                "⭕ <b>تـحـمـيـل عـرب سـيـد مـبـاشـر</b> 🗂\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"⌯ <b>{title}</b>\n\n"
                "📂 اختر جودة التحميل:"
            )
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(message, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await query.edit_message_text("❌ فشلت المعالجة!")
            
    elif data.startswith("auto_"):
        parts = data.split("_", 2)
        current_num = int(parts[1])
        url = parts[2]
        
        await query.edit_message_text(f"⏳ بدء التحميل التلقائي من الحلقة {current_num}...")
        
        _, builder = extract_episode_and_base(url)
        episodes_processed = 0
        
        while True:
            candidate_url = builder(current_num)
            if not candidate_url:
                break
                
            result, episode_data = process_single_episode(candidate_url, session)
            
            if result is True and episode_data:
                title, buttons = episode_data
                message = (
                    "⭕ <b>تـحـمـيـل عـرب سـيـد مـبـاشـر</b> 🗂\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⌯ <b>{title}</b>\n\n"
                    "📂 اختر جودة التحميل:"
                )
                reply_markup = InlineKeyboardMarkup(buttons)
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=message,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                episodes_processed += 1
                current_num += 1
                time.sleep(0.9)
            elif result is False:
                break
            else:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"⚠️ خطأ في معالجة الحلقة {current_num}"
                )
                break
        
        await query.edit_message_text(
            f"✅ تم الانتهاء!\n"
            f"📊 عدد الحلقات المعالجة: {episodes_processed}"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 <b>دليل استخدام البوت</b>\n\n"
        "<b>الأوامر المتاحة:</b>\n"
        "/start - بدء البوت\n"
        "/help - عرض المساعدة\n\n"
        "<b>طريقة الاستخدام:</b>\n"
        "1️⃣ أرسل رابط من عرب سيد\n"
        "2️⃣ انتظر المعالجة\n"
        "3️⃣ اختر الجودة المناسبة\n"
        "4️⃣ ابدأ التحميل!\n\n"
        "💬 للدعم: تواصل مع المطور"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')

# ============= تشغيل البوت =============
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("🚀 Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
