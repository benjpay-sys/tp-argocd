# Guide d'utilisation — DevHub Campus SRE (TP 3)

Ce fichier explique comment démarrer, opérer et tester la stack complète du TP 3.
Il part de zéro (poste propre) et couvre chaque couche jusqu'aux rollouts progressifs.

---

## Prérequis

| Outil | Version minimale | Installation |
|---|---|---|
| Docker Desktop | ≥ 25 (WSL2 backend sur Windows) | docker.com |
| kind | ≥ 0.23 | `brew install kind` / [kind.sigs.k8s.io](https://kind.sigs.k8s.io/) |
| kubectl | ≥ 1.29 | `brew install kubectl` |
| Helm | ≥ 3.14 | `brew install helm` |
| argocd CLI | ≥ 2.12 | `brew install argocd` |
| kubectl-argo-rollouts | ≥ 1.7 | voir section ci-dessous |
| promtool | ≥ 2.50 | livré avec Prometheus tarball |

Vérification globale :

```bash
make tools-check
```

### Installer le plugin kubectl-argo-rollouts (Windows/WSL2)

```bash
curl -LO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
chmod +x kubectl-argo-rollouts-linux-amd64
sudo mv kubectl-argo-rollouts-linux-amd64 /usr/local/bin/kubectl-argo-rollouts
# Vérification
kubectl argo rollouts version
```

---

## 1. Démarrer le cluster

```bash
make cluster-up
```

Crée un cluster kind `pulse` (1 control-plane + 1 worker).
Les ports 80/443 du nœud control-plane sont mappés sur localhost.

Vérification :

```bash
kubectl get nodes
# NAME                  STATUS   ROLES
# pulse-control-plane   Ready    control-plane
# pulse-worker          Ready    <none>
```

---

## 2. Fichier `/etc/hosts`

```bash
make hosts-print
```

Copier les lignes affichées dans :
- **Linux/macOS** : `/etc/hosts`
- **Windows** : `C:\Windows\System32\drivers\etc\hosts` (en tant qu'administrateur)

```
127.0.0.1  argocd.devhub.local
127.0.0.1  grafana.devhub.local
127.0.0.1  prometheus.devhub.local
127.0.0.1  rollouts.devhub.local
127.0.0.1  annuaire.devhub.local
127.0.0.1  planning.devhub.local
127.0.0.1  notif.devhub.local
```

---

## 3. Installer ingress-nginx et ArgoCD

```bash
make argocd-install
```

Installe ingress-nginx (NodePort, hostPort) puis ArgoCD via Helm.

Récupérer le mot de passe admin initial :

```bash
make argocd-password
```

Ouvrir [http://argocd.devhub.local](http://argocd.devhub.local) → login `admin` / mot de passe ci-dessus.

---

## 4. Secrets hors-Git (à créer une seule fois)

Ces secrets ne sont jamais versionnés. Ils doivent être créés avant le premier sync ArgoCD.

### 4a. Mot de passe Grafana

```bash
kubectl create secret generic grafana-admin-secret \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='ChangeMe123!' \
  -n monitoring
```

### 4b. Webhook receiver (pour les démonstrations d'alertes et notifications)

```bash
kubectl run webhook-receiver -n monitoring \
  --image=mendhak/http-https-echo:34 \
  --restart=Never --port=8080 --env="HTTP_PORT=8080"

kubectl expose pod webhook-receiver -n monitoring \
  --port=8080 --name=webhook-receiver
```

Ce pod reçoit les notifications Alertmanager (`/page`, `/ticket`) et Argo Rollouts
(`/rollout/success`, `/rollout/failure`). Consulter ses logs :

```bash
kubectl logs webhook-receiver -n monitoring -f
```

---

## 5. Démarrer la stack via GitOps (App of Apps)

Adaptez l'URL du repo dans `platform-sre/bootstrap/root-app.yaml` si vous avez forké.
Puis appliquez la Root Application — c'est la **seule** commande `kubectl apply` manuelle :

```bash
kubectl apply -f platform-sre/bootstrap/root-app.yaml
```

ArgoCD crée automatiquement toutes les Applications enfant définies dans `platform-sre/apps/` :

| Application ArgoCD | Ce qu'elle déploie | Namespace |
|---|---|---|
| `kube-prometheus-stack` | Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics | `monitoring` |
| `argo-rollouts` | contrôleur Argo Rollouts + dashboard | `argo-rollouts` |
| `annuaire-dev` | service annuaire (Rollout canary) | `devhub-dev` |
| `planning-dev` | service planning (Rollout blue/green) | `devhub-dev` |
| `notif-dev` | service notif (Deployment standard) | `devhub-dev` |

Premier sync : compter 5–10 minutes (téléchargement des charts Helm).

Vérification :

```bash
kubectl get applications -n argocd
# NAME                    SYNC STATUS   HEALTH STATUS
# argo-rollouts           Synced        Healthy
# kube-prometheus-stack   Synced        Healthy
# annuaire-dev            Synced        Healthy
# planning-dev            Synced        Healthy
# notif-dev               Synced        Healthy
# root                    Synced        Healthy
```

---

## 6. Construire et charger les images applicatives

Les services utilisent un registre local kind (port 5001). Adapter le tag selon la version voulue.

```bash
# Construire une image (exemple : annuaire)
docker build -t host.docker.internal:5001/annuaire:tp3-v7 services/annuaire/
docker push host.docker.internal:5001/annuaire:tp3-v7

# Ou utiliser le Makefile (tag = SHA Git courant, registre GHCR)
# GHCR_USER=votre-compte make images-build images-load
```

Mettre à jour le tag dans `services/annuaire/chart/values-dev.yaml` :

```yaml
image:
  tag: tp3-v7
```

Committer et pousser → ArgoCD détecte le commit → rollout démarre automatiquement.

---

## 7. Interfaces web disponibles

| URL | Service | Identifiants |
|---|---|---|
| [http://argocd.devhub.local](http://argocd.devhub.local) | ArgoCD | admin / `make argocd-password` |
| [http://grafana.devhub.local](http://grafana.devhub.local) | Grafana | admin / mot de passe du secret `grafana-admin-secret` |
| [http://prometheus.devhub.local](http://prometheus.devhub.local) | Prometheus UI | aucun |
| [http://rollouts.devhub.local](http://rollouts.devhub.local) | Argo Rollouts dashboard | aucun |
| [http://annuaire.devhub.local](http://annuaire.devhub.local) | Service annuaire | aucun |
| [http://planning.devhub.local](http://planning.devhub.local) | Service planning | aucun |
| [http://notif.devhub.local](http://notif.devhub.local) | Service notif | aucun |

---

## 8. Opérer les rollouts (canary — annuaire)

### Déclencher un rollout

Toute modification du pod template (image, env var) dans `values-dev.yaml` + commit + push déclenche un rollout.

```bash
# Changer le tag image
sed -i 's/tag: tp3-v7/tag: tp3-v8/' services/annuaire/chart/values-dev.yaml
git add services/annuaire/chart/values-dev.yaml
git commit -m "chore: bump annuaire tp3-v8"
git push origin main:tp3
```

### Suivre un rollout en temps réel

```bash
kubectl argo rollouts get rollout annuaire-dev-annuaire -n devhub-dev --watch
```

### Séquence canary (annuaire)

```
setWeight: 10  →  pause (manuelle)  →  setWeight: 25  →  AnalysisRun  →  setWeight: 50  →  pause 30s  →  setWeight: 100
```

### Commandes de pilotage

```bash
# Avancer d'une pause manuelle
kubectl argo rollouts promote annuaire-dev-annuaire -n devhub-dev

# Promouvoir toutes les étapes restantes d'un coup (dangereux en prod)
kubectl argo rollouts promote annuaire-dev-annuaire -n devhub-dev --full

# Annuler — bascule tout le trafic vers le stable
kubectl argo rollouts abort annuaire-dev-annuaire -n devhub-dev

# Vérifier les AnalysisRun
kubectl get analysisrun -n devhub-dev
kubectl describe analysisrun <nom> -n devhub-dev
```

### Header routing (canary uniquement pour les testeurs internes)

```bash
# Version stable (trafic normal)
curl http://annuaire.devhub.local/students

# Version canary (forcer avec le header)
curl -H "X-Beta-User: true" http://annuaire.devhub.local/students
```

---

## 9. Opérer les rollouts (blue/green — planning)

### Séquence blue/green

1. Nouveau déploiement → preview reçoit 100 % des réplicas, active reste inchangé
2. Tester la preview : `curl http://planning-preview.devhub.local/slots`
3. Valider et basculer :

```bash
kubectl argo rollouts promote planning-dev-planning -n devhub-dev
```

4. L'ancienne version reste 5 min (`scaleDownDelaySeconds: 300`) puis disparaît.

### Suivre

```bash
kubectl argo rollouts get rollout planning-dev-planning -n devhub-dev --watch
kubectl get pods -n devhub-dev -l app.kubernetes.io/name=planning
# Pendant la bascule : 2× le nombre normal de pods
```

---

## 10. Tester l'observabilité (Prometheus / Grafana)

### Envoyer du trafic

```bash
# Boucle de trafic sur annuaire (100 req, 3 req/s)
for i in $(seq 1 100); do curl -s http://annuaire.devhub.local/students > /dev/null; sleep 0.3; done
```

### Requêtes PromQL utiles

```promql
# Taux de requêtes (RPS)
sum(rate(http_requests_total{namespace="devhub-dev", service="annuaire-dev-annuaire-stable"}[5m]))

# Taux d'erreur 5xx
sum(rate(http_requests_total{namespace="devhub-dev", service="annuaire-dev-annuaire-stable", status_class="5xx"}[5m]))
/ sum(rate(http_requests_total{namespace="devhub-dev", service="annuaire-dev-annuaire-stable"}[5m]))

# Latence p95
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{namespace="devhub-dev", service="annuaire-dev-annuaire-stable"}[5m]))
  by (le)
)
```

Dashboard préchargé dans Grafana : **Services RED** (provisionnement automatique depuis
`platform-sre/dashboards/services-red.json`).

---

## 11. Déclencher les alertes (tests)

### `AnnuaireHighErrorRate` (severity: page)

L'endpoint `/break` renvoie des 500 au taux `FAIL_RATE`. Pour activer :

```yaml
# services/annuaire/chart/values-dev.yaml
env:
  FAIL_RATE: "0.1"   # 10 % de 5xx sur /break
```

Committer, puis :

```bash
# Générer du trafic avec erreurs
for i in $(seq 1 200); do curl -s http://annuaire.devhub.local/break; sleep 0.3; done
```

L'alerte passe en `firing` après ~1 min. Vérifier dans Prometheus :
[http://prometheus.devhub.local/alerts](http://prometheus.devhub.local/alerts)

Le webhook reçoit `POST /page` dans ~30 s après firing :

```bash
kubectl logs webhook-receiver -n monitoring -f
```

### `AnnuaireHighLatency` (severity: ticket)

Alerte avec `for: 30m` — en pratique, attendre 30 min avec une latence p95 > 300 ms.
La PromQL peut être testée directement dans Prometheus sans attendre le firing.

### Remettre à zéro

```yaml
# services/annuaire/chart/values-dev.yaml
env:
  FAIL_RATE: "0"
```

Committer et pousser.

---

## 12. Tester les notifications Argo Rollouts

Les notifications se déclenchent automatiquement quand un rollout se termine.

| Événement | Trigger | Endpoint |
|---|---|---|
| Rollout promu avec succès | `rollout.status.phase == "Healthy"` | `POST /rollout/success` |
| Rollout annulé / Degraded | `rollout.status.phase == "Degraded"` | `POST /rollout/failure` |

Pour provoquer un échec rapidement :

```bash
# Déclencher un rollout (modifier values-dev.yaml), attendre la pause à 10 %
kubectl argo rollouts abort annuaire-dev-annuaire -n devhub-dev
# → POST /rollout/failure reçu dans les secondes qui suivent
kubectl logs webhook-receiver -n monitoring | grep "/rollout"
```

---

## 13. Valider les règles d'alerte avec promtool

```bash
promtool check rules services/annuaire/chart/templates/prometheusrule.yaml
```

---

## 14. Commandes de diagnostic rapide

```bash
# État de tous les pods
kubectl get pods -n devhub-dev
kubectl get pods -n monitoring
kubectl get pods -n argo-rollouts

# État des rollouts
kubectl argo rollouts list rollouts -n devhub-dev

# ServiceMonitor détecté par Prometheus
# → Status → Targets dans http://prometheus.devhub.local

# Config Alertmanager chargée (vérifier les matchers)
kubectl exec -n monitoring alertmanager-kps-alertmanager-0 -c alertmanager -- \
  wget -qO- http://localhost:9093/api/v2/status | grep -o '"routes":\[.*\]'

# Logs Alertmanager (problèmes de config)
kubectl logs alertmanager-kps-alertmanager-0 -c alertmanager -n monitoring --since=5m

# Alertes actives
kubectl exec -n monitoring alertmanager-kps-alertmanager-0 -c alertmanager -- \
  wget -qO- "http://localhost:9093/api/v2/alerts" | grep -o '"alertname":"[^"]*"'

# Historique d'un rollout
kubectl argo rollouts history rollout annuaire-dev-annuaire -n devhub-dev

# Logs d'un AnalysisRun
kubectl describe analysisrun -n devhub-dev | grep -A5 "Measurements\|Value\|Phase"

# Forcer un re-sync ArgoCD sans attendre le polling
kubectl annotate application annuaire-dev -n argocd \
  argocd.argoproj.io/refresh=hard --overwrite
```

---

## 15. Détruire le cluster

```bash
make cluster-down
# ou
kind delete cluster --name pulse
```

Les données (Prometheus, Grafana, logs) ne sont pas persistées — tout repart de zéro au prochain `make cluster-up`.

---

## Pièges connus

| Symptôme | Cause | Correctif |
|---|---|---|
| Prometheus ne voit pas le service | Label `release: kps` manquant sur le `ServiceMonitor` ou le `Service` | Vérifier `Status → Targets` dans l'UI Prometheus |
| `histogram_quantile` retourne `NaN` | Pas assez de trafic dans la fenêtre temporelle | Envoyer des requêtes en boucle |
| `AnnuaireHighErrorRate` ne fire pas | `/break` n'est pas l'endpoint testé, ou `FAIL_RATE=0` | Utiliser `/break` avec `FAIL_RATE > 0` |
| Alertmanager route vers `null` (blackhole) | Format map pour les `matchers` → parse silencieusement en erreur | Utiliser le format chaîne : `- "severity=\"page\""` |
| Les notifications Argo Rollouts montrent `{{ .rollout.metadata.name }}` littéral | Helm escaping (`{{ "{{" }}`) dans values.yaml — les values ne sont pas des templates | Écrire directement `{{ .rollout.metadata.name }}` sans échappement |
| Rollout reste bloqué à 10 % | Pause manuelle — normal, nécessite `kubectl argo rollouts promote` | Voir section 8 |
| Service canary/stable endpoints vides | Conflict SSA / Argo Rollouts sur `spec.selector` | Vérifier `ignoreDifferences` + `RespectIgnoreDifferences=true` dans l'Application ArgoCD |
| Canary Analysis passe toujours même avec `FAIL_RATE=0.1` | L'analyse query le service canary — si personne ne l'appelle, `rate()=0` → succès | Envoyer du trafic sur l'ingress pendant l'analyse |
| `kubectl argo rollouts` introuvable | Plugin non installé ou pas dans PATH | Voir section Prérequis |
