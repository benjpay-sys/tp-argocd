# RAPPORT — DevHub Campus SRE (TP 3)

Binôme : Benjamin Payen (benjaminpayen59@gmail.com)
Fork : https://github.com/benjpay-sys/tp-argocd.git
Cluster : kind `devhub` (2 nœuds, hérité du TP 2)

---

## Étape 0 — Outillage complémentaire

| Outil | Version constatée | Statut |
|---|---|---|
| docker | 29.0.1 | OK |
| kubectl | (client Docker Desktop) | OK |
| helm | v3.15.2+g1a500d5 | OK |
| kind | v0.22.0 | OK |
| argocd (CLI) | présent | OK |
| kubectl-argo-rollouts | v1.9.0+838d4e7 | OK (installé dans `%USERPROFILE%\.local\bin`, ajouté au PATH utilisateur) |
| promtool | 3.12.0 | OK (installé dans `%USERPROFILE%\.local\bin`, ajouté au PATH utilisateur) |

Le cluster kind `devhub` du TP 2 est réutilisé tel quel (namespaces `argocd`, `devhub-dev`,
`devhub-preview-feature-demo-prof`, `ingress-nginx` déjà présents et `Healthy`). L'AppProject
et la root Application actuelles pointent encore vers l'ancien serveur Git interne du TP 2
(`http://local-git-server.argocd.svc/git/devhub-campus.git`, path `platform/apps`) — elles
seront remplacées en étape 5 par la chaîne pointant sur le fork GitHub
`https://github.com/benjpay-sys/tp-argocd.git`, path `pulse-campus/platform-sre/apps`.

**Action en attente** : installer `kubectl-argo-rollouts` et `promtool` avant l'étape 5. Pas
bloquant pour les étapes 0–1 (conceptuelles).

---

## Étape 1 — SLI, SLO, error budget

### Contexte de criticité par service

- **planning** : service au cœur de l'incident qui a déclenché ce TP (créneaux décalés vus par
  1200 étudiants, healthcheck restés verts). C'est le service où l'écart entre « healthy » et
  « correct » est le plus dangereux → SLO le plus strict.
- **annuaire** : consulté en lecture très fréquemment, mais une erreur ponctuelle a un impact
  limité (un étudiant recharge la page). SLO intermédiaire.
- **notif** : notifications informatives, asynchrones de fait (un retard de quelques minutes
  n'a presque aucun impact perçu). SLO le plus lâche.

### annuaire

| SLI | SLO | Fenêtre | Error budget mensuel |
|---|---|---|---|
| Disponibilité (ratio requêtes non-5xx) | 99,5 % | 30 j glissants | 3h36 |
| Latence p95 | < 300 ms sur 99,5 % des fenêtres de 5 min | 30 j glissants | 3h36 |
| Fraîcheur de déploiement | 95 % des déploiements visibles dans le cluster en moins de 5 min après le commit `image.tag` | event-based (par déploiement) | non exprimable en minutes — *budget événementiel* : 1 déploiement en retard tolérable sur 20 par mois (cf. note ci-dessous) |

Justification des seuils : 99,5 % (et non 99,99 %) parce que l'annuaire n'est pas dans le
chemin critique d'un cours qui démarre — un budget trop strict serait épuisé en permanence pour
un service à faible enjeu, ce qui le rendrait inutile comme signal de pilotage. Le seuil p95 à
300 ms est choisi parce que c'est une API CRUD en mémoire, sans I/O externe : au-delà de 300 ms
sans dépendance externe, quelque chose d'anormal se passe (CPU throttling, GC, etc.).

Note sur la 3ᵉ SLI : c'est un **SLO event-based** (cf. défi bonus étape 1) — chaque déploiement
est un événement discret « à l'heure » ou « en retard », pas une proportion de temps. Exprimer
un budget en minutes n'aurait pas de sens ici contrairement aux deux premières SLI qui sont
time-based.

```promql
# Disponibilité (annuaire)
sum(rate(http_requests_total{service="annuaire", status_class!~"5.."}[5m]))
/
sum(rate(http_requests_total{service="annuaire"}[5m]))

# Latence p95 (annuaire)
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket{service="annuaire"}[5m])) by (le)
)

# Fraîcheur de déploiement (annuaire) — âge du build actif
time() - max(process_start_time_seconds{job="annuaire"})
```

### planning

| SLI | SLO | Fenêtre | Error budget mensuel |
|---|---|---|---|
| Disponibilité (ratio requêtes non-5xx) | 99,9 % | 30 j glissants | 43 min |
| Latence p95 | < 300 ms sur 99,9 % des fenêtres de 5 min | 30 j glissants | 43 min |
| Cohérence de version pendant un déploiement | les pods actifs n'exposent pas plus de 2 versions distinctes de `planning_build_info` pendant plus de 10 min consécutives | event-based (par déploiement) | 0 dépassement toléré par déploiement (alerte immédiate si dépassé) |

Justification : c'est le service de l'incident fondateur. Le risque réel n'était pas un 5xx —
les pods répondaient 200 OK avec de mauvaises données. La disponibilité/latence ne suffisent
donc pas : la 3ᵉ SLI capture spécifiquement le symptôme de l'incident (un rollout qui reste
« coincé » entre deux versions plus longtemps que prévu est le signal qu'une release est en train
de mal se propager). Seuil de dispo à 99,9 % (et non 99,5 % comme annuaire) parce qu'un
planning faux a un coût pédagogique direct (un enseignant ou un étudiant rate un cours).

