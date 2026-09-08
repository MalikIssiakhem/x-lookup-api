# x-lookup-api — blueprint produit

Source de vérité des endpoints commercialisés et de leur traduction vers l'API interne
de X. `CLAUDE.md` porte les règles d'architecture et de code ; ce fichier porte le
**contrat vendu** et le **mapping**. Toute nouvelle feature commence ici.

---

## 1. Ce qu'on vend

Une API de lookup X/Twitter **en lecture seule**, revendue sur RapidAPI. Le client
paie à l'appel : chaque endpoint doit donc avoir une raison d'exister **distincte des
autres** — un payload plus léger, un TTL de cache différent ou une entrée différente
suffisent, mais il faut que la raison soit écrite.

Contraintes qui découlent du modèle marketplace :

- Le client n'a **pas** accès au code : la description Swagger de chaque champ *est* la
  documentation vendue (`CLAUDE.md` §4).
- Le client ne sait pas ce qu'est un query id GraphQL ni un curseur X. Le contrat est
  stable même quand X change de schéma — c'est tout l'intérêt du produit.
- Un appel qui coûte deux requêtes vers X coûte deux fois plus cher en quota de pool.
  Les endpoints concernés sont identifiés comme tels ci-dessous.

---

## 2. Endpoints publics (v1)

Sept routes, un seul domaine : `users`.

| # | Route | Entrée | Sortie | Pagination | Appels X | TTL cache |
|---|---|---|---|---|---|---|
| 1 | `GET /users/by-username/{username}` | `username` | `UserOut` | — | 1 | court |
| 2 | `GET /users/{user_id}` | `user_id` (numérique) | `UserOut` | — | 1 | court |
| 3 | `GET /users/by-username/{username}/id` | `username` | `UserIdOut` | — | 1 | long |
| 4 | `GET /users/{user_id}/tweets` | `user_id` | `TimelinePageOut` | curseur | 1 | très court |
| 5 | `GET /users/by-username/{username}/tweets` | `username` | `TimelinePageOut` | curseur | 1 + 1 | très court |
| 6 | `GET /users/{user_id}/tweets-and-replies` | `user_id` | `TimelinePageOut` | curseur | 1 | très court |
| 7 | `GET /users/by-username/{username}/tweets-and-replies` | `username` | `TimelinePageOut` | curseur | 1 + 1 | très court |

**#3 n'est pas un doublon de #1.** Il tape le même endpoint X mais ne renvoie que le
couple `username` / `id`. Sa raison d'être est le **TTL** : le mapping username→id est
quasi-immuable, un profil complet ne l'est pas. Deux TTL = deux entrées de cache = deux
routes. C'est aussi l'endpoint le plus appelé de tout pipeline client, donc celui dont
le payload doit être le plus petit.

**#5 et #7 valent 2 appels X** (résolution puis timeline). Le service compose #3 puis la
timeline par id : en régime établi, la résolution sort du cache et le coût réel retombe
à 1 appel. C'est la deuxième justification de #3.

### Collision de routage

`/users/by-username/...` et `/users/{user_id}` se recouvrent. On lève l'ambiguïté en
**contraignant le type**, pas par l'ordre de déclaration des routes qui est silencieux
et fragile :

```python
UserId = Annotated[str, AfterValidator(validate_user_id)]        # ^\d{1,20}$
Username = Annotated[str, AfterValidator(validate_username)]     # ^[A-Za-z0-9_]{1,15}$
```

Les deux validateurs vivent dans `app/models/users/`. Un `user_id` non numérique ou un
`username` hors charset renvoie **422** sans jamais toucher au pool de sessions —
un lookup impossible ne doit pas consommer de quota.

---

## 3. Mapping vers l'API interne de X

Toutes les requêtes passent par `clients/x/`. Aucune autre couche ne connaît le contenu
de ce tableau.

