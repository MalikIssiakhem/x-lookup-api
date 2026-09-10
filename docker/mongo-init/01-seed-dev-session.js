// Dev fixture — run once by the official Mongo image, on an empty data dir only
// (`/docker-entrypoint-initdb.d`). It exists so `docker compose up` still gives
// a booting API and a reachable Swagger: the lifespan refuses to start on an
// empty pool, which is correct in production and unlivable in development.
//
// Every value below is deliberately fake. No route calls X yet, so a session
// that cannot authenticate breaks nothing. A REAL account never belongs here:
// this file is committed. Real sessions are inserted into the production Mongo
// by the provisioning tool, never by a versioned script (CLAUDE.md §5).

db.sessions.createIndex({ username: 1 }, { unique: true });

db.sessions.insertOne({
  username: "dev_placeholder_account",
  kind: "cookie",
  auth_token: "dev-placeholder-auth-token-not-a-real-credential",
  ct0: "dev-placeholder-ct0-not-a-real-credential",
  status: "active",
  cooldown_until: null,
  created_at: new Date(),
  updated_at: new Date(),
});