```promql
# Disponibilité (planning)
sum(rate(http_requests_total{service="planning", status_class!~"5.."}[5m]))
/
sum(rate(http_requests_total{service="planning"}[5m]))

# Latence p95 (planning)
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket{service="planning"}[5m])) by (le)
)

# Cohérence de version (planning) — nombre de versions distinctes actives
count(count by (version) (planning_build_info))
```

### notif

| SLI | SLO | Fenêtre | Error budget mensuel |
|---|---|---|---|
| Disponibilité (ratio requêtes non-5xx) | 99 % | 30 j glissants | 7h12 |
| Latence p95 | < 500 ms sur 99 % des fenêtres de 5 min | 30 j glissants | 7h12 |
| Débit d'événements métier | au moins 1 `business_event_total` émis par fenêtre de 15 min en heures ouvrées (signal anti-silence) | 30 j glissants, heures ouvrées | 7h12 (équivalent) |

Justification : notif est asynchrone par nature (l'utilisateur ne regarde pas une notification
en temps réel comme il consulte son planning) → SLO le plus lâche du lot. La 3ᵉ SLI n'est pas
une garantie de qualité mais un garde-fou anti-silence : un service notif qui répond 200 OK sur
`/healthz` mais ne pousse plus aucun événement métier est un mode de panne silencieux classique
(file de traitement vide, worker bloqué) que la dispo seule ne détecte jamais.

```promql
# Disponibilité (notif)
sum(rate(http_requests_total{service="notif", status_class!~"5.."}[5m]))
/
sum(rate(http_requests_total{service="notif"}[5m]))

# Latence p95 (notif)
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket{service="notif"}[5m])) by (le)
)

# Débit d'événements métier (notif)
sum(increase(business_event_total{service="notif"}[15m]))
```

### Question de synthèse (à restituer à voix haute)

> Pour `planning`, l'error budget est de 43 minutes par mois. Si on l'épuise en deux semaines
> (donc deux fois plus vite que prévu), je :
> 1. gèle les déploiements non critiques sur `planning` jusqu'à la fin du mois (error budget
>    policy) ;
> 2. ouvre un post-mortem pour identifier la cause de la consommation anormale (un seul incident
>    long, ou une dérive lente type fuite mémoire) ;
> 3. ne déploie plus qu'en canary avec `pause: {}` manuel tant que le budget n'est pas reconstitué,
>    même si l'AnalysisTemplate est positif — le SRE garde la main tant que la confiance n'est
>    pas restaurée.

---

---

## Étape 2 — Instrumentation Prometheus : buckets

Aucune ligne de code applicatif modifiée (conforme à la consigne du TP). Le travail consiste à
choisir les buckets d'histogramme par service, dans `chart/values.yaml`, en fonction des SLO de
l'étape 1.

