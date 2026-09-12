# ماسح المراجحة — Polygon (KyberSwap Elastic ⇄ QuickSwap v3)

سكربت بايثون يفحص دورياً فرص المراجحة على شبكة Polygon بين KyberSwap Elastic
وQuickSwap v3، باستخدام GeckoTerminal Public API (**بدون أي مفتاح API**)،
ويرسل النتائج إلى بوت تيليجرام.

## 1) إنشاء بوت تيليجرام (دقيقتان)

1. افتح تيليجرام وابحث عن `@BotFather`.
2. أرسل له `/newbot` واتبع التعليمات (اسم + username ينتهي بـ `bot`).
3. سيعطيك **توكن** شكله مثل: `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
   → هذا هو `TELEGRAM_BOT_TOKEN`.
4. للحصول على `chat_id` الخاص بك:
   - أرسل أي رسالة للبوت الذي أنشأته (اكتب له "hi" مثلاً).
   - افتح في المتصفح:
     `https://api.telegram.org/bot<التوكن>/getUpdates`
   - ستجد في الرد رقم `"chat":{"id": 123456789 ...}` — هذا هو `TELEGRAM_CHAT_ID`.

## 2) رفع المشروع إلى Railway

1. أنشئ حساباً على https://railway.com إن لم يكن لديك.
2. اضغط **New Project → Deploy from GitHub repo** (ارفع هذه الملفات إلى مستودع GitHub أولاً)،
   أو استخدم **Empty Project** ثم ارفع الملفات عبر Railway CLI.
3. في تبويب **Variables** أضف:
   ```
   TELEGRAM_BOT_TOKEN = <التوكن من BotFather>
   TELEGRAM_CHAT_ID   = <معرف المحادثة>
   ```
4. Railway سيكتشف تلقائياً أنه Python (بفضل `requirements.txt`) وسيشغّل الأمر
   الموجود في `Procfile` (`worker: python main.py`).
   - تأكد أنك اخترت نوع الخدمة **Worker** وليس **Web Service** (لا يوجد منفذ HTTP هنا).

## 3) متغيرات اختيارية لتعديل الشروط دون تعديل الكود

يمكنك ضبطها من نفس تبويب Variables في Railway:

| المتغير | الافتراضي | الوصف |
|---|---|---|
| `SCAN_INTERVAL_MINUTES` | 15 | كل كم دقيقة يعيد الفحص |
| `MIN_LIQUIDITY_USD` / `MAX_LIQUIDITY_USD` | 1000 / 10000 | نطاق السيولة |
| `MIN_VOLUME_USD` / `MAX_VOLUME_USD` | 500 / 10000 | نطاق الحجم اليومي |
| `MIN_TXNS_24H` / `MAX_TXNS_24H` | 20 / 300 | نطاق عدد المعاملات |
| `MIN_TRADERS_24H` / `MAX_TRADERS_24H` | 10 / 100 | نطاق عدد المتداولين |
| `MIN_PRICE_DIFF_PCT` / `MAX_PRICE_DIFF_PCT` | 1.5 / 15 | نطاق فرق السعر المقبول |

## 4) تشغيل محلي للتجربة قبل الرفع

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="التوكن"
export TELEGRAM_CHAT_ID="المعرف"
python main.py
```

## ملاحظات مهمة

- **بدون مفتاح API**: GeckoTerminal العام يسمح باستخدام مجاني بدون تسجيل
  (حد تقريبي 10-30 طلب/دقيقة)، لذلك السكربت ينتظر بين الطلبات لتفادي الحظر المؤقت (429).
- **تقدير الربح تقريبي وليس دقيقاً 100%**: الرسوم الفعلية لكل مجمع على KyberSwap
  وQuickSwap تختلف حسب الـ tier المُختار، والانزلاق الحقيقي يعتمد على شكل منحنى
  السيولة الفعلي (لا يمكن معرفته بدقة من endpoint الأساسي). عامل الانزلاق في
  الكود تحفظي (50%) لتجنّب فرص وهمية — يمكنك تعديله عبر تحرير `SLIPPAGE_SAFETY_FACTOR`
  مباشرة في `main.py`.
- **عدد المتداولين**: GeckoTerminal لا يوفر رقم "متداولين فريدين" موحّداً، لذلك
  السكربت يقدّره كأكبر قيمة بين عدد المشترين وعدد البائعين خلال 24 ساعة (تقدير
  تحفظي وليس دقيقاً).
- **إخلاء مسؤولية**: هذه أداة بيانات وفرز فقط، وليست توصية استثمارية أو ضماناً
  لتنفيذ الصفقة بنفس السعر المعروض. السيولة الضعيفة تعني انزلاقاً حقيقياً قد
  يكون أعلى من المُقدَّر، وتوصى دائماً بالتحقق يدوياً من كل مجمع على
  GeckoTerminal قبل أي تنفيذ فعلي.
