# x-lookup-api — repères pour Claude

API FastAPI **publique de lookup X/Twitter** (users, posts, timelines…) destinée à la
revente sur le marketplace **RapidAPI**. La logique d'accès à l'API interne de X est
reprise de **Nitter**. L'archi ne doit rien coder en dur qui suppose un seul type d'objet
(user / post / list) ni une seule stratégie d'authentification vers X.

- **Blueprint complet & endpoints cibles : `docs/PROJECT.md` — à lire avant toute feature.**
- Référence d'implémentation de la couche X : le **clone local de Nitter**
  (`src/consts.nim`, `apiutils.nim`, `auth.nim`, `tid.nim`, `api.nim`, `parser.nim`).
- Modèle de bonnes pratiques imposé : le **repo de back-office de référence** (archi en
  couches + conventions) — **modèle uniquement**, cf. §0.
- Les chemins locaux de ces deux repos sont dans `.claude/local-refs.md`, **gitignoré** :
  ils pointent vers du code tiers et professionnel qui n'a rien à faire dans ce dépôt.

---

## 0. Isolation du projet (règle n°1)

- **Projet personnel, zéro lien avec l'entreprise.** Aucune dépendance interne (le package
  de modèles partagés en particulier), aucun secret, aucune URL, aucun nom de client, aucune
  mention de l'entreprise — ni dans le code, ni dans les docs, ni dans les commits. Le repo
  de référence sert de **modèle d'architecture** : on en copie les patterns, jamais le code
  ni les dépendances.
- **PyPI public uniquement.** La machine injecte un index privé via `%APPDATA%\pip\pip.ini`
  et une variable `PIP_EXTRA_INDEX_URL` définie au niveau machine. Installer avec
  `pip install --isolated --index-url https://pypi.org/simple -r requirements.txt`, sinon la
  résolution part sur l'index privé et fait entrer une dépendance interdite par accident.
- **Pas d'espace dans le chemin du projet** (`x-lookup-api`) : Docker, buildx et les scripts
  CI cassent dessus.

---

## 1. Workflow de collaboration (non négociable)

- **Plan avant dev.** Sur toute nouvelle feature : présenter en discussion les
  routes/endpoints, la justification de chaque choix, et la preuve que les conventions du
  repo sont comprises — **attendre la validation avant d'écrire du code**. Vaut **aussi pour
  les corrections en cours de feature** : un rapport de bug n'est pas une autorisation
  d'éditer, on explique les options d'abord.
- **Un ticket = une MR.** Segmenter le long des couches (Endpoint → Route → Service →
  Repository/Client), pas une grosse MR. Une MR de plomberie prend le **plus petit
  consommateur possible**, jamais la feature d'un ticket futur. Corollaire : **pas de couche
  sans consommateur**.
- **Jamais de `git commit` sans autorisation explicite** de l'utilisateur (il peut vouloir
  une autre branche). **Message de commit simple**, sans trailer `Co-Authored-By` /
  `Claude-Session`.
- **Lire le comportement réel avant d'écrire le code d'intégration.** Ici la source de vérité
  est le code Nitter **et** une réponse réelle de X, pas ce qu'on suppose du schéma : X sert
  deux formes de réponse simultanément et un champ « toujours présent » disparaît sans
  préavis.
- Nommer les branches `Feat/Malik/...` (pas `Chore/...`).

---

## 2. Architecture

Archi en couches, **modulaire par domaine métier**, sans sur-ingénierie :

```
app/
├── routes/<domaine>/       # endpoints + validation Pydantic + orchestration fine
├── services/<domaine>/     # logique métier (résolution username→id, cache, pagination)
├── repositories/<domaine>/ # accès Mongo/Redis — renvoie des modèles validés
├── clients/x/              # gateway HTTP vers l'API interne de X (pendant du repository)
├── models/<domaine>/       # modèles API In/Out ; modèles internes du pool à part
├── exceptions/             # handlers transverses + erreurs métier par domaine
├── core/                   # pool de sessions, rate-limit, TID, cache — le cœur non-HTTP
├── db/{mongodb.py,redis.py}
├── dependencies.py         # fonctions Depends (lisent app.state, jamais un global)
├── config.py               # pydantic-settings (source de vérité de la config)
└── main.py                 # app FastAPI + lifespan (pings, registres) + middlewares
```

- **Chaîne** : Endpoint → **Route → Service → Repository/Client**. La couche service est
  obligatoire entre route et repo. Seule exception tolérée : un proxy pur sans aucune règle
  métier à nous — et le commentaire doit dire pourquoi la couche serait une coquille vide.
- **`clients/x/` est la seule frontière avec X.** Aucune route, aucun service ne construit
  une URL GraphQL, ne choisit un bearer, ne lit un header de rate-limit ni ne touche un
  cookie.