| Service | SLO p95 | Buckets choisis | Commentaire |
|---|---|---|---|
| annuaire | < 300 ms | `0.05,0.1,0.2,0.3,0.5,1,2,5` | valeur par défaut du squelette — déjà alignée : un point exactement à `0.3` (le seuil SLO) et des points encadrants à `0.2`/`0.5` pour que `histogram_quantile` interpole correctement autour du seuil. |
| planning | < 300 ms | `0.05,0.1,0.2,0.3,0.5,1,2,5` | même raisonnement qu'annuaire — même seuil SLO. |
| notif | < 500 ms | `0.05,0.1,0.2,0.3,0.5,1,2,5` | seuil SLO à `0.5`, déjà présent dans la liste par défaut ; conservé tel quel plutôt que d'inventer une distribution différente sans donnée réelle de trafic. |

Les trois services partagent la même liste par défaut du squelette, et il se trouve qu'elle
couvre exactement les deux seuils SLO retenus (300 ms et 500 ms) — aucune valeur n'a donc été
modifiée dans `values.yaml`. C'est documenté ici plutôt que silencieusement laissé tel quel, pour
que le choix soit traçable : une progression uniforme aurait été rejetée (piège du poly), celle-ci
est volontairement quasi-logarithmique.

`metrics.businessEnabled` reste à `false` partout (défi bonus non traité — pas nécessaire pour
la suite du TP).

### Validation (faite en local via `docker run`, hors cluster)

```
docker build -t local/annuaire:tp3 services/annuaire
docker run -d -p 18081:8080 -e METRICS_BUCKETS="0.05,0.1,0.2,0.3,0.5,1,2,5" local/annuaire:tp3
curl -s http://localhost:18081/metrics | promtool check metrics
```

Résultats :
- **annuaire** : `curl /metrics` renvoie bien les `http_request_duration_seconds_bucket{le="0.3", ...}`
  attendus. `promtool check metrics` ne signale qu'un avertissement (exit 3, pas une erreur de
  format) sur les métriques par défaut de `prom-client` (`nodejs_active_handles_total`,
  `nodejs_active_requests_total`, `nodejs_active_resources_total` — des gauges nommées en
  `_total` par la bibliothèque elle-même, hors de notre code applicatif, donc hors périmètre du
  TP qui interdit de modifier le code).
- **planning** : `curl /metrics` conforme, `promtool check metrics` ne signale rien (FastAPI +
  `prometheus_client` n'a pas ce défaut de nommage).
- **notif** : idem, `promtool check metrics` clean.

Les trois services exposent bien `http_requests_total`, `http_request_duration_seconds_bucket`
(avec les buckets configurés), `<service>_build_info`, et `business_event_total` (à 0, puisque
désactivé) — conforme à la convention RED documentée dans le poly.

---

## Étape 3 — kube-prometheus-stack via ArgoCD

Chart installé : `prometheus-community/kube-prometheus-stack` version **65.5.0**, releaseName `kps`.

Fichiers GitOps produits :
- `platform-sre/apps/observability/kube-prometheus-stack.yaml` — Application ArgoCD
- `platform-sre/values/kube-prometheus-stack-values.yaml` — values du chart

Choix opérationnels :

| Sous-composant | Activé | Raison |
|---|---|---|
| Prometheus Operator | ✓ | requis |
| Prometheus | ✓ | requis |
| Alertmanager | ✓ | requis |
| Grafana | ✓ | requis |
| node-exporter | ✓ | métriques infra nœud |
| kube-state-metrics | ✓ | métriques objets K8s |
| admissionWebhooks | ✗ | kind ne supporte pas les webhooks TLS sans cert-manager |
| kubeControllerManager / kubeScheduler / kubeEtcd | ✗ | kind n'expose pas la control-plane sur les ports attendus |

Ajustement critique pour kind : `prometheusOperator.tls.enabled: false` — sans ça, l'opérateur
cherche un secret `kps-admission` jamais créé (puisque le job patch admission webhook est désactivé)
et reste en `ContainerCreating` indéfiniment.

Le mot de passe Grafana est **hors Git** : un `Secret` Kubernetes `grafana-admin-secret` a été
créé manuellement dans le namespace `monitoring` ; le chart le référence via
`grafana.admin.existingSecret`. Aucun mot de passe en clair dans les fichiers versionné.

Prometheus est configuré avec `serviceMonitorSelectorNilUsesHelmValues: false` et un
`serviceMonitorSelector.matchLabels.release: kps` pour découvrir les ServiceMonitors dans
n'importe quel namespace du cluster (pas uniquement dans `monitoring`).

**Validation** : tous les pods `monitoring` sont `Running` ; l'UI Prometheus répond sur
`http://prometheus.devhub.local` ; Grafana répond sur `http://grafana.devhub.local` ;
`Status → Targets` montre `kube-state-metrics`, `node-exporter` et l'API K8s comme cibles `UP`.

---

## Étape 4 — ServiceMonitor + dashboard Grafana

### ServiceMonitor

Un template `chart/templates/servicemonitor.yaml` a été ajouté dans les trois charts (annuaire,
planning, notif). Il est conditionnel (`monitoring.enabled: true` dans `values-dev.yaml`).

Mécanisme de découverte : le Service K8s se voit ajouter le label `release: kps` quand
`monitoring.enabled` est vrai. Le `serviceMonitorSelector` du chart kube-prometheus-stack filtre
sur ce label. C'est le point le plus souvent oublié (piège documenté dans l'annexe B du poly).

