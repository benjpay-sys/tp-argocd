"""Capture des screenshots supplementaires avec etat sain."""
import time, json, urllib.request
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

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
opts.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(options=opts)
wait = WebDriverWait(driver, 20)

def shot(name, delay=2):
    time.sleep(delay)
    p = str(ASSETS / f"{name}.png")
    driver.save_screenshot(p)
    size = Path(p).stat().st_size // 1024
    print(f"  {name}.png ({size}KB)")

# ArgoCD login via API token
req_data = json.dumps({"username": "admin", "password": ARGOCD_PASS}).encode()
req = urllib.request.Request("http://argocd.devhub.local/api/v1/session",
                             data=req_data, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    argocd_token = json.loads(resp.read())["token"]

def argocd_go(path, name, delay=5):
    driver.get("http://argocd.devhub.local")
    time.sleep(1)
    try:
        driver.delete_all_cookies()
    except:
        pass
    driver.add_cookie({"name": "argocd.token", "value": argocd_token,
                       "domain": "argocd.devhub.local", "path": "/"})
    driver.get(f"http://argocd.devhub.local{path}")
    shot(name, delay)

print("=== Screenshots supplementaires ===\n")

# Prometheus targets (tous UP)
print("[Prometheus] Targets")
driver.get("http://prometheus.devhub.local/targets")
shot("e03-prometheus-targets-up", 4)

# Prometheus rules
print("[Prometheus] Rules")
driver.get("http://prometheus.devhub.local/rules")
shot("e03-prometheus-rules-ok", 3)

# Prometheus alerts
print("[Prometheus] Alerts")
driver.get("http://prometheus.devhub.local/alerts")
shot("e07-prometheus-alerts-ok", 3)

# Prometheus PromQL - rate de requetes par service
print("[Prometheus] PromQL RPS par service")
query = "sum(rate(http_requests_total{namespace=\"devhub-dev\"}[5m])) by (service)"
import urllib.parse
q_enc = urllib.parse.quote(query)
driver.get(f"http://prometheus.devhub.local/graph?g0.expr={q_enc}&g0.tab=0")
shot("e04-prometheus-query-rps-up", 5)

# Argo Rollouts - namespace devhub-dev
print("[Argo Rollouts] Namespace")
driver.get("http://rollouts.devhub.local/rollouts/devhub-dev")
shot("e05-rollouts-namespace-healthy", 5)

# ArgoCD - toutes les apps
print("[ArgoCD] Toutes les applications")
argocd_go("/applications", "global-argocd-all-apps-healthy", 6)

# ArgoCD - annuaire-dev
print("[ArgoCD] annuaire-dev")
argocd_go("/applications/argocd/annuaire-dev", "e05-argocd-annuaire-healthy", 7)

# ArgoCD - planning-dev
print("[ArgoCD] planning-dev")
argocd_go("/applications/argocd/planning-dev", "e08-argocd-planning-healthy", 7)

# ArgoCD - kube-prometheus-stack
print("[ArgoCD] kube-prometheus-stack")
argocd_go("/applications/argocd/kube-prometheus-stack", "e03-argocd-kps-healthy", 7)

# ArgoCD - argo-rollouts
print("[ArgoCD] argo-rollouts")
argocd_go("/applications/argocd/argo-rollouts", "e05-argocd-rollouts-healthy", 7)

# Grafana login
print("[Grafana] Login et home")
driver.get("http://grafana.devhub.local/login")
time.sleep(3)
try:
    u = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='user']")))
    u.clear(); u.send_keys("admin")
    p = driver.find_element(By.CSS_SELECTOR, "input[name='password']")
    p.clear(); p.send_keys(GRAFANA_PASS)
    p.send_keys(Keys.RETURN)
    time.sleep(4)
    shot("e04-grafana-home-ok", 2)
    print("  Grafana logged in")

    # Dashboards list
    driver.get("http://grafana.devhub.local/dashboards")
    shot("e04-grafana-dashboards-ok", 3)

    # Dashboard RED
    driver.get("http://grafana.devhub.local/d/services-red/services-red")
    shot("e04-grafana-dashboard-red-ok", 5)

except Exception as e:
    print(f"  Grafana error: {e}")
    shot("e04-grafana-error")

driver.quit()
print("\n=== Done ===")