- **`core/` n'est pas un fourre-tout** : uniquement ce qui n'appartient à aucune couche (pool
  de sessions, comptabilité de rate-limit, génération du transaction id, single-flight du
  cache). Si ça n'a qu'un consommateur dans une couche, ça vit dans cette couche.
- **Ajouter un endpoint X = additif** : une constante de query id, un builder de variables,
  un parseur, un modèle de sortie. Rien d'autre ne bouge.

---

## 3. Couche X & pool de comptes (décisions figées)

- **Sessions de comptes uniquement, pas de guest token.** X les a supprimés du chemin de
  lecture ; un guest token ne sert qu'à l'outil de création de session (flow
  `1.1/onboarding/task.json`). Une session = cookies `auth_token` + `ct0` (ou un couple
  OAuth1), plus l'id numérique du compte.
- **Mongo = source de vérité des comptes** (cookies, état, dernière erreur, dates) ;
  **Redis = état chaud** (cache des réponses, compteurs de rate-limit, single-flight). Le
  pool est chargé en mémoire au boot et rafraîchi en tâche de fond — **le chemin chaud ne
  fait jamais d'I/O de pool**, sinon chaque lookup paie deux allers-retours de base.
- **Rate-limit compté par couple (session, endpoint)**, alimenté par les headers
  `x-rate-limit-remaining` / `-reset` / `-limit` de chaque réponse. Une session est traitée
  comme épuisée pour un endpoint dès `remaining <= 10` tant que `reset` est dans le futur :
  la marge absorbe les requêtes concurrentes déjà parties.
- **Taxonomie d'erreurs X figée** (code de `errors[0].code`) :
  `88` → cooldown de la session ; `89 / 239 / 326` → éviction définitive du pool (token
  expiré / invalide / compte verrouillé) ; `17 / 34 / 50 / 63 / 144` → **404 métier propre**,
  jamais un retry (l'objet n'existe pas, réessayer ne le fera pas apparaître) ; `429`, `503`
  et `404` à corps vide → retry sur **une autre session**.
- **`authorization` et `x-client-transaction-id` sont couplés** : bearer principal **avec**
  TID, bearer secondaire **sans** TID. Ne jamais mélanger les deux combinaisons — c'est la
  cause n°1 d'échec silencieux des requêtes.
- **Aucune variable GraphQL construite par concaténation de chaînes.** Curseurs, termes de
  recherche et identifiants viennent du client : sérialisation JSON systématique
  (`json.dumps(..., separators=(",", ":"))`). C'est une classe d'injection réelle, déjà
  exploitée dans Nitter, pas une précaution théorique.
- **Fail-fast au démarrage** : ping Mongo et Redis dans le lifespan (en parallèle) **et**
  pool non vide → un datastore injoignable ou zéro session valide **stoppe le boot** au lieu
  de 500-er chaque requête. X lui-même n'est **pas** appelé au boot : sa panne est un 502 par
  requête, elle ne doit pas empêcher l'API de démarrer.
- **Dépendances** dans `dependencies.py` qui lisent `request.app.state.…`, jamais un global
  de module.

---

## 4. Conventions de code

- **Modèles Pydantic aux frontières, jamais de `dict`** — en lecture ET en écriture. Le
  repository/client est la **frontière d'intégrité** : il reçoit et renvoie des modèles
  validés. Corollaire : `model_dump` et ses flags (`exclude_none` pour un insert,
  `exclude_unset` pour un `$set` partiel) vivent **dans le repository/client** (savoir de
  persistance), pas dans le service.
- **Le JSON brut de X ne franchit jamais `clients/x/`.** Les parseurs y traduisent en modèles
  internes ; services et routes ne connaissent que ces modèles. Corollaire : X peut changer
  de forme de réponse sans qu'une seule route bouge.
- **Tolérance de forme obligatoire côté parseur.** X sert simultanément l'ancienne forme
  (`legacy`, camelCase) et la nouvelle (`core` / `avatar` / `details` / `counts`, snake_case),
  et plusieurs racines d'instructions selon l'endpoint. Un parseur **essaie plusieurs chemins
  et prend le premier non-nul** — jamais un chemin unique en dur.
