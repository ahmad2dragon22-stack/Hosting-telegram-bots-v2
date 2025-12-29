# Hosting-telegram-bots-v2

تشغيل المشروع:

1. ثبت المتطلبات:

```bash
pip install -r requirements.txt
```

2. عيّن متغير التوكن قبل التشغيل. يمكن تعيينه كمتغير بيئة أو في ملف `.env` في نفس المجلد، مثال لمحتوى `.env`:

```
BOT_TOKEN=8519726834:AAHbe2DFx-your-token-here
```

3. شغّل البوت:

```bash
python bot.py
```

ملاحظة: إذا ظهر الخطأ "❌ خطأ: يجب تعيين BOT_TOKEN في متغيرات البيئة." فتأكد من وجود المتغير أعلاه.