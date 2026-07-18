# מסלול (Maslul)

מתכנן אימוני ריצה אישי שדוחף אימונים מובנים לשעון גרמין.

## מבנה
- `web/index.html` - האפליקציה (PWA, עברית RTL, קובץ יחיד ללא build).
- `server/` - ה-backend (FastAPI ל-Vercel) שמתרגם ומתזמן אימונים בגרמין.
- `scripts/generate_token.py` - יצירת טוקן גרמין חד-פעמית (עובד גם ב-Google Colab).
- `CLAUDE.md` - הקשר מלא לפרויקט עבור Claude Code.

## התחלה מהירה
1. הרץ פעם אחת את `scripts/generate_token.py` וקבל את מחרוזת `GARTH_TOKEN`.
2. פרוס את `server/` ל-Vercel, הוסף את `GARTH_TOKEN` (ואופציונלי `API_SECRET`) במשתני הסביבה.
3. פרסם את `web/index.html` ל-GitHub Pages או ל-Vercel.
4. באפליקציה, בחלון השליחה, הגדר את כתובת ה-backend ל-`https://<project>.vercel.app/schedule-week`.

פרטים מלאים ב-`CLAUDE.md`.
