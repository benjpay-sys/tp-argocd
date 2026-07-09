"""
Convertit RAPPORT_VALIDATION.md en PDF via :
  1. Retake screenshot Grafana avec le bon mot de passe
  2. Python `markdown` → HTML avec CSS intégré
  3. Selenium CDP Page.printToPDF (sans en-têtes Chrome)
"""
import subprocess, sys, re, base64, json, time
from pathlib import Path

# ── Dépendances ──────────────────────────────────────────────────────────────
for pkg in ("markdown", "selenium"):
    try:
        __import__(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

import markdown
from markdown.extensions.tables import TableExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

ROOT         = Path(__file__).parent.parent
SRC          = ROOT / "RAPPORT_VALIDATION.md"
HTML         = ROOT / "assets" / "rapport_validation.html"
PDF          = ROOT / "RAPPORT_VALIDATION.pdf"
SCREENSHOTS  = ROOT / "assets" / "screenshots"
CHROME       = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GRAFANA_PASS = "DevHubSRE2025!"
ARGOCD_PASS  = "Admin1234!"

# ── 0. Retake Grafana home (login corrigé) ────────────────────────────────────
print("Retake Grafana home screenshot…")
opts = Options()
opts.binary_location = CHROME
for a in ("--headless=new","--no-sandbox","--disable-gpu","--window-size=1440,900",
          "--disable-dev-shm-usage"):
    opts.add_argument(a)
drv = webdriver.Chrome(options=opts)
w   = WebDriverWait(drv, 20)
try:
    drv.get("http://grafana.devhub.local/login")
    time.sleep(3)
    u = w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='user']")))
    u.clear(); u.send_keys("admin")
    p = drv.find_element(By.CSS_SELECTOR, "input[name='password']")
    p.clear(); p.send_keys(GRAFANA_PASS); p.send_keys(Keys.RETURN)
    time.sleep(4)
    drv.save_screenshot(str(SCREENSHOTS / "e04-grafana-home-ok.png"))
    kb = (SCREENSHOTS / "e04-grafana-home-ok.png").stat().st_size // 1024
    print(f"  e04-grafana-home-ok.png ({kb}KB)")

    drv.get("http://grafana.devhub.local/dashboards")
    time.sleep(3)
    drv.save_screenshot(str(SCREENSHOTS / "e04-grafana-dashboards-ok.png"))

    drv.get("http://grafana.devhub.local/d/services-red/services-red")
    time.sleep(4)
    drv.save_screenshot(str(SCREENSHOTS / "e04-grafana-dashboard-red-ok.png"))
    print("  Grafana screenshots OK")
except Exception as e:
    print(f"  Grafana error: {e}")
finally:
    drv.quit()

# ── 1. Lire le markdown ──────────────────────────────────────────────────────
md_text = SRC.read_text(encoding="utf-8")

def fix_img_paths(text):
    def repl(m):
        alt, path = m.group(1), m.group(2)
        return f"![{alt}]({(ROOT / path).resolve().as_uri()})"
    return re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', repl, text)

md_text = fix_img_paths(md_text)

# ── 2. Markdown → HTML ───────────────────────────────────────────────────────
md_conv = markdown.Markdown(extensions=[
    TableExtension(), FencedCodeExtension(),
    "md_in_html", "attr_list",
])
body_html = md_conv.convert(md_text)

# ── 3. HTML complet avec CSS ─────────────────────────────────────────────────
CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
@page { margin: 18mm 15mm 18mm 15mm; }
body {
  font-family: "Segoe UI", system-ui, Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.65;
  color: #1a1a2e;
}

