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

## Étape 10 — Alerting Alertmanager et notifications Rollouts

### PrometheusRules déployées

Deux règles dans `services/annuaire/chart/templates/prometheusrule.yaml` (label `release: kps`
pour que le Prometheus Operator les sélectionne) :

| Alerte | Condition | `for` | Severity | Receiver |
|---|---|---|---|---|
| `AnnuaireHighErrorRate` | taux 5xx > 1 % sur la série `[5m]` | 1 m (démo) / 5 m (prod) | `page` | `webhook-page` |
| `AnnuaireHighLatency` | latence p95 > 300 ms sur `[5m]` | 30 m | `ticket` | `webhook-ticket` |

Le seuil `for: 1m` est volontairement court pour la démo ; en production on utilise `for: 5m` pour
éviter qu'un pic transitoire réveille l'astreinte.

PromQL de `AnnuaireHighErrorRate` :

```promql
(
  sum(rate(http_requests_total{
    namespace="devhub-dev",
    service="annuaire-dev-annuaire-stable",
    status_class="5xx"
  }[5m]))
  /
  sum(rate(http_requests_total{
    namespace="devhub-dev",
    service="annuaire-dev-annuaire-stable"
  }[5m]))
) > 0.01
```

PromQL de `AnnuaireHighLatency` :

```promql
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{
    namespace="devhub-dev",
    service="annuaire-dev-annuaire-stable"
  }[5m])) by (le)
) > 0.3
```

### Configuration Alertmanager

Fichier : `platform-sre/values/kube-prometheus-stack-values.yaml`, section `alertmanager.config`.

Points importants :
- **Format des matchers** : Alertmanager 0.27.0 avec Prometheus Operator attend la syntaxe
  chaîne (`- "severity=\"page\""`) et non le format map. Le format map provoque une erreur
  `yaml: unmarshal errors: cannot unmarshal !!map into string` et Alertmanager repasse en
  configuration par défaut silencieusement. Ce bug coûte du temps si on ne vérifie pas le status
  via `kubectl get alertmanager -n monitoring -o yaml`.
- **inhibit_rules** : une alerte `severity: page` inhibe `severity: ticket` sur le même service.
  Évite le double bruit quand le service est déjà paginé.
- **repeat_interval** : 1 h pour `page`, 12 h pour `ticket`. Sans ce réglage, Alertmanager
  renvoie toutes les 4 h par défaut (peut saturer en cours de démo).

```yaml
route:
  routes:
    - matchers:
        - "severity=\"page\""
      receiver: webhook-page
      group_wait: 10s
      repeat_interval: 1h
    - matchers:
        - "severity=\"ticket\""
      receiver: webhook-ticket
      group_wait: 1m
      repeat_interval: 12h
```

### Récepteurs in-cluster

En TP, les trois récepteurs sont le pod `webhook-receiver` (image `mendhak/http-https-echo:34`)
déployé impérativement dans `monitoring` pour que l'URL interne soit stable :

```
kubectl run webhook-receiver -n monitoring --image=mendhak/http-https-echo:34 \
  --restart=Never --port=8080 --env="HTTP_PORT=8080"
kubectl expose pod webhook-receiver -n monitoring --port=8080 --name=webhook-receiver
```

En production on remplacerait par un vrai receiver Slack/PagerDuty/Opsgenie.

### Démonstration — alerte `page` déclenchée

Génération de trafic sur l'endpoint `/break` (FAIL_RATE=0.1 → ~10 % de 5xx) :

```bash
# ~200 requêtes à 3 req/s → AnnuaireHighErrorRate passe en firing après ~1 min
for i in $(seq 1 200); do curl -s http://annuaire.devhub.local/break; sleep 0.3; done
```

Vérification via l'API Alertmanager :

```
GET /api/v2/alerts?filter=alertname="AnnuaireHighErrorRate"
→ status.state: "active", receivers: [{"name":"webhook-page"}]
```

Payload reçu par `webhook-receiver` (POST /page, Alertmanager/0.27.0) :

```json
{
  "commonLabels": {
    "alertname": "AnnuaireHighErrorRate",
    "severity": "page",
    "service": "annuaire"
  },
  "commonAnnotations": {
    "description": "Le taux de réponses 5xx sur annuaire dépasse 1 % depuis 5 minutes (valeur actuelle : 1.21%).",
    "summary": "Annuaire : taux d'erreur > 1 %"
  }
}
```

