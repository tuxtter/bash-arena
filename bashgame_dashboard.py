#!/usr/bin/env python3
import base64
import binascii
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import game_state

ADMIN_PASSWORD_FILE = "/var/lib/bashgame/admin.password"

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Bashgame scoreboard</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; background: #111827; color: #f3f4f6; }
    body { max-width: 760px; margin: 4rem auto; padding: 0 1.25rem; }
    h1 { margin-bottom: .35rem; }
    p { color: #9ca3af; }
    table { width: 100%; border-collapse: collapse; margin-top: 2rem; background: #1f2937; border-radius: .75rem; overflow: hidden; }
    th, td { padding: .9rem 1rem; text-align: left; border-bottom: 1px solid #374151; }
    th { color: #9ca3af; font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; }
    tbody tr:last-child td { border-bottom: 0; }
    td.score { text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; }
    th:last-child { text-align: right; }
    .alive { color: #34d399; }
    .eliminated { color: #f87171; }
    .online { color: #34d399; }
    .offline { color: #9ca3af; }
    #status { min-height: 1.5em; }
    h2 { margin: 2.5rem 0 .75rem; }
    #tree { padding: 1rem 1.25rem; background: #1f2937; border-radius: .75rem; }
    #tree ul { list-style: none; margin: .35rem 0 0; padding-left: 1.25rem; }
    #tree > ul { padding-left: 0; }
    #tree li { padding: .2rem 0; }
    button { padding: .65rem 1rem; border: 1px solid #7f1d1d; border-radius: .5rem; color: #fee2e2; background: #7f1d1d; cursor: pointer; }
    button.respawn { border-color: #065f46; color: #d1fae5; background: #065f46; }
    button:disabled { opacity: .6; cursor: wait; }
  </style>
</head>
<body>
  <h1>Bashgame</h1>
  <p>All-versus-all file survival. Scores count opponents eliminated.</p>
  <p id="status" role="status" aria-live="polite">Loading scoreboard…</p>
  <button id="reset" type="button">Reset round</button>
  <table>
    <thead><tr><th>Player</th><th>Connection</th><th>Game status</th><th>Eliminations</th><th>Action</th></tr></thead>
    <tbody id="players"><tr><td colspan="5">Loading…</td></tr></tbody>
  </table>
  <h2>Folder tree</h2>
  <div id="tree" aria-live="polite">Loading folders…</div>
  <script>
    const body = document.getElementById("players");
    const tree = document.getElementById("tree");
    const status = document.getElementById("status");
    const resetButton = document.getElementById("reset");
    async function postAdminAction(path, password, payload) {
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Authorization": `Basic ${btoa(`admin:${password}`)}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      if (response.status === 401) throw new Error("Incorrect admin password.");
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Dashboard action failed.");
      return result;
    }
    function renderTree(node) {
      const label = document.createElement("span");
      label.textContent = node.name;
      const item = document.createElement("li");
      item.append(label);
      if (node.children.length) {
        const list = document.createElement("ul");
        for (const child of node.children) list.append(renderTree(child));
        item.append(list);
      }
      return item;
    }
    async function refresh() {
      try {
        const response = await fetch("/api/scoreboard", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const folderList = document.createElement("ul");
        folderList.append(renderTree(data.tree));
        tree.replaceChildren(folderList);
        body.replaceChildren();
        for (const player of data.players) {
          const row = document.createElement("tr");
          const name = document.createElement("td");
          name.textContent = player.username;
          const connection = document.createElement("td");
          connection.textContent = player.online ? "Online" : "Offline";
          connection.className = player.online ? "online" : "offline";
          const gameStatus = document.createElement("td");
          gameStatus.textContent = player.alive ? "In game" : "Eliminated";
          gameStatus.className = player.alive ? "alive" : "eliminated";
          const score = document.createElement("td");
          score.textContent = player.score;
          score.className = "score";
          const action = document.createElement("td");
          if (!player.alive) {
            const respawnButton = document.createElement("button");
            respawnButton.className = "respawn";
            respawnButton.type = "button";
            respawnButton.textContent = "Respawn";
            respawnButton.addEventListener("click", async () => {
              if (!window.confirm(`Respawn ${player.username}? Their elimination score will be preserved.`)) return;
              const password = window.prompt("Enter the dashboard admin password:");
              if (password === null) return;
              respawnButton.disabled = true;
              try {
                await postAdminAction("/api/respawn", password, { username: player.username });
                status.textContent = `${player.username} respawned.`;
                await refresh();
              } catch (error) {
                status.textContent = error.message;
              } finally {
                respawnButton.disabled = false;
              }
            });
            action.append(respawnButton);
          }
          row.append(name, connection, gameStatus, score, action);
          body.append(row);
        }
        if (data.players.length === 0) {
          const row = document.createElement("tr");
          const cell = document.createElement("td");
          cell.colSpan = 5;
          cell.textContent = "No players in this round.";
          row.append(cell);
          body.append(row);
        }
        status.textContent = `Updated ${new Date().toLocaleTimeString()}. Refreshes every 3 seconds.`;
      } catch (error) {
        status.textContent = "Dashboard update failed; retrying.";
        console.error("Scoreboard refresh failed:", error);
      }
    }
    resetButton.addEventListener("click", async () => {
      if (!window.confirm("Start a fresh round? This respawns all players, clears scores and arena files, and disconnects current players.")) return;
      const password = window.prompt("Enter the dashboard admin password:");
      if (password === null) return;
      resetButton.disabled = true;
      try {
        await postAdminAction("/api/reset", password, {});
        status.textContent = "Fresh round started.";
        await refresh();
      } catch (error) {
        status.textContent = error.message;
      } finally {
        resetButton.disabled = false;
      }
    });
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
""".encode("utf-8")


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(PAGE)
            return

        if self.path == "/api/scoreboard":
            try:
                body = json.dumps({
                    "players": game_state.scoreboard(),
                    "tree": game_state.folder_tree(),
                }).encode("utf-8")
            except game_state.GameStateError as exc:
                self.log_error("scoreboard unavailable: %s", exc)
                body = b'{"error":"scoreboard unavailable"}'
                self.send_response(503)
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)

    def do_POST(self):
        if self.path not in ("/api/reset", "/api/respawn"):
            self.send_error(404)
            return

        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        parsed_origin = urlsplit(origin or "")
        if (
            not host
            or parsed_origin.scheme not in ("http", "https")
            or parsed_origin.netloc != host
        ):
            self.send_error(403, "same-origin requests only")
            return

        authorization = self.headers.get("Authorization", "")
        if not self._authorized(authorization):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Bashgame admin"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if self.path == "/api/reset":
            try:
                player_count = game_state.reset_round()
            except game_state.GameStateError as exc:
                self.log_error("round reset failed: %s", exc)
                body = b'{"error":"round reset failed"}'
                self.send_response(500)
            else:
                body = json.dumps({"ok": True, "players": player_count}).encode("utf-8")
                self.send_response(200)
                print(f"dashboard: fresh round started for {player_count} players", flush=True)
        else:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 0 < content_length <= 4096:
                    raise ValueError("invalid request body size")
                payload = json.loads(self.rfile.read(content_length))
                username = payload.get("username") if isinstance(payload, dict) else None
                if not isinstance(username, str) or set(payload) != {"username"}:
                    raise ValueError("invalid respawn request")
            except (ValueError, UnicodeDecodeError) as exc:
                self.log_error("invalid respawn request: %s", exc)
                body = b'{"error":"invalid respawn request"}'
                self.send_response(400)
            else:
                try:
                    game_state.respawn_player(username)
                except game_state.GameStateError as exc:
                    self.log_error("player respawn failed: %s", exc)
                    body = b'{"error":"player respawn failed"}'
                    self.send_response(409)
                else:
                    body = json.dumps({"ok": True, "username": username}).encode("utf-8")
                    self.send_response(200)
                    print(f"dashboard: respawned player {username}", flush=True)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _authorized(authorization):
        scheme, separator, encoded = authorization.partition(" ")
        if not separator or scheme.lower() != "basic":
            return False
        try:
            credentials = base64.b64decode(encoded, validate=True).decode("utf-8")
            username, separator, password = credentials.partition(":")
            expected_password = Path(ADMIN_PASSWORD_FILE).read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError, binascii.Error):
            return False
        return (
            separator == ":"
            and username == "admin"
            and hmac.compare_digest(password, expected_password)
        )

    def log_message(self, format_string, *args):
        print(f"dashboard: {self.address_string()} {format_string % args}", flush=True)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8080), DashboardHandler)
    print("Bashgame dashboard listening on port 8080", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