| Route | Query id X | Variables | TID | fieldToggles |
|---|---|---|---|---|
| #1, #3 (session cookie) | `IGgvgiOx4QZndDHuD3x9TQ/UserByScreenName` | `screen_name`, `withGrokTranslatedBio` | **oui** | `withArticleRichContentState`, `withArticlePlainText`, `withGrokAnalyze`, `withDisallowedReplyControls` |
| #1, #3 (session OAuth) | `-ZzAG_Bckx16LMbEvHC3lg/UserResultByScreenNameQuery` | `screen_name` | **oui** | — |
| #2 | `-DAaa9jPxPswYeI2fZ9rug/UserResultByIdQuery` | `rest_id` | **oui** | — |
| #4, #5 | `LE3eTyeqhBh2g-fX85O2eQ/UserWithProfileTweetsQueryV2` | `rest_id`, `cursor`, `count` | **oui** | `withArticleRichContentState`, `withArticlePlainText` |
| #6, #7 | `AcYHjc_YAx-9_rKWdMsKvA/UserWithProfileTweetsAndRepliesQueryV2` | `rest_id`, `cursor`, `count` | **non** | `withArticleRichContentState`, `withArticlePlainText` |

Chaque requête porte en plus le blob `features` (constante partagée) en query param.

### Trois règles non négociables

1. **Le TID se décide par endpoint, pas globalement.**
   `UserWithProfileTweetsAndRepliesQueryV2` part **sans** `x-client-transaction-id` ; les
   autres le portent. Le `authorization` et le TID sont couplés (`CLAUDE.md` §3) : bearer
   principal **avec** TID, bearer secondaire **sans**. Une mauvaise combinaison ne lève
   pas d'erreur — la réponse revient simplement vide. C'est la cause n°1 d'échec
   silencieux.
2. **Le query id dépend du type de session.** Pour #1/#3, une session à cookies vise
   `UserByScreenName` et une session OAuth vise `UserResultByScreenNameQuery`. Le client
   ne peut donc pas construire l'URL avant d'avoir pioché une session dans le pool :
   **sélection de session puis résolution d'endpoint**, dans cet ordre.
3. **Aucune variable construite par concaténation.** `cursor`, `screen_name` et
   `rest_id` viennent du client final. Sérialisation JSON systématique
   (`json.dumps(..., separators=(",", ":"))`). C'est une classe d'injection réelle,
   déjà exploitée en pratique.

### Tolérance de forme des parseurs

X sert simultanément l'ancienne et la nouvelle forme. Un parseur **essaie plusieurs
chemins et prend le premier non-nul**, jamais un chemin unique en dur.

Racine de l'objet utilisateur, dans l'ordre :
`user_result.result` → `user_results.result` → la racine elle-même si elle porte `core`.

Champs d'un utilisateur — ancienne forme puis nouvelle :

| Champ | Ancienne forme | Nouvelle forme |
|---|---|---|
| username | `legacy.screen_name` | `core.screen_name` |
| nom affiché | `legacy.name` | `core.name` |
| date de création | `legacy.created_at` | `core.created_at` |
| avatar | `legacy.profile_image_url_https` | `avatar.image_url` |
| badge bleu | `is_blue_verified` | `verification.is_blue_verified` |
| type de vérification | `legacy.verified_type` | `verification.verified_type` |

Racine des instructions de timeline, dans l'ordre :
`data.user.result.timeline.timeline.instructions` →
`data.user_result.result.timeline_response.timeline.instructions`.

Un champ absent des deux formes est `None` dans le modèle de sortie, jamais une
exception : X retire un champ « toujours présent » sans préavis, et ça ne doit pas
transformer un lookup en 502.

---

## 4. Modèles de sortie

Définis dans `app/models/users/`. Tout champ exposé porte un `Field(description=...)`.

### `UserIdOut` (#3)

`id`, `username`. Rien d'autre — c'est le point de l'endpoint.

### `UserOut` (#1, #2)

Identité : `id`, `username`, `name`, `created_at`, `description`, `location`,
`website`, `profile_image_url`, `profile_banner_url`.
Compteurs : `followers_count`, `following_count`, `tweets_count`, `likes_count`,
`media_count`.
État : `is_verified`, `verified_type`, `is_protected`, `pinned_post_id`.