### Notifications Argo Rollouts

Fichier : `platform-sre/values/argo-rollouts-values.yaml`, section `notifications`.

**Piège de templating** : les valeurs dans un fichier `values.yaml` ne sont PAS traitées comme des
templates Helm. Écrire `{{ "{{" }} .rollout.metadata.name {{ "}}" }}` en values produit la chaîne
littérale `{{ "{{" }} .rollout.metadata.name {{ "}}" }}` dans le ConfigMap — pas `{{ .rollout.metadata.name }}`.
Il faut écrire directement `{{ .rollout.metadata.name }}` sans échappement Helm, car les values sont
injectées comme chaînes opaques dans le template du chart.

**Rollout promu** (FAIL_RATE=0, révision 10) — POST /rollout/success :

```json
{
  "event": "Promoted",
  "rollout": "annuaire-dev-annuaire",
  "namespace": "devhub-dev",
  "stable": "fd6787c9b",
  "phase": "Healthy"
}
```

**Rollout aborté** (révision 12, `kubectl argo rollouts abort`) — POST /rollout/failure :

```json
{
  "event": "Aborted",
  "rollout": "annuaire-dev-annuaire",
  "namespace": "devhub-dev",
  "message": "RolloutAborted: Rollout aborted update to revision 12"
}
```

### Récapitulatif des trois cas

| Cas | Déclencheur | Receiver | URL |
|---|---|---|---|
| Alerte `page` | `AnnuaireHighErrorRate` firing depuis 1 min | `webhook-page` | `/page` |
| Alerte `ticket` | `AnnuaireHighLatency` firing depuis 30 min | `webhook-ticket` | `/ticket` |
| Rollout promu | `rollout.status.phase == "Healthy"` | `rollout-success` | `/rollout/success` |
| Rollout aborté | `rollout.status.phase == "Degraded"` | `rollout-failure` | `/rollout/failure` |

L'alerte `ticket` n'a pas été déclenchée en démo (le `for: 30m` est rédhibitoire en TP) : la
PromQL est validée dans l'UI Prometheus, et la configuration Alertmanager correctement routée
(`severity="ticket"` → `webhook-ticket`).

### Gradation page / ticket — justification

Réveil à 3 h du matin pour un `severity: ticket` signifie que toutes les alertes sonnent en
permanence, et que l'on cesse de les lire. La distinction `page` (actionnable immédiatement,
service dégradé pour les utilisateurs) vs `ticket` (dégradation lente, peut attendre l'ouverture
du bureau) est ce qui rend l'oncall soutenable. Un seul niveau de sévérité transforme l'oncall
en bruit de fond.

---

## Étape 11 — Comparatif RollingUpdate natif / Argo Rollouts / Flagger

Note de notation : 0 = inutilisable, 3 = acceptable, 5 = excellent.