/* ── Titres ── */
h1 {
  font-size: 24pt; color: #0f3460;
  border-bottom: 3px solid #0f3460; padding-bottom: 10px;
  margin: 0 0 28px;
}
h2 {
  font-size: 14pt; color: #16213e;
  border-bottom: 2px solid #0f3460; padding-bottom: 4px;
  margin: 36px 0 14px;
  page-break-before: always;
}
h2:first-of-type { page-break-before: avoid; }
h3 { font-size: 11.5pt; color: #0f3460; margin: 22px 0 8px; }
h4 { font-size: 10.5pt; color: #555; margin: 16px 0 6px; font-weight: 600; }

/* ── Paragraphes ── */
p  { margin: 8px 0 10px; }
ul, ol { margin: 6px 0 10px 24px; }
li { margin: 3px 0; }

/* ── Séparateur ── */
hr { border: none; border-top: 1px solid #ddd; margin: 24px 0; }

/* ── Code inline ── */
code {
  background: #f2f6fb;
  border: 1px solid #d0dce8;
  border-radius: 3px;
  padding: 1px 5px;
  font-family: "Cascadia Code", Consolas, "Courier New", monospace;
  font-size: 9pt;
  color: #b5294e;
}

/* ── Blocs de code ── */
pre {
  background: #1a1e30;
  color: #cdd6f4;
  border-radius: 6px;
  padding: 13px 16px;
  margin: 10px 0 16px;
  font-family: "Cascadia Code", Consolas, "Courier New", monospace;
  font-size: 8.5pt;
  line-height: 1.55;
  page-break-inside: avoid;
  white-space: pre-wrap;
  word-break: break-all;
}
pre code {
  background: none; border: none; padding: 0;
  color: inherit; font-size: inherit;
}

/* ── Tables ── */
table {
  border-collapse: collapse; width: 100%;
  margin: 12px 0 18px; font-size: 9.8pt;
  page-break-inside: avoid;
}
thead tr { background: #0f3460; color: #fff; }
th { padding: 8px 12px; text-align: left; font-weight: 600; }
td { padding: 6px 12px; border-bottom: 1px solid #dce6f0; vertical-align: top; }
tbody tr:nth-child(even) td { background: #f5f8fc; }
tbody tr:last-child td { border-bottom: 2px solid #0f3460; }

/* ── Images ── */
img {
  max-width: 100%; height: auto;
  border: 1px solid #c8d6e2; border-radius: 5px;
  box-shadow: 0 2px 6px rgba(0,0,0,.10);
  margin: 10px 0 16px; display: block;
  page-break-inside: avoid;
}

/* ── Liens ── */
a { color: #0f3460; text-decoration: none; }
"""

full_html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Rapport Validation — DevHub Campus SRE TP3</title>
  <style>{CSS}</style>
</head>
<body>
{body_html}
</body>
</html>
"""

HTML.write_text(full_html, encoding="utf-8")
print(f"HTML écrit : {HTML}")

# ── 4. Selenium CDP → PDF (sans en-têtes Chrome) ────────────────────────────
print("Génération PDF via Selenium CDP…")
opts2 = Options()
opts2.binary_location = CHROME
for a in ("--headless=new","--no-sandbox","--disable-gpu","--disable-extensions",
          "--disable-dev-shm-usage"):
    opts2.add_argument(a)

drv2 = webdriver.Chrome(options=opts2)
try:
    drv2.get(HTML.as_uri())
    time.sleep(3)          # laisser le rendu se stabiliser
    result = drv2.execute_cdp_cmd("Page.printToPDF", {
        "printBackground":      True,
        "displayHeaderFooter":  False,   # ← supprime date/URL/numéros Chrome
        "paperWidth":           8.27,    # A4 pouces
        "paperHeight":          11.69,
        "marginTop":            0.7,
        "marginBottom":         0.7,
        "marginLeft":           0.6,
        "marginRight":          0.6,
        "scale":                0.92,
    })
    pdf_bytes = base64.b64decode(result["data"])
    PDF.write_bytes(pdf_bytes)
    print(f"PDF généré  : {PDF}  ({len(pdf_bytes)//1024} KB)")
finally:
    drv2.quit()