### `PostOut` (#4 à #7)

Identité : `id`, `text`, `created_at`, `lang`, `conversation_id`, `in_reply_to_post_id`,
`in_reply_to_user_id`, `is_pinned`.
Statistiques : `reply_count`, `retweet_count`, `like_count`, `quote_count`,
`bookmark_count`, `view_count`.
Entités : `urls`, `hashtags`, `mentions`, `media` (type, url, preview, dimensions).
Imbrication : `author` (`UserOut`), `quoted_post`, `retweeted_post`.

`author` est présent sur **chaque** post, y compris sur une timeline où il est presque
toujours le même utilisateur. C'est délibéré : un retweet a un auteur différent, et un
contrat uniforme vaut mieux qu'un payload minimal que le client doit recoller lui-même.

`quoted_post` et `retweeted_post` sont dépilés sur **un seul niveau**. X ne sert pas plus
profond, et une récursion non bornée sur un modèle Pydantic exposé est une surface
d'attaque gratuite.

### `TimelinePageOut` (#4 à #7)

`posts` (`list[PostOut]`), `next_cursor`, `has_more`.

---

## 5. Pagination

Curseur **brut de X**, passé tel quel au client dans `next_cursor` et réinjecté tel quel
dans le paramètre de query `cursor`. Pas de `page_token` maison : traduire le curseur
imposerait un aller-retour Redis par page pour un gain nul côté client.

Conséquences assumées :

- Le curseur est **opaque** : il n'est jamais construit ni parsé par nous, seulement
  transporté. Il est **sérialisé en JSON** avant d'entrer dans les variables GraphQL,
  comme toute entrée client (§3, règle 3).
- `has_more` est `false` quand X ne renvoie plus de curseur *bas*, pas quand la page est
  vide : X sert régulièrement une page vide suivie d'une page pleine.
- `count` est figé à 20 côté X. Le client ne choisit pas la taille de page en v1 — c'est
  une décision à prendre plus tard, pas à subir via un paramètre non testé.

---

## 6. Cache

Redis, clé par `(endpoint, entrée normalisée, curseur)`. Single-flight sur la clé pour
qu'un pic de trafic sur un même username ne parte pas en N requêtes vers X.

