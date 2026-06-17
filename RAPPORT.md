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

*(sections suivantes à compléter au fil des étapes 3 à 12)*
