"""One-off: render the app locally with seeded demo data and capture PWA
manifest screenshots (narrow/mobile + wide/desktop) via Playwright.
Not part of the deploy pipeline - run manually, commit the resulting PNGs."""
import pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "web" / "index.html"
OUT = ROOT / "web" / "screenshots"
OUT.mkdir(exist_ok=True)

SEED_JS = """
() => {
  AUTH.session = {user:{id:'demo', email:'demo@example.com'}};
  S.profile.nameHe = 'רון';
  S.profile.nameEn = 'Ron';
  S.theme = 'dark';
  const wk = weekDates(0);
  S.plan[ymd(wk[0])] = [defaultWorkout('running','recovery',wk[0])];
  S.plan[ymd(wk[1])] = [defaultWorkout('running','intervals',wk[1])];
  S.plan[ymd(wk[2])] = [defaultWorkout('strength','strength',wk[2])];
  S.plan[ymd(wk[3])] = [defaultWorkout('running','tempo',wk[3])];
  S.plan[ymd(wk[0])][0].done = true;
  S.sel = 1;
  render();
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch()

    # narrow (mobile) - 1080x1920 at 2x scale
    page = browser.new_page(viewport={"width": 540, "height": 960}, device_scale_factor=2)
    page.goto(INDEX.as_uri())
    page.wait_for_timeout(300)
    page.evaluate(SEED_JS)
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "mobile-1.png"))
    page.close()

    # wide (desktop) - 1920x1080 at 1x scale, app is centered/narrow so this
    # shows the same UI on a wider canvas, matching how it actually looks on desktop
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(INDEX.as_uri())
    page.wait_for_timeout(300)
    page.evaluate(SEED_JS)
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "desktop-1.png"))
    page.close()

    browser.close()

print("done:", list(OUT.iterdir()))