| Critère | RollingUpdate natif | Argo Rollouts | Flagger |
|---|---|---|---|
| **Courbe d'apprentissage** | **5** — rien à apprendre, intégré à K8s | **3** — une CRD `Rollout`, une UI, des subtilités (SSA, ignoreDifferences) | **3** — config plus compacte, mais moins de documentation française, moins d'exemples accessibles |
| **Intégration ArgoCD** | **5** — natif, ArgoCD gère les Deployment sans configuration | **4** — native, mais nécessite `ignoreDifferences` + `RespectIgnoreDifferences` pour le split de traffic (field ownership conflict avec SSA) | **2** — conçu pour Flux ; avec ArgoCD il faut des workarounds pour que ArgoCD ne réconcilie pas les poids que Flagger ajuste |
| **Intégration Flux** | **5** — natif | **2** — Argo Rollouts est pensé ArgoCD ; ça fonctionne mais sans UI dédiée | **5** — conçu pour Flux, intégration native et bien documentée |
| **Variété des stratégies** | **2** — RollingUpdate et Recreate uniquement | **5** — canary, blue/green, A/B (header/cookie), experiment, shadow (via webhook) | **4** — canary, A/B, blue/green ; pas d'experiment multi-variante native |
| **Variété des metric providers** | **0** — aucun metric provider | **5** — Prometheus, Datadog, NewRelic, CloudWatch, Wavefront, web hook custom | **4** — Prometheus, Datadog, NewRelic, CloudWatch ; pas de web hook custom natif |
| **UI / dashboard** | **0** — rien (kubectl uniquement) | **5** — dashboard web dédié, intégré à l'UI ArgoCD, vue temps réel des poids et AnalysisRun | **1** — pas d'UI dédiée ; on lit les CustomResources via kubectl |
| **Coût opérationnel** | **1** — zéro contrôleur supplémentaire, mais zéro sécurité | **3** — un contrôleur, des CRDs, de la config par service | **3** — un contrôleur, de la config par service ; légèrement plus compact |
| **Adapté à un mesh (Linkerd, Istio)** | **2** — possible via VirtualService Istio, mais pas natif | **4** — plugin traffic routing pour Istio, Linkerd, Traefik, SMI | **5** — conçu avec Istio/Linkerd en tête ; le traffic split L7 est la feature primaire |
| **Communauté / fréquence de release** | **5** — K8s upstream | **4** — CNCF Graduated, release ~tous les 2 mois, communauté active | **4** — CNCF Graduated (sous Flux), release régulière ; communauté plus petite qu'Argo |
| **Risque si le contrôleur tombe** | **5** — aucun contrôleur | **2** — si le contrôleur est down pendant un canary, le rollout reste bloqué à son poids actuel indéfiniment (pas de failsafe automatique) | **3** — si le contrôleur tombe, Flagger laisse le trafic à la dernière position connue et alertes sur `canary.status.failedChecks` |

### Points à défendre

**RollingUpdate natif (score = 1 sur les métriques) :** suffisant pour une petite équipe avec peu
de trafic, sans SLO exigeant, et sans besoin de rollback automatique. Le coût d'exploitation
est nul. Pour un service interne peu critique, Argo Rollouts n'est pas justifié.

**Argo Rollouts vs Flagger :** Argo Rollouts gagne sur l'UI, la maturité de la documentation
française, et l'intégration ArgoCD. Flagger gagne sur les service meshes et l'intégration Flux.
Si demain on bascule vers Flux ou qu'on installe Istio, Flagger devient le meilleur choix.

**Deux opérations où le surcoût TP 3 n'est pas justifié pour une startup de 3 personnes :**
1. **Rollback** : `git revert + ArgoCD sync` (TP 2) revient en 2 minutes. Pour un service avec
   peu de trafic, le coût d'un rollback tardif est accepteble par rapport à la complexité opérationnelle d'un canary.
2. **Mesure de fréquence de déploiement (DORA)** : les logs CI suffisent. Brancher Prometheus +
   AnalysisTemplate pour mesurer ce KPI est un overengineering évident pour < 5 services.

---

## Étape 12 — Synthèse : ma chaîne de release est-elle production-ready ?

### Livrable 1 — Rétrospective TP 2 → TP 3

| Opération | TP 3 ressenti | Commentaire |
|---|---|---|
| Déployer une nouvelle version | Plus rassurant | On sait qu'au pire 5 % du trafic est touché pendant la fenêtre canary. |
| Détecter une régression | Beaucoup plus rassurant | L'AnalysisTemplate voit ce que les probes Kubernetes ne voient pas (erreur métier). |
| Faire un rollback | Équivalent pour l'humain, meilleur pour le système | `git revert` reste identique ; mais le rollout automatique évite la détection tardive. |
| Limiter l'impact | Radicalement différent | 5 % max vs 100 % avec RollingUpdate. C'est la promesse centrale du progressive delivery. |
| Savoir si le service tient son SLO | Inexistant avant, présent maintenant | Dashboard Grafana + alertes = on ne découvre plus un problème par un appel de support. |
| Décider de promouvoir | Sur preuve vs au feeling | Le plus grand changement de posture. On ne déploie plus sans mesure. |
| Justifier un déploiement à 17h vendredi | "Le canary est positif sur 30 min" | Argument technique > argument de confiance. |

**Deux opérations non justifiées pour une startup de 3 pers :**
1. La mesure de `change failure rate` via les Rollouts objects — les tickets Jira suffisent.
2. La mise en place d'un `AnalysisTemplate` pour des services internes peu critiques où le
   rollback < 2 min est acceptable.