| Donnée | TTL par défaut | Raison |
|---|---|---|
| Résolution username→id (#3) | long (~24 h) | Mapping quasi-immuable. Pas *totalement* : un username libéré peut être repris par un autre compte, donc pas d'infini. |
| Profil (#1, #2) | court (~5 min) | Les compteurs bougent en permanence ; un profil périmé est visible par le client. |
| Timelines (#4 à #7) | très court (~60 s) | La fraîcheur *est* le produit sur une timeline. |

Les trois TTL sont des variables de config avec défaut (`CLAUDE.md` §5) : ce sont des
réglages économiques, pas des invariants.

Une réponse d'erreur n'est jamais mise en cache, **sauf** le 404 métier : un compte
inexistant le restera, et le remettre en cache évite qu'un scan de usernames aléatoires
vide le quota du pool.

---

## 7. Erreurs

Format de réponse uniforme `{"error", "message"}` via `@app.exception_handler`.
Aucun `raise` dans une route.

| HTTP | `error` | Quand |
|---|---|---|
| 401 | `unauthorized` | Secret RapidAPI absent ou faux (middleware, `/health` exempté) |
| 403 | `user_protected` | Timeline d'un compte protégé (le profil, lui, reste lisible) |
| 404 | `user_not_found` | X répond que l'objet n'existe pas |
| 404 | `user_suspended` | Compte suspendu — l'`error` distingue le cas, le code non |
| 422 | `validation_error` | `username` ou `user_id` hors format (avant tout appel X) |
| 429 | `rate_limited` | Notre propre quota dépassé |
| 500 | `internal_error` | Mongo/Redis injoignable ou en timeout, document de compte corrompu |
| 502 | `upstream_error` | X en échec après épuisement des sessions candidates |

Le 500 et le 502 sont **distincts** : l'un est notre panne, l'autre celle de X. Les
confondre rend le support impossible à trier.

### Taxonomie des erreurs X (code de `errors[0].code`)

| Code | Traitement |
|---|---|
| `88` | Cooldown de la session, on rejoue sur une autre |
| `89`, `239`, `326` | Éviction définitive de la session du pool (token expiré / invalide / compte verrouillé) |
| `17`, `34`, `50`, `63`, `144` | **404 métier propre, jamais de retry** — l'objet n'existe pas, réessayer ne le fera pas apparaître |
| `429`, `503`, `404` à corps vide | Retry sur **une autre session** |

---

## 8. Architecture cible pour la v1

```
app/
├── routes/users/          # les 7 endpoints, validation déclarative, zéro logique
├── services/users/        # résolution username→id, composition #5/#7, cache
├── repositories/sessions/ # comptes X en Mongo (source de vérité)
├── clients/x/             # seule frontière avec X : URLs, bearers, TID, parseurs
├── models/users/          # UserOut, UserIdOut, PostOut, TimelinePageOut, validateurs
├── models/sessions/       # modèles internes du pool (jamais exposés)
├── exceptions/            # handlers transverses + erreurs métier du domaine users
├── core/                  # pool de sessions, rate-limit, TID, single-flight du cache
├── db/{mongodb.py,redis.py}
├── dependencies.py
├── config.py
└── main.py
```

Pas de domaine `timelines` en v1 : les quatre routes de timeline sont indexées par un
utilisateur et n'auraient qu'un seul consommateur. On le sortira quand arriveront
search, lists ou communities — pas avant (`CLAUDE.md` §2, pas de couche sans
consommateur).

---

## 9. Découpage en tickets

Un ticket = une MR. Chaque ticket livre un consommateur réel de ce qu'il ajoute.

| # | Ticket | Livre |
|---|---|---|
| 1 | Blueprint | Ce fichier |
| 2 | Socle bootable | `config.py`, `main.py`, handlers d'exceptions, `/health`, Dockerfile multi-stage, CI lint/test/build |
| 3 | Datastores + pool | `db/`, **lifespan** avec ping fail-fast en parallèle, repository de sessions, pool en mémoire, refresh en tâche de fond |
| 4 | Client X + endpoint #1 | `clients/x/`, TID, comptabilité de rate-limit, parseur utilisateur tolérant, route #1 de bout en bout, fixtures des deux formes |
| 5 | Endpoint #2 | Additif : query id + builder de variables, parseur réutilisé |
| 6 | Endpoint #3 | Route de résolution + cache à TTL long |
| 7 | Endpoint #4 | `PostOut`, parseur de timeline, pagination par curseur |
| 8 | Endpoint #6 | Additif, **sans TID** |
| 9 | Endpoints #5 et #7 | Le service compose #3 et la timeline par id |
| 10 | Garde-fous marketplace | Middleware `X-RapidAPI-Proxy-Secret`, 429 sur notre propre quota |

L'ordre n'est pas négociable sur un point : le **client X et son premier consommateur
arrivent ensemble** (ticket 4). Une couche d'accès à X sans route qui l'appelle est du
code non testé en conditions réelles.

Le `lifespan` arrive au ticket 3 et non au 2 : ses pings de démarrage sont sa seule
raison d'être, et un `asynccontextmanager` qui ne fait que `yield` est de la plomberie
sans consommateur.

---

## 10. Hors scope v1

Backlog, dans l'ordre de valeur marchande estimée. Rien de tout ça n'ouvre de chantier
d'architecture : ajouter un endpoint X reste additif (une constante de query id, un
builder de variables, un parseur, un modèle de sortie).

- Post unique par id, et batch de posts par ids
- Recherche (`SearchTimeline`)
- Followers / following
- Timeline média d'un utilisateur
- Listes (membres, timeline)
- Communities
- Historique d'édition d'un post, Spaces, broadcasts
