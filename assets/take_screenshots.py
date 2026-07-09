"""
Script de capture d'ecran automatise pour le rapport TP3.
Utilise Selenium + Chrome headless pour capturer toutes les UIs.
"""
import time, os, subprocess, sys
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium", "webdriver-manager", "-q"])
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

ASSETS = Path(__file__).parent / "screenshots"
ASSETS.mkdir(exist_ok=True)

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ARGOCD_PASS = "Admin1234!"
GRAFANA_PASS = "ChangeMe123!"

opts = Options()
opts.binary_location = CHROME
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-gpu")
opts.add_argument("--window-size=1440,900")
opts.add_argument("--hide-scrollbars")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--ignore-certificate-errors")
opts.add_argument("--host-resolver-rules=")

driver = webdriver.Chrome(options=opts)
wait = WebDriverWait(driver, 15)

def shot(name, delay=2):
    time.sleep(delay)
    p = str(ASSETS / f"{name}.png")
    driver.save_screenshot(p)
    size = Path(p).stat().st_size // 1024
    print(f"  OK  {name}.png ({size}KB)")

def go(url, delay=2):
    driver.get(url)
    time.sleep(delay)

print("=== Screenshot TP3 ===\n")

# ── ETAPE 0 : ArgoCD login ──────────────────────────────────────────────────
print("[E00] ArgoCD – connexion et liste des applications")
go("http://argocd.devhub.local", 3)
shot("e00-argocd-login-page")

try:
    import urllib.request, json as _json
    # Login via ArgoCD REST API to get token
    req_data = _json.dumps({"username": "admin", "password": ARGOCD_PASS}).encode()
    req = urllib.request.Request("http://argocd.devhub.local/api/v1/session",
                                 data=req_data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        token = _json.loads(resp.read())["token"]
    print(f"  Got ArgoCD token: {token[:20]}...")
    # Set cookie in the browser
    driver.get("http://argocd.devhub.local")
    time.sleep(2)
    driver.add_cookie({"name": "argocd.token", "value": token, "domain": "argocd.devhub.local"})
    driver.get("http://argocd.devhub.local/applications")
    time.sleep(4)
    shot("e00-argocd-applications")
    print("  ArgoCD logged in via API token")
except Exception as e:
    print(f"  ArgoCD login error: {e}")
    shot("e00-argocd-error")

# ── ETAPE 3 : kube-prometheus-stack dans ArgoCD ─────────────────────────────
print("[E03] ArgoCD – kube-prometheus-stack")
go("http://argocd.devhub.local/applications/argocd/kube-prometheus-stack", 3)
shot("e03-argocd-kube-prometheus-stack")

# ── ETAPE 3 : Prometheus targets ────────────────────────────────────────────
print("[E03] Prometheus – Status/Targets")
go("http://prometheus.devhub.local/targets", 3)
shot("e03-prometheus-targets")

# ── ETAPE 3 : Prometheus rules ──────────────────────────────────────────────
print("[E03] Prometheus – Status/Rules")
go("http://prometheus.devhub.local/rules", 2)
shot("e03-prometheus-rules")

# ── ETAPE 4 : Grafana login ─────────────────────────────────────────────────
print("[E04] Grafana – connexion et dashboard RED")
go("http://grafana.devhub.local/login", 3)
shot("e04-grafana-login")
try:
    u2 = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='user']")))
    u2.clear(); u2.send_keys("admin")
    p2 = driver.find_element(By.CSS_SELECTOR, "input[name='password']")
    p2.clear(); p2.send_keys(GRAFANA_PASS)
    p2.send_keys(Keys.RETURN)
    time.sleep(4)
    shot("e04-grafana-home")
    print("  Grafana logged in")
except Exception as e:
    print(f"  Grafana login error: {e}")
    shot("e04-grafana-error")

# ── ETAPE 4 : Dashboard RED ─────────────────────────────────────────────────
print("[E04] Grafana – Dashboard Services RED")
go("http://grafana.devhub.local/dashboards", 2)
shot("e04-grafana-dashboards-list")
# Try to open the dashboard by searching
go("http://grafana.devhub.local/d/services-red/services-red", 3)
shot("e04-grafana-dashboard-red", delay=3)

# ── ETAPE 4 : Prometheus – requete PromQL ───────────────────────────────────
print("[E04] Prometheus – requete PromQL RPS")
go("http://prometheus.devhub.local/graph?g0.expr=sum(rate(http_requests_total%7Bnamespace%3D%22devhub-dev%22%7D%5B5m%5D))%20by%20(service)&g0.tab=0", 4)
shot("e04-prometheus-query-rps")

# ── ETAPE 5 : Argo Rollouts dashboard ───────────────────────────────────────
print("[E05] Argo Rollouts – dashboard")
go("http://rollouts.devhub.local", 3)
shot("e05-rollouts-dashboard")

go("http://rollouts.devhub.local/rollouts/devhub-dev", 3)
shot("e05-rollouts-namespace")

# ── ETAPE 7 : AnalysisRun ───────────────────────────────────────────────────
print("[E07] Prometheus – alerte AnnuaireHighErrorRate")
go("http://prometheus.devhub.local/alerts", 3)
shot("e07-prometheus-alerts")

# ── ETAPE 10 : Alertmanager ─────────────────────────────────────────────────
print("[E10] Alertmanager")
go("http://prometheus.devhub.local/alerts#AnnuaireHighErrorRate", 2)
shot("e10-prometheus-alert-rules")

# ── ETAPE 10 : ArgoCD – argo-rollouts app ────────────────────────────────────
print("[E10] ArgoCD – argo-rollouts application")
go("http://argocd.devhub.local/applications/argocd/argo-rollouts", 3)
shot("e10-argocd-argo-rollouts")

# ── Vue globale ArgoCD toutes les apps ──────────────────────────────────────
print("[GLOBAL] ArgoCD – toutes les applications")
go("http://argocd.devhub.local/applications", 3)
shot("global-argocd-all-apps")

# ── Annuaire app ArgoCD ─────────────────────────────────────────────────────
print("[E05] ArgoCD – annuaire-dev detail")
go("http://argocd.devhub.local/applications/argocd/annuaire-dev", 4)
shot("e05-argocd-annuaire-dev")

# ── Planning app ArgoCD ─────────────────────────────────────────────────────
print("[E08] ArgoCD – planning-dev detail")
go("http://argocd.devhub.local/applications/argocd/planning-dev", 4)
shot("e08-argocd-planning-dev")

driver.quit()
print("\n=== Terminé ===")
print(f"Screenshots dans : {ASSETS}")