Les trois ServiceMonitors apparaissent dans `Status → Targets` de Prometheus avec `UP=1`.

### PromQL des 4 panneaux du dashboard `services-red.json`

**Panneau 1 — Request Rate (RPS)**
```promql
sum(rate(http_requests_total{namespace="$namespace", job="$service"}[5m])) by (route, status_class)
```
Donne le débit entrant par route et classe de statut. Sert le SLI disponibilité : si le compteur
de 2xx s'effondre, l'error rate monte.

**Panneau 2 — Error Rate (ratio 5xx)**
```promql
sum(rate(http_requests_total{namespace="$namespace", job="$service", status_class="5xx"}[5m]))
/
sum(rate(http_requests_total{namespace="$namespace", job="$service"}[5m]))
```
Ratio directement comparable au SLO de disponibilité. Seuil de couleur à 1 % (rouge au-delà).

**Panneau 3 — Latence p50/p95/p99**
```promql
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{namespace="$namespace", job="$service"}[5m])) by (le)
)
```
Le `sum(...) by (le)` est indispensable pour agréger les instances avant le calcul du quantile
— sans lui on obtient un quantile par pod, illisible et non représentatif du SLI service.
Le panneau trace aussi p50 et p99 pour le contexte (p50 indique la médiane, p99 les outliers).

**Panneau 4 — Build Info (version active)**
```promql
max by (version, commit, language) (annuaire_build_info{namespace="$namespace"})
or max by (version, commit, language) (planning_build_info{namespace="$namespace"})
or max by (version, commit, language) (notif_build_info{namespace="$namespace"})
```
Gauge constante = 1 ; la valeur importe peu, ce sont les labels qui portent l'information
(`version`, `commit`, `language`). Afficher ce panneau dans le dashboard permet de savoir
immédiatement quel tag d'image est actif sans quitter Grafana.

Dashboard exporté : `platform-sre/dashboards/services-red.json`

---

## Étape 5 — Du Deployment au Rollout (annuaire, canary)

**Argo Rollouts** est installé via l'Application ArgoCD `platform-sre/apps/observability/argo-rollouts.yaml`
(chart `argo/argo-rollouts`, namespace `argo-rollouts`).

