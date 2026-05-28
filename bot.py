import os, json, pandas as pd, easyocr, requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== الإعدادات (ستُمرر كمتغيرات بيئة عند النشر) ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ضع_توكن_البوت_هنا")
AUTHORIZED_USERS = [int(u) for u in os.environ.get("AUTHORIZED_USERS", "").split(",") if u]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "ضع_توكن_GitHub_هنا")
GIST_ID = os.environ.get("GIST_ID", "ضع_معرف_الـ_Gist_هنا")
TEMP_DIR = "temp_images"
os.makedirs(TEMP_DIR, exist_ok=True)

# EasyOCR (يدعم العربية والإنجليزية)
reader = easyocr.Reader(['ar', 'en'], gpu=False)  # gpu=False لتوفير الموارد على السيرفر

# ========== دوال استخراج الأدوية ==========
def extract_medicines_from_text(text):
    """تحليل النص لاستخراج اسم الدواء وسعر البيع"""
    lines = text.strip().split('\n')
    medicines = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2:
            try:
                price = float(parts[-1].replace(',', ''))
            except:
                continue
            name = ' '.join(parts[:-1]).strip()
            if name:
                medicines.append({"name": name, "selling_price": price})
    return medicines

def process_image(image_path):
    """OCR على الصورة واستخراج النص"""
    results = reader.readtext(image_path, detail=0, paragraph=True)
    full_text = '\n'.join(results)
    return extract_medicines_from_text(full_text)

def read_excel(file_path):
    """قراءة ملف Excel (يتوقع عمود 'name' أو 'اسم الدواء' و 'selling_price' أو 'السعر')"""
    df = pd.read_excel(file_path)
    medicines = []
    for _, row in df.iterrows():
        name = row.get("name") or row.get("اسم الدواء") or ""
        price = row.get("selling_price") or row.get("السعر") or 0
        if name and price:
            medicines.append({"name": str(name), "selling_price": float(price)})
    return medicines

def upload_to_github_gist(file_path):
    """رفع ملف prices.json إلى Gist وإرجاع رابط raw"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"files": {"prices.json": {"content": content}}}
    resp = requests.patch(f"https://api.github.com/gists/{GIST_ID}", json=data, headers=headers)
    if resp.status_code == 200:
        return resp.json()["files"]["prices.json"]["raw_url"]
    else:
        raise Exception(f"فشل الرفع: {resp.status_code}")

# ========== معالجات البوت ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أرسل صورة النشرة، ملف Excel، أو نصاً بالشكل:\nاسم_الدواء السعر"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("⛔ غير مصرح لك.")
        return

    medicines = None

    if update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        img_path = os.path.join(TEMP_DIR, f"{user_id}.jpg")
        await file.download_to_drive(img_path)
        await update.message.reply_text("🔍 جارٍ تحليل الصورة...")
        try:
            medicines = process_image(img_path)
        finally:
            os.remove(img_path)

    elif update.message.document:
        doc = update.message.document
        if not doc.file_name.endswith('.xlsx'):
            await update.message.reply_text("⚠️ يرجى إرسال ملف Excel فقط.")
            return
        file = await doc.get_file()
        file_path = os.path.join(TEMP_DIR, doc.file_name)
        await file.download_to_drive(file_path)
        await update.message.reply_text("📊 جارٍ قراءة الملف...")
        try:
            medicines = read_excel(file_path)
        finally:
            os.remove(file_path)

    elif update.message.text:
        medicines = extract_medicines_from_text(update.message.text)

    else:
        await update.message.reply_text("❌ نوع الملف غير مدعوم.")
        return

    if not medicines:
        await update.message.reply_text("❌ لم أستخرج أي دواء. تأكد من التنسيق.")
        return

    # حفظ JSON
    output = {"medicines": medicines, "updated_at": str(pd.Timestamp.now())}
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # رفع إلى Gist
    try:
        raw_url = upload_to_github_gist("prices.json")
        await update.message.reply_text(
            f"✅ تم تحديث أسعار {len(medicines)} دواء.\n"
            f"الرابط الجديد للتطبيق:\n{raw_url}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ فشل رفع الملف: {str(e)}")

async def prices_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists("prices.json"):
        await update.message.reply_text("لا يوجد تحديثات بعد.")
        return
    with open("prices.json", "rb") as f:
        await update.message.reply_document(f, filename="prices.json")

# ========== تشغيل البوت ==========
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("prices", prices_cmd))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL | filters.TEXT, handle_message))
    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