- **Validation déclarative (Pydantic)** — **aucune logique ni `raise` dans une route** (y
  compris la gestion d'exception). Valider un path param = un type annoté
  (`Annotated[str, AfterValidator(...)]`), pas un `raise HTTPException` dans l'endpoint.
- **Gestion d'exceptions** : exceptions custom + `@app.exception_handler`, format de réponse
  `{"error", "message"}`. Couvrir : 404 ressource absente, **500 propre** si Mongo/Redis est
  down ou en timeout, corruption de document (validation qui échoue), **502 si X échoue**
  (distinct d'un 500 à nous), 429 quand notre propre quota est dépassé.
- **Descriptions Swagger obligatoires** : tout champ d'un modèle request/response exposé
  porte un `Field(description=...)` explicite. Sur RapidAPI, cette description **est** la
  documentation vendue au client — c'est son seul contrat, il n'a pas accès au code.
- **Nommage explicite, quitte à être long**, surtout pour tout ce qui touche un datastore :
  `X_SESSIONS_MONGODB_URL`, pas `MONGODB_URL`.
- **Pas de `typing.Any`** → `object` / `Callable[..., object]`.
- **Pas de variable à usage unique.**
- **Logging hybride** : `except X as e: logger.exception(f"... - {e}")`. Une erreur métier
  attendue (user inexistant) **ne se logge pas** ; un échec se logge **là où il se produit**,
  une seule fois — les handlers ne re-loggent pas.
- **Ne jamais logger un cookie de session, un `ct0`, un bearer ou un transaction id.** Sur
  une `ValidationError` d'un document de compte, logger
  `e.errors(include_input=False, include_url=False)` — l'input contient les identifiants.
- **Pas de dépendance ajoutée « en prévision »** : on ajoute un paquet quand un import le
  consomme réellement (idem plomberie : pas de couche sans consommateur).

---

## 5. Config & secrets

- `pydantic-settings` (`app/config.py`) = source de vérité de la config. Les variables
  requises sont **sans défaut** → le boot plante si elles manquent (fail-fast voulu). Ne
  mettre un défaut que pour du vraiment optionnel (nom de collection, TTL de cache…).
- **Aucun secret dans le repo.** `.env` est gitignoré, `.env.example` ne contient que des
  placeholders. Les comptes X vivent **en base**, jamais dans un fichier versionné. En CI :
  GitHub Secrets.
- URIs Mongo : **percent-encoder** les caractères spéciaux du mot de passe (`&`→`%26`,
  `!`→`%21`, `%`→`%25`).
- **Le secret RapidAPI (`X-RapidAPI-Proxy-Secret`) est vérifié par un middleware**, pas dans
  les routes. `/health` en est **exempté** : liveness minimale, jamais l'état du pool ni le
  nombre de comptes — c'est une information exploitable par un tiers.

---

## 6. Qualité & tests

- **Tests unitaires par couche** (pytest) avec des **fakes** — pas de vraie base, pas d'appel
  réseau. Chaque couche teste sa responsabilité : route (codes HTTP, garde-fous), service
  (règles métier), repository (requête Mongo/Redis construite), client (mapping des réponses
  HTTP via un transport mocké).
- **Le client X se teste sur des fixtures JSON réelles** dans `test/fixtures/x/` : captures
  anonymisées couvrant **les deux formes** de réponse. C'est le seul garde-fou contre une
  régression silencieuse le jour où X change de schéma.
- **Outils** : black (line-length 88), isort, pycln, pyrefly, enchaînés par **pre-commit**.
  Couverture via `coverage`, avec un `fail_under` dans `pyproject.toml`.
- **Le lint tourne en CI**, en rejouant exactement les hooks : `pre-commit run --all-files`
  en mode `--show-diff-on-failure`. Il n'y a **pas** de gate qualité externe sur ce repo :
  pre-commit local se contourne avec un `--no-verify`, donc la CI est le seul filet réel.
  Corollaire : **un hook n'est ajouté qu'en local et en CI en même temps** — sinon les deux
  divergent et la CI devient du bruit qu'on finit par ignorer.
- **Le seuil de couverture est la gate**, pas un indicateur : `coverage report --fail-under`
  fait échouer le job. On monte le seuil quand la couverture monte, on ne le baisse **jamais**
  pour faire passer une MR — c'est le seul garde-fou automatique qui reste.
- Factories de données partagées dans `test/helpers.py` : les payloads X sont volumineux et
  les recopier dans chaque test rend une évolution de schéma impossible à répercuter.
- Noms de tests en phrases complètes :
  `test_lifespan_refuses_to_boot_when_the_session_pool_is_empty`.

---

## 7. Docker / image de prod & CI

- `Dockerfile` **multi-stage** : le stage runtime copie **le venv + `app/` seulement** —
  `test/`, linters et `requirements-dev.txt` ne sont **jamais** dans l'image de prod.
  `.dockerignore` exclut `test/`, `docs/`, `.github/`. L'app tourne en **non-root**
  (`appuser`, uid 1000).
- Deux fichiers de dépendances : `requirements.txt` (prod, **pins exacts**, une ligne de
  commentaire justifiant chaque dépendance non évidente) et `requirements-dev.txt`
  (outillage, jamais installé dans l'image).
- **GitHub Actions**, pipeline `lint → test → build`. `lint` et `test` tournent sur chaque PR,
  `build` uniquement sur `main`. Le déploiement reste manuel tant que la cible d'hébergement
  n'est pas figée.
- **Un seul process API** (pas de `--workers`) tant que le pool de sessions est en mémoire :
  N workers = N pools divergents et une comptabilité de rate-limit fausse, donc des comptes
  bannis. Scaler horizontalement suppose **d'abord** de déporter l'état du pool dans Redis —
  c'est une décision à prendre, pas à subir.
