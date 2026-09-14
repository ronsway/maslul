# מסלול (Maslul)

מתכנן אימוני ריצה אישי שדוחף אימונים מובנים לשעון גרמין.

כל משתמש מחבר את חשבון הגרמין שלו ומקבל תוכנית משלו, מסונכרנת בענן (Supabase).
לא מוצר ציבורי - לבעלים ולכמה אנשים קרובים.

## מבנה
- `web/index.html` - האפליקציה (PWA, עברית RTL, קובץ יחיד ללא build).
  כולל `manifest.json`, `sw.js`, אייקונים וצילומי מסך לחנויות אפליקציות.
- `server/` - ה-backend (FastAPI ל-Vercel) שמתרגם ומתזמן אימונים בגרמין,
  ומנהל את חיבורי הגרמין הפרטיים של כל משתמש (`server/api/garmin_auth.py`).
- `scripts/generate_token.py` - יצירת טוקן גרמין מקומית (למקרה של אתגר MFA
  שההרשמה הרגילה באפליקציה לא תומכת בו).
- `scripts/capture_screenshots.py` - צילומי מסך לחנות (Playwright, חד-פעמי).
- `deploy.bat` - workflow הפריסה הרגיל: מעלה גרסה, פורס backend+frontend ל-Vercel,
  ואז מבצע commit+push. ראו `CHANGELOG.md` להיסטוריית הפריסות.
- `CLAUDE.md` - ההקשר המלא לפרויקט: מודל האימונים, אימות גרמין פר-משתמש,
  ארוז ל-APK אנדרואיד, קונבנציות UI, ועוד.

## התחלה מהירה
1. פרוס את `server/` ל-Vercel (root directory: `server/`), הוסף את משתני הסביבה
   `GARMIN_TOKEN_ENCRYPTION_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
   `SUPABASE_SERVICE_ROLE_KEY` (פרטים ב-`CLAUDE.md`).
2. הרץ פעם אחת את `server/sql/garmin_connections.sql` ב-Supabase SQL editor.
3. פרסם את `web/` (GitHub Pages או Vercel static).
4. כל משתמש מתחבר עם Google/Email ומחבר את חשבון הגרמין שלו מתוך Settings >
   Garmin באפליקציה - אין יותר טוקן גלובלי אחד להגדיר.

לפריסות הבאות, פשוט `deploy.bat` מהשורש. פרטים מלאים ב-`CLAUDE.md`.
