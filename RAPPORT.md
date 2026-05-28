# Rapport de TP : GitOps avec ArgoCD — `DevHub Campus`

Ce rapport présente l'ensemble des réalisations et justifications techniques apportées lors de la conception, de la containerisation et du déploiement GitOps de la plateforme **DevHub Campus** avec **ArgoCD** sur un cluster **Kind**.

---

## 1. Containerisation des Microservices

Pour répondre aux exigences de sécurité, de performance et d'empreinte minimale, chaque microservice dispose d'un `Dockerfile` multi-stage hautement optimisé :

### A. `annuaire-service` (Node.js)
* **Approche Multi-stage** : Une étape de construction (`build`) prépare les dépendances de production (`npm install --omit=dev`), puis l'image d'exécution (`runtime`) ne conserve que le code source utile et les dépendances nécessaires.
* **Sécurité** :
  * Utilisation d'une image de base alpine légère (`node:20-alpine`).
  * Création d'un groupe et d'un utilisateur non-root dédié (`appuser` avec l'UID `1001`) pour éviter toute exécution avec les privilèges root.

### B. `planning-service` (Python FastAPI)
* **Approche Multi-stage** : L'étape de `build` installe les dépendances dans un environnement virtuel (`venv`) à l'aide de `requirements.txt`. L'étape de `runtime` copie cet environnement virtuel entier `/opt/venv`, excluant ainsi tous les outils de build superflus.
* **Sécurité** :
  * Utilisation d'une image de base slim (`python:3.12-slim`).
  * Création de l'utilisateur d'exécution non-root `appuser` (UID `1001`).

### C. `notif-service` (Go)
* **Approche Multi-stage** : L'étape de `build` compile statiquement le binaire Go (`CGO_ENABLED=0`) en appliquant des drapeaux d'optimisation de taille et de symboles (`-ldflags="-s -w"`).
* **Sécurité** :
  * L'image de d'exécution utilise la base ultra-sécurisée **Distroless** de Google (`gcr.io/distroless/static-debian12:nonroot`).
  * Cette image d'exécution ne comporte aucun shell (`/bin/sh`), aucun gestionnaire de paquets, ni aucun utilitaire système, réduisant la surface d'attaque à zéro.
  * L'utilisateur par défaut est `nonroot` (UID `65532`), ce qui est reflété dans le securityContext Helm.

---

## 2. Configuration des Charts Helm

### A. Standards de Nommage et de Labellisation (`_helpers.tpl`)
Nous avons implémenté les 4 labels Kubernetes recommandés au niveau des métadonnées communes :
1. `app.kubernetes.io/name` : Nom du microservice.
2. `app.kubernetes.io/instance` : Nom de l'instance (Release Helm).
3. `app.kubernetes.io/part-of` : Nom du projet global (`devhub-campus`).
4. `app.kubernetes.io/managed-by` : Outil de gestion (`Helm`).

Pour les sélecteurs de pods (`selectorLabels`), nous avons conservé un ensemble minimal et stable pour éviter des redéploiements inutiles ou des erreurs de modification de sélecteur :
* `app.kubernetes.io/name`
* `app.kubernetes.io/instance`

### B. Sécurité : Pod-level vs. Container-level `securityContext`
Une bonne pratique Kubernetes consiste à séparer les privilèges au niveau du Pod et au niveau du conteneur :
* **Niveau Pod** : Définit l'identité d'exécution globale du pod.
  * `runAsNonRoot: true`
  * `runAsUser: 1001` (ou `65532` pour le conteneur Go).
* **Niveau Conteneur** : Définit les privilèges spécifiques accordés au conteneur lui-même.
  * `readOnlyRootFilesystem: true` : Le système de fichiers racine est monté en lecture seule pour empêcher les injections de code malveillant à l'exécution.
  * `allowPrivilegeEscalation: false` : Empêche un processus enfant d'obtenir plus de privilèges que son parent.
  * `capabilities.drop: ["ALL"]` : Supprime l'ensemble des capacités Linux standard non indispensables.

### C. Health Probes et Limites de Ressources
Chaque microservice dispose de sondes adaptées configurées dynamiquement depuis `values.yaml` :
* **ReadinessProbe** : Valide que l'application est prête à servir du trafic (`/healthz`).
* **LivenessProbe** : Valide que l'application est toujours saine. Si elle échoue de manière répétée, le conteneur est redémarré.
* **Resources** : Des requêtes et limites de CPU/mémoire strictes ont été définies pour éviter les attaques par déni de service interne (Out of Memory - OOM Killer) et garantir un ordonnancement optimal des pods.

---

## 3. Sécurité ArgoCD et AppProject (`devhub`)

Le manifest `platform/projects/devhub.yaml` a été conçu pour isoler et sécuriser l'environnement de développement :

* **`sourceRepos`** : Seul le dépôt Git interne du projet (`http://local-git-server.argocd.svc/git/devhub-campus.git`) est autorisé.
* **`destinations`** : Seul le cluster local (`https://kubernetes.default.svc`) et les namespaces `devhub-*` ou `argocd` (pour le bootstrapping) sont autorisés.
* **`clusterResourceWhitelist`** : Pour garantir la sécurité, les ressources de niveau cluster sont interdites par défaut. Cependant, nous avons whitelisté la ressource **`Namespace`** pour permettre à ArgoCD de provisionner à la volée le namespace `devhub-dev` lors du premier déploiement automatique via `CreateNamespace=true`.
* **Rôles Développeur (`roles`)** : Ajout d'un rôle `developer` avec des politiques RBAC limitées aux opérations de synchronisation et de lecture sur les applications du projet `devhub`.
* **Sync Windows (`syncWindows`)** : Une fenêtre d'interdiction de synchronisation a été configurée entre 18:00 et 08:00 le lendemain (durée `14h`) pour bloquer les synchronisations automatiques en dehors des heures de bureau (défi bonus). Elle autorise les synchronisations manuelles par les humains en cas d'urgence (`manualSync: true`).

---

## 4. Pattern App of Apps (Bootstrap) et Choix de Synchronisation

La racine de notre architecture GitOps repose sur l'Application `root` (`platform/bootstrap/root-app.yaml`).

### Choix de la Politique de Synchronisation

| Application | `prune` | `selfHeal` | Justification |
| :--- | :--- | :--- | :--- |
| **Root Application** (`root`) | **`true`** | **`true`** | **`prune: true`** garantit que si un manifest d'application enfant (ex. `notif.yaml`) est supprimé de `platform/apps/dev/` dans Git, ArgoCD détruit automatiquement l'application enfant correspondante dans le cluster.<br>**`selfHeal: true`** garantit que si une modification manuelle non autorisée est faite sur les métadonnées d'une application enfant dans le cluster, ArgoCD la restaure automatiquement selon l'état décrit dans Git. |
| **Applications Enfants** (ex. `annuaire-dev`) | **`false`** | **`true`** | **`prune: false`** évite la suppression accidentelle de ressources applicatives sensibles contenant des données d'exécution en cas d'erreur de commit.<br>**`selfHeal: true`** applique en permanence l'état désiré et répare immédiatement toute dérive de configuration (ex. modification manuelle d'un Deployment ou d'un Service). |

---

## 5. Serveur Git Interne (Solution Autonome)

Afin d'offrir une solution **100 % autonome et hors-ligne**, sans dépendance externe vis-à-vis d'un compte ou de clés d'API GitHub privées, un serveur Git léger (`aliolozy/tinygit`) a été déployé dans le namespace `argocd` (`platform/local-git-server.yaml`).

* **Flux de travail** :
  1. Le code modifié sur la machine hôte est poussé sur le serveur Git du cluster via un port-forward local (`git push local main`).
  2. ArgoCD interroge directement ce serveur Git interne à l'URL `http://local-git-server.argocd.svc/git/devhub-campus.git`.
* Cette architecture garantit une isolation parfaite et une vitesse de déploiement instantanée, idéale pour les environnements de laboratoire sécurisés.

---

## 6. Validation Opérationnelle

Tous les tests opérationnels ont été passés avec succès :
1. **Linting** : `helm lint` a validé les trois charts Helm avec 0 erreur.
2. **Synchronisation** : Les applications `root`, `annuaire-dev`, `planning-dev` et `notif-dev` sont toutes synchronisées (`Synced`) et saines (`Healthy`).
3. **Connectivité** : L'accès aux applications via l'Ingress Nginx de Kind a été validé avec `curl` :
   * Conteneur Node.js (`annuaire`) : `{"ok":true,"service":"annuaire"}` (200 OK)
   * Conteneur FastAPI (`planning`) : `{"ok":true,"service":"planning"}` (200 OK)
   * Conteneur Go Distroless (`notif`) : `{"ok":true,"service":"notif"}` (200 OK)