Le chart `annuaire` a été modifié :
- `rollout.yaml` remplace `deployment.yaml` (`{{- if not .Values.useDeployment }}` ; le Deployment ne
  s'affiche plus quand `useDeployment: false`)
- `service.yaml` devient conditionnel (`{{- if .Values.useDeployment }}`) pour éviter la coexistence
- `service-stable.yaml` + `service-canary.yaml` créés pour le split de trafic
- `ingress.yaml` pointe vers `<fullname>-stable` quand `useDeployment: false`
- `values-dev.yaml` : `useDeployment: false`

Stratégie canary étape 5 (test) : `setWeight:20 → pause:30s → setWeight:50 → pause:30s → setWeight:100`.

**Validation observée** : le canary `tp3-v2` a passé successivement 20 %, 50 % (pauses automatiques),
puis 100 % ; `kubectl argo rollouts get rollout` a montré à chaque étape le poids actuel et le status
`Paused → Healthy`. L'ancienne revision (v1) a été scale-down après la promotion.

**Piège évité** : après le premier sync, le Deployment ET le Rollout coexistaient (`prune: false` dans
la syncPolicy ArgoCD). Le Deployment orphelin a été supprimé manuellement (`kubectl delete deployment`)
— cas documenté dans l'Annexe B du poly.

---

## Étape 6 — Pilotage manuel du canary (pause/promote/abort)

Étapes du Rollout pour le pilotage manuel :
```
setWeight: 10 → pause: {} (infini) → setWeight: 50 → pause: {duration: 1m} → setWeight: 100
```

### Scénario 1 — Promotion normale

```
kubectl argo rollouts get rollout annuaire-dev-annuaire -n devhub-dev
# → Status: Paused, Step 1/5, SetWeight: 10 (canary tp3-v3)

kubectl argo rollouts promote annuaire-dev-annuaire -n devhub-dev
# → rollout promoted — passe à Step 3/5, SetWeight: 50, pause 1m, puis Healthy à 100%
```

**Observation** : la commande `promote` avance le Rollout d'une étape de pause manuelle à la fois ;
le Rollout attend automatiquement la pause temporisée de 1 min avant de passer à 100 %.

### Scénario 2 — Annulation explicite (abort)

```
kubectl argo rollouts get rollout annuaire-dev-annuaire -n devhub-dev
# → Status: Paused, Step 1/5, SetWeight: 10 (canary tp3-v4)

kubectl argo rollouts abort annuaire-dev-annuaire -n devhub-dev
# → rollout aborted — Status: Degraded, SetWeight: 0, tout le trafic sur stable (tp3-v3)
```

**Observation** : le poids canary descend immédiatement à 0, le pod canary reste en vie mais ne reçoit
plus de trafic (via ingress-nginx). Le Rollout est en état `Degraded` car Git pointe toujours vers
`tp3-v4`. Pour réaligner : `git revert HEAD + push` → ArgoCD sync → `kubectl argo rollouts retry rollout`.

### Scénario 3 — Promotion forcée (`--full`)

```
kubectl argo rollouts get rollout annuaire-dev-annuaire -n devhub-dev
# → Status: Paused, Step 1/5, SetWeight: 10 (canary tp3-v5)

kubectl argo rollouts promote annuaire-dev-annuaire -n devhub-dev --full
# → rollout fully promoted — toutes les étapes sautées, Status: Healthy à 100% immédiatement
```

**Quand `promote --full` est acceptable en production ?**
C'est justifié en cas d'urgence réelle : un incident de production en cours, une régression avérée
sur la version stable qui nécessite que la nouvelle version prenne le trafic immédiatement (ex.
correctif de sécurité). Les précautions : (1) documenter la décision dans le canal d'astreinte pour
traçabilité, (2) surveiller activement les métriques les 5 minutes suivantes, (3) ne jamais l'utiliser
pour « gagner du temps » sur un déploiement normal — la valeur du canary est précisément d'observer
sous trafic partiel.

---

## Étape 7 — AnalysisTemplate : promotion sur preuve (annuaire)

L'`AnalysisTemplate` `annuaire-dev-annuaire-sre` interroge Prometheus toutes les 30 s pendant 5 min
(10 mesures, `failureLimit: 1`). Deux métriques :

**Taux d'erreur (canary)**
```promql
sum(rate(http_requests_total{
  namespace="devhub-dev", service="annuaire-dev-annuaire-canary", status_class="5xx"
}[2m]))
/
(sum(rate(http_requests_total{
  namespace="devhub-dev", service="annuaire-dev-annuaire-canary"
}[2m])) > 0)
or vector(0)
```
`successCondition: result[0] == 0 || result[0] < 0.01` — seuil 1 %.
Le `or vector(0)` évite le `NaN` quand il n'y a pas encore de trafic.

**Latence p95 (canary)**
```promql
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{
    namespace="devhub-dev", service="annuaire-dev-annuaire-canary"
  }[2m])) by (le)
)
```
`successCondition: isNaN(result[0]) || result[0] < 0.3` — seuil SLO 300 ms.

Le label `service` filtre spécifiquement le service canary (distinct du stable dans Prometheus grâce
aux deux ServiceMonitor endpoints). L'Analysis est placée en step 4 entre `setWeight:25` et `setWeight:50`.

**Résultat observé** — AnalysisRun `…-7-3` : Successful (latency-p95=0.047 s, error-rate=0).
Promotion automatique vers `tp3-v6` sans intervention humaine.

**Choix des seuils et durée** : 1 % d'erreur et p95 < 300 ms correspondent aux SLOs définis en
étape 1. La durée de 5 min (10 × 30 s) est un compromis : assez long pour filtrer les pics
transitoires, assez court pour ne pas ralentir inutilement le pipeline. Sur du trafic réel plus
soutenu, on pourrait descendre à 3 min.

---

## Étape 8 — Blue/Green : planning

### Stratégie et architecture

Le service `planning` est migré en **BlueGreen** :
- `service-active.yaml` (avec label `release: kps` pour le scraping) = trafic production
- `service-preview.yaml` = nouvelle version avant bascule
- `ingress-preview.yaml` → `planning-preview.devhub.local` (accès interne équipe)
- `ingress.yaml` → `<fullname>-active` quand `useDeployment: false`
- `autoPromotionEnabled: false` → bascule toujours manuelle
- `scaleDownDelaySeconds: 300` → ancienne version garde ses pods 5 min après bascule
- `prePromotionAnalysis` : même AnalysisTemplate que canary (error-rate + latency-p95),
  interroge `service="{{ fullname }}-preview"`, 4 mesures × 30 s = 2 min

### Piège ArgoCD SSA + Argo Rollouts

Argo Rollouts injecte le label `rollout-pod-template-hash=<hash>` dans les sélecteurs des services
active et preview pour les différencier. Avec `ServerSideApply=true` dans ArgoCD, le champ
`spec.selector` est possédé par `argocd-controller`, ce qui empêche `rollouts-controller` de le modifier.

**Conséquence** : sans le hash, les deux services routaient vers TOUS les pods — le contrôleur ne
voyait jamais de transition stable→preview et traitait chaque déploiement comme un « Initial deploy »,
bypassing l'analysis et auto-promouvant immédiatement.

**Fix** : `ignoreDifferences` + `RespectIgnoreDifferences=true` dans l'Application ArgoCD :

```yaml
ignoreDifferences:
  - group: ""
    kind: Service
    name: planning-dev-planning-active
    namespace: devhub-dev
    jsonPointers:
      - /spec/selector
  - group: ""
    kind: Service
    name: planning-dev-planning-preview
    namespace: devhub-dev
    jsonPointers:
      - /spec/selector
syncOptions:
  - RespectIgnoreDifferences=true
```

### Démonstration bascule manuelle (tp3-v5)

**État avant promote** :
```
Status: Paused (BlueGreenPause)
tp3-v4 (stable, active)
tp3-v5 (preview)
AnalysisRun planning-dev-planning-79f588b48c-5-pre: Successful (8 mesures)
```

```bash
# Validation preview avant bascule
curl http://planning-preview.devhub.local/readyz
# → 200 OK {"ok":true,"service":"planning"}

# Bascule manuelle
kubectl argo rollouts promote planning-dev-planning -n devhub-dev
# → rollout 'planning-dev-planning' promoted
```

**État après promote** :
```
Status: Healthy
tp3-v5 (stable, active)
tp3-v4 (delay:4m48s → ScaledDown après 300 s)
```

### Comparatif Canary vs BlueGreen

| Critère | Canary | BlueGreen |
|---|---|---|
| Exposition au risque | Fraction du trafic (5–20 %) | 0 % pendant le test (preview isolé) |
| Ressources | Normale + quelques pods canary | Double capacité pendant la bascule |
| Rollback | Trafic redescend vers stable | Ancienne version encore active 5 min |
| Validation | Métriques sur trafic réel | Test interne sur preview |
| Cas d'usage | Services stateless à fort volume | Services critiques, migrations lourdes |

**BlueGreen plutôt que canary quand** : (1) le service a un état partagé (DB schema, sessions) que
deux versions simultanées ne peuvent pas gérer ; (2) on veut une validation QA complète sur la
nouvelle version avant d'exposer le moindre utilisateur réel.

---

## Étape 9 — Routage avancé par header (X-Beta-User)

### Objectif et mécanisme

Envoyer une fraction du trafic vers la version canary non plus aléatoirement (selon le `setWeight`)
mais sur un critère déterministe : un header HTTP `X-Beta-User: true`. Cela permet à l'équipe produit
de tester chaque release sur ses propres comptes avant n'importe quel utilisateur réel.

Mécanisme nginx-ingress : les trois annotations `canary`, `canary-by-header`, `canary-by-header-value`
sur l'Ingress canary font que **le header gagne sur le poids** — une requête portant le header est
toujours envoyée au canary, quelle que soit la valeur de `setWeight`.

### Implémentation

Ajout dans `services/annuaire/chart/templates/rollout.yaml` :

```yaml
trafficRouting:
  nginx:
    stableIngress: {{ include "annuaire.fullname" . }}
    {{- if .Values.rollout.canary.headerRouting.enabled }}
    additionalIngressAnnotations:
      nginx.ingress.kubernetes.io/canary-by-header: {{ .Values.rollout.canary.headerRouting.header | quote }}
      nginx.ingress.kubernetes.io/canary-by-header-value: {{ .Values.rollout.canary.headerRouting.headerValue | quote }}
    {{- end }}
```

Valeurs par défaut dans `values.yaml` :

```yaml
rollout:
  canary:
    headerRouting:
      enabled: false
      header: X-Beta-User
      headerValue: "true"
```

Activé dans `values-dev.yaml` :

```yaml
rollout:
  canary:
    headerRouting:
      enabled: true
```

Argo Rollouts injecte ces annotations dans l'Ingress canary qu'il gère automatiquement. Le résultat
observé sur le cluster :

```
kubectl get ingress annuaire-dev-annuaire-annuaire-dev-annuaire-canary -n devhub-dev -o yaml | grep canary
# nginx.ingress.kubernetes.io/canary: "true"
# nginx.ingress.kubernetes.io/canary-by-header: X-Beta-User
# nginx.ingress.kubernetes.io/canary-by-header-value: "true"
# nginx.ingress.kubernetes.io/canary-weight: "10"
```

### Correction préalable : SSA field ownership

La démo n'était pas fonctionnelle au premier essai car `ServerSideApply=true` dans l'Application ArgoCD
`annuaire-dev` avait donné à `argocd-controller` la propriété de `spec.selector` sur les services
canary/stable. Argo Rollouts ne pouvait donc pas injecter `rollouts-pod-template-hash` → les deux
services pointaient vers tous les pods → pas de split de trafic.

Même fix que pour planning (étape 8) :

```yaml
# platform-sre/apps/dev/annuaire.yaml
ignoreDifferences:
  - group: ""
    kind: Service
    name: annuaire-dev-annuaire-canary
    namespace: devhub-dev
    jsonPointers:
      - /spec/selector
  - group: ""
    kind: Service
    name: annuaire-dev-annuaire-stable
    namespace: devhub-dev
    jsonPointers:
      - /spec/selector
syncOptions:
  - RespectIgnoreDifferences=true
```

Après ce fix, les endpoints sont correctement séparés :

```
annuaire-dev-annuaire-canary  ENDPOINTS: 10.244.1.27:8080         (1 pod canary)
annuaire-dev-annuaire-stable  ENDPOINTS: 10.244.1.14:8080,10.244.1.23:8080  (2 pods stable)
```

### Démonstration du routage

Rollout en état Paused (step 1/7, setWeight: 10) — canary = tp3-v7, stable = tp3-v6.
Identification de la version via le label `commit` de la métrique `annuaire_build_info`.

**Sans header (trafic poids-aléatoire, ~10 % canary) :**

```bash
curl -s http://annuaire.devhub.local/metrics | grep build_info
# annuaire_build_info{version="0.2.0",commit="tp3-v6",language="nodejs"} 1  (stable)
# (sur 10 requêtes, ~9 arrivent sur stable, ~1 sur canary)
```

**Avec `X-Beta-User: true` (100 % canary) :**

```bash
curl -s -H "X-Beta-User: true" http://annuaire.devhub.local/metrics | grep build_info
# annuaire_build_info{version="0.2.0",commit="tp3-v7",language="nodejs"} 1  (canary)
# 5/5 requêtes → tp3-v7 (canary), quel que soit le setWeight
```

### Usage métier

Cette technique permettrait à l'équipe produit de tester chaque release sur leurs propres comptes
avant n'importe quel utilisateur. Le workflow serait :

1. Le développeur pousse un tag → ArgoCD déclenche le canary à 10 %
2. L'équipe produit accède via son client HTTP/browser en forçant `X-Beta-User: true`
3. Si validé → `kubectl argo rollouts promote` pour avancer
4. L'AnalysisTemplate prend le relai à l'étape 25 % pour la validation automatisée

Combiné à `AnalysisTemplate`, le header permet une **double validation** : prévisualisation humaine
ciblée + métriques automatisées sur le trafic réel.

---