**L'opération qui, à elle seule, justifie le passage TP 2 → TP 3 :**
La **détection automatique de régression** (AnalysisTemplate + Prometheus). C'est l'incident du
planning (`9h31`, emplois du temps décalés, personne ne s'en rend compte avant 10h45) qui ne se
reproduit plus. ArgoCD dit "Synced + Healthy" mais ne dit pas "le service fonctionne" — c'est
exactement ce que comble l'AnalysisTemplate.

---

### Livrable 2 — Ce que cette chaîne ne sait toujours pas faire

#### 1. Traçabilité distribuée
**Risque :** un appel utilisateur traverse `annuaire → planning → notif`. Si `planning` est lent,
les métriques RED montrent une dégradation mais pas *où* dans la chaîne elle commence. On cherche
à la main, log par log.

**Outil :** OpenTelemetry SDK dans chaque service + Jaeger ou Grafana Tempo pour la visualisation.
Les traces distribuées permettent de voir le span exact qui prend du temps.

**Référence :** [opentelemetry.io/docs/instrumentation/js](https://opentelemetry.io/docs/instrumentation/js/)
et [grafana.com/docs/tempo](https://grafana.com/docs/tempo/latest/)

#### 2. Logs centralisés corrélés aux métriques
**Risque :** quand une alerte fire à 3h, les logs sont dans les pods. Si le pod a crashé, les
logs sont perdus. On ne peut pas corréler un spike de latence avec une ligne de log spécifique.

**Outil :** Loki + Fluent Bit (ou Promtail) pour centraliser les logs ; les exemplars Prometheus
créent un lien direct entre un point de dashboard Grafana et la trace/log correspondante.

**Référence :** [grafana.com/docs/loki](https://grafana.com/docs/loki/latest/) et
[prometheus.io/docs/concepts/exemplars](https://prometheus.io/docs/concepts/exemplars/)

#### 3. Mesure côté utilisateur (RUM)
**Risque :** la latence p95 mesurée par Prometheus est la latence *serveur*. Elle ne compte pas
le temps réseau, le rendu navigateur, le Time to First Byte réel. Un utilisateur en 3G sur une
mauvaise connexion peut avoir une expérience dégradée que nos métriques ne voient pas du tout.

**Outil :** Core Web Vitals (LCP, FID, CLS) collectés via un snippet JavaScript + Grafana Faro
ou equivalent. En B2B (DevHub Campus), le RUM est moins critique qu'en B2C, mais il reste utile
pour les enseignants qui utilisent des réseaux institutionnels lents.

**Référence :** [web.dev/vitals](https://web.dev/vitals/) et
[grafana.com/docs/grafana-cloud/monitor-applications/frontend-observability](https://grafana.com/docs/grafana-cloud/monitor-applications/frontend-observability/)

#### 4. Chaos engineering applicatif
**Risque :** on a testé le "happy path" + quelques erreurs 5xx artificielles. On n'a jamais testé
ce qui se passe si Kubernetes tue un pod pendant un canary, si le réseau entre `planning` et
`annuaire` est saturé à 50 ms de latence, ou si le disque du nœud est plein. Les vrais incidents
ressemblent à ces scénarios, pas aux scénarios de test.

**Outil :** Chaos Mesh (CNCF Incubating) ou LitmusChaos (CNCF Graduated). Injecter des faults
(pod kill, network delay, CPU throttle) pendant un canary pour vérifier que l'AnalysisTemplate
détecte bien la dégradation et rollback.

**Référence :** [chaos-mesh.org](https://chaos-mesh.org/) et
[litmuschaos.io](https://litmuschaos.io/)

#### 5. Politique d'admission des manifests
**Risque :** rien n'empêche un développeur de committer un `Rollout` sans `AnalysisTemplate`,
ou avec `autoPromotionEnabled: true` sur un blueGreen. La chaîne GitOps synchronise et déploie
sans contrôle. Un seul commit mal formé peut casser les garanties SRE.

**Outil :** Kyverno (CNCF Graduated) ou OPA Gatekeeper. Exemples de policies : "tout Rollout
doit référencer un AnalysisTemplate", "aucun Deployment ne peut coexister avec un Rollout de
même nom", "toutes les images doivent venir du registre interne".

**Référence :** [kyverno.io/docs](https://kyverno.io/docs/) et
[open-policy-agent.github.io/gatekeeper](https://open-policy-agent.github.io/gatekeeper/)

#### 6. Signature des images et provenance
**Risque :** ArgoCD synchronise l'image `host.docker.internal:5001/annuaire:tp3-v7`. Rien ne
prouve que cette image a été construite par notre CI et pas par quelqu'un qui a poussé directement
sur le registre. En production avec un registre public ou partagé, c'est une surface d'attaque
supply-chain réelle.

**Outil :** Sigstore / cosign pour signer les images à la sortie de la CI, et vérifier la
signature à l'admission (via Kyverno + cosign policy). In-toto pour l'attestation de build.
SLSA level 2+ comme cadre d'exigence.

**Référence :** [docs.sigstore.dev](https://docs.sigstore.dev/) et
[slsa.dev](https://slsa.dev/)

#### 7. Backup applicatif et disaster recovery
**Risque :** les données de DevHub Campus (emplois du temps, annuaire) sont gérées par des
services stateless dans notre stack — mais si en production ils s'appuyaient sur une base de
données (PostgreSQL, Redis), une suppression accidentelle du namespace ou du PVC serait
irréversible. Notre GitOps reconstitue les pods, pas les données.

**Outil :** Velero (CNCF sandbox) pour les snapshots de PVC et les backups de namespace entier.
En complément : dumps SGBD en cron job + stockage objet externe (S3/MinIO). Tester régulièrement
la restauration — un backup non testé est un backup inutile.

**Référence :** [velero.io/docs](https://velero.io/docs/) et
[longhorn.io](https://longhorn.io/) pour le stockage distribué en cluster.

---

### Livrable 3 — Ma position d'architecte

Demain je deviens responsable plateforme dans une boîte avec 10 services et 30 développeurs.

**Ce que je garde :** ArgoCD (GitOps non-négociable, évite le drift), Argo Rollouts avec
AnalysisTemplate Prometheus (le progressive delivery sur preuve est ce qui justifie la posture
SRE), et kube-prometheus-stack (Prometheus + Alertmanager + Grafana, stack de facto,
opérationnelle en une journée).

**Ce que je remplace :** le webhook receiver in-cluster `mendhak/http-https-echo` par un vrai
canal (Slack/PagerDuty) ; le mode pull d'ArgoCD par Image Updater pour éviter les commits
manuels de tag ; les PrometheusRules statiques par des SLO burn-rate alerts (multi-window,
Google SRE Workbook chapitre 5) dès que l'équipe est prête.

**Ce que j'ajoute :** Kyverno dès le premier jour pour imposer `AnalysisTemplate` obligatoire et
interdire les Deployment/Rollout coexistants (évite la catégorie d'erreur #1 du TP) ; Loki +
Fluent Bit pour les logs centralisés (corréler log + métrique + trace est la différence entre
30 min et 3 h de MTTR) ; Sigstore/cosign sur la CI pour la signature des images (supply-chain
security, pas optionnel à 30 devs).

**Pourquoi :** à 30 développeurs, les incidents humains (mauvais commit, mauvaise image, oubli
d'AnalysisTemplate) deviennent le vecteur principal de régression — plus que les bugs applicatifs.
La chaîne TP 3 protège contre les régressions mesurables. Kyverno + Sigstore protègent contre
les erreurs de processus. C'est le niveau de maturité opérationnelle où la confiance dans la
plateforme remplace la confiance dans les individus.

---

### Note sur Grafana (non-CNCF)

Grafana est le seul outil de la stack hors CNCF (projet Grafana Labs, AGPLv3). Si demain je dois
justifier une stack 100 % CNCF en comité d'archi, l'alternative est Perses (CNCF Sandbox, 2023)
ou l'UI Prometheus + recording rules pré-calculées. En l'état, je consens à ce compromis
pragmatique : Grafana est le standard industriel, son écosystème de dashboards est incomparable,
et la licence AGPLv3 ne pose pas de problème tant qu'on ne l'embarque pas dans un produit
distribué. Je documente ce choix explicitement.

---
