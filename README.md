# Bashgame

Bashgame is a small multiplayer, all-versus-all file survival game. Players connect over SSH using public keys. Everyone can see and move or remove files in the shared arena; each player's `<name>.flag` is their life. Removing a player's flag disconnects them and prevents them from rejoining that round.

Docker provides the isolated game environment. SSH sessions are forced into a command interpreter that supports only `ls`, `tree`, `find`, `cd`, `pwd`, `touch`, `mkdir`, `mv`, `rm`, and `exit`. Paths are confined to `/arena`, where players can create shared directories; directory removal, shell operators, wildcard characters (`*`, `?`, `[` and `]`), and other commands are not available. Use `tree` to view the arena's files and directories, or `find [directory]` to list entries under a directory. The dashboard also displays the folder tree. Use `exit` or Ctrl-D to disconnect normally. `mv` can replace an existing file, so moving a file onto another player's flag eliminates them.

SSH sessions open with a static, colorful Bashgame ASCII welcome banner. Interactive terminals use colored status, prompts, command output, and error messages, with no animation. Color is disabled for `TERM=dumb` terminals and when `NO_COLOR` is set. Non-interactive sessions use the normal line-based shell.

Players can be eliminated only while online: `rm` and `mv` cannot remove or replace an offline player's flag. Eliminating an online opponent with either command earns one point for the player who performed the action. Removing or replacing your own flag does not award a point. The live scoreboard shows every player, whether they are connected over SSH, whether they are still in the game, and their elimination count.

## Set up players

Create one SSH key pair per player, then copy only each public key into `keys/` using the player's login name:

```sh
ssh-keygen -t ed25519 -f alice
ssh-keygen -t ed25519 -f bob
cp alice.pub keys/alice.pub
cp bob.pub keys/bob.pub
```

Player names must start with a lowercase letter and contain only lowercase letters, digits, `_`, or `-` (up to 32 characters). Keep the private key files private; do not put them in `keys/`.

## Start and connect

```sh
docker compose up --build
```

Connect each player in a separate terminal:

```sh
ssh -p 2222 alice@localhost
ssh -p 2222 bob@localhost
```

Open [http://localhost:8080](http://localhost:8080) to view the live scoreboard.

The dashboard's **Reset round** button starts a fresh round: it respawns every player, clears arena files and scores, and disconnects current SSH sessions. Reset requires the dashboard admin password, shown once in the container startup logs (retrieve it with `docker compose logs bashgame | grep 'Dashboard admin password'`). Store it securely. For a public server, put the dashboard behind HTTPS and restrict dashboard access; do not send the admin password over plain HTTP.

An admin can also use the **Respawn** action beside an eliminated player to return that player to the game without clearing the arena or changing any scores. Respawning creates a fresh flag and disconnects any stale SSH sessions; the player can reconnect with their existing SSH key. This action also requires the dashboard admin password.

Use `ls` to look around. Create directories with `mkdir hideout` and enter them with `cd hideout`. Rename your flag often with `mv alice.flag a-new-name`; it remains yours while its contents are preserved, including when moved into a subdirectory. Use `rm bob.flag` to eliminate another player. `touch` can create decoy files. Wildcard characters are rejected rather than expanded.

The round's player list comes from the public keys present when the container starts. Every successful container start clears the arena contents, then creates fresh player flags and resets scores. All files and folders from the previous round are removed.

## Hosting notes

The SSH port is published as `2222` and the read-only dashboard as `8080` on the host. Open or forward those ports as appropriate for your server, and restrict access to players you trust. The container limits what SSH users can do, but Docker is not a substitute for protecting the host from hostile users or kernel/container-runtime vulnerabilities.
