# Bashgame

Bashgame is a small multiplayer, all-versus-all file survival game. Players connect over SSH using public keys. Everyone can see and move or remove files in the shared arena; each player's `<name>.flag` is their life. Removing a player's flag disconnects them and prevents them from rejoining that round.

Docker provides the isolated game environment. SSH sessions are forced into a command interpreter that supports only `ls`, `tree`, `find`, `cd`, `pwd`, `touch`, `mkdir`, `mv`, `rm`, `interact`, `scan`, `status`, and `exit`. Paths are confined to `/arena`, where players can create shared directories; directory removal, shell operators, wildcard characters (`*`, `?`, `[` and `]`), and other commands are not available. Use `tree` to view the arena's files and directories, or `find [directory]` to list entries under a directory. The dashboard also displays the folder tree. Use `exit` or Ctrl-D to disconnect normally. `mv` can replace an existing file, so moving a file onto another player's flag eliminates them.

SSH sessions open with a static, colorful Bashgame ASCII welcome banner. Interactive terminals use colored status, prompts, command output, and error messages, with no animation. Color is disabled for `TERM=dumb` terminals and when `NO_COLOR` is set. Non-interactive sessions use the normal line-based shell.

Players can be eliminated only while online: `rm` and `mv` cannot remove or replace an offline player's flag. Eliminating an online opponent with either command earns one point for the player who performed the action. Removing or replacing your own flag does not award a point. The live scoreboard shows every player, whether they are connected over SSH, whether they are still in the game, and their elimination count.

## Power-ups

Power-ups are special files hidden throughout the arena that grant temporary abilities when picked up. Find them to gain competitive advantages!

**Available Power-ups:**

- **⚡ Speed Boost** (30 seconds): Cooldown reduction—faster command execution. Found in `powerup_speed_boost_*` files.
- **🛡️  Shield** (40 seconds): Temporary invulnerability—your flag cannot be removed or replaced while active. Found in `powerup_shield_*` files.
- **📡 Radar** (20 seconds): Detect all online players. Use the `scan` command to see who's connected. Found in `powerup_radar_*` files.

**How to Use:**
1. Find power-up files in the arena (e.g., `touch` or `mv` them to acquire).
2. Check active power-ups with `interact` command.
3. Use `scan` command to activate Radar if you have it.

## Dungeons & Trap Rooms

Each round generates a unique **procedurally-generated dungeon** with a multi-layered folder structure. The dungeon includes strategic trap rooms ("jails") that capture players until they're rescued by allies, adding positional and cooperative gameplay.

### Dungeon Features

- **Random Generation**: Different folder hierarchies every round
- **Trap Rooms**: Special folders that trap players until rescued (🔒 marked on the map)
- **Player Tracking**: Real-time visualization of all player positions on the dungeon map
- **Rescue Mechanics**: Work with teammates to free trapped allies
- **Strategic Gameplay**: Risk vs. reward—treasure might be guarded by traps

### Entering & Escaping Traps

```bash
# You enter a trap room
alice$ cd vault_chamber
🔒 You've entered a TRAP ROOM! You are now trapped here.
💡 Another player must enter this room to free you!

# Bob hears your distress and comes to help
bob$ cd vault_chamber
⭐ You entered a dangerous room and encountered trapped players!
🔓 alice has been freed from the trap!

# Now you can move again
alice$ cd ..
✓ Back in main hall
```

### Dungeon Map (Dashboard)

The dashboard shows a live ASCII map of the dungeon with player positions:

```
🗺️  DUNGEON MAP
========================================================
🏠 root/
  ├─ 🚪 hall_north/            [🔴 alice]
  │  ├─ 🔒 vault_deep/         ⚠️  TRAP ACTIVE
  │  └─ 🚪 storage/             [🔴 bob]
  ├─ 🚪 cavern_east/            [🔴 charlie]
  └─ 🚪 treasure_room/
```

**Updates every 3 seconds**, showing where every player is located and which rooms have active traps.

### New Command: `status`

Display your dungeon status and power-ups:

```bash
alice$ status
✓ STATUS: Free in hall_north
⚡ Active Power-ups:
   shield (32s remaining)
   radar (8s remaining)

📍 Dungeon Statistics:
   Depth: 3
   Width: 3
   Traps: 5
```

If trapped:
```bash
alice$ status
🔒 STATUS: You are TRAPPED in vault_deep
   Wait for another player to enter this room to free you!
```

### Trap Rooms & Rescue System

**Trap Mechanics:**
1. When you `cd` into a trap room, you become **trapped** (can't `cd` out)
2. You can still use `ls`, `pwd`, `touch`, and `interact`
3. Another player entering the same room **rescues you automatically**
4. Both players must be online for rescue to work (offline players can't enter)
5. After rescue, you're free to move again

**Strategic Use:**
- **High Risk/High Reward**: Treasure might be in trap-guarded chambers
- **Team Play**: Encourages coordination and communication
- **Dramatic Moments**: Climactic rescues and close calls
- **Map Knowledge**: Learn where traps are to avoid or use them strategically

### Dungeon Exploration Example

```bash
alice$ ls
hall_north  hall_south  cavern_east  treasure_room

alice$ cd hall_north
✓ Room entered safely

alice$ ls
passage_1  vault_north  storage

# Risky choice: go deeper
alice$ cd vault_north
🔒 TRAPPED!

# Meanwhile, bob is exploring
bob$ cd hall_north
bob$ cd passage_1
bob$ cd vault_north
⭐ Encountered trapped players!
🔓 alice has been freed!

alice$ cd ..
# Back to passage_1, ready to continue
alice$ interact
Active power-ups:
  🛡️  Shield (25s)

# Now they hunt other players together...
```



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

The dashboard's **Reset round** button starts a fresh round: it respawns every player, clears arena files and scores, resets power-ups, and disconnects current SSH sessions. Reset requires the dashboard admin password, shown once in the container startup logs (retrieve it with `docker compose logs bashgame | grep 'Dashboard admin password'`). Store it securely. For a public server, put the dashboard behind HTTPS and restrict dashboard access; do not send the admin password over plain HTTP.

An admin can also use the **Respawn** action beside an eliminated player to return that player to the game without clearing the arena or changing any scores. Respawning creates a fresh flag and disconnects any stale SSH sessions; the player can reconnect with their existing SSH key. This action also requires the dashboard admin password.

Use `ls` to look around. Create directories with `mkdir hideout` and enter them with `cd hideout`. Rename your flag often with `mv alice.flag a-new-name`; it remains yours while its contents are preserved, including when moved into a subdirectory. Use `rm bob.flag` to eliminate another player. `touch` can create decoy files. Wildcard characters are rejected rather than expanded.

The round's player list comes from the public keys present when the container starts. Every successful container start clears the arena contents, then creates fresh player flags and resets scores. All files and folders from the previous round are removed. Multiple power-ups spawn randomly each round (5-8 total).

## Hosting notes

The SSH port is published as `2222` and the read-only dashboard as `8080` on the host. Open or forward those ports as appropriate for your server, and restrict access to players you trust. The container limits what SSH users can do, but Docker is not a substitute for protecting the host from hostile users or kernel/container-runtime vulnerabilities.

## Gameplay Examples

### Starting a Session

```
 ____  _____ ____  _   _  ____    _    __  __ _____ 
| __ )| ____|  _ \| | | |/ ___|  / \  |  \/  | ____|
|  _ \|  _| | |_) | |_| | |  _  / _ \ | |\\/| |  _|  
| |_) | |___|  _ <|  _  | |_| |/ ___ \| |  | | |___ 
|____/|_____|_| \_\_| |_|\____/_/   \_\_|  |_|_____|

                 WELCOME, alice
          KEEP YOUR alice.flag ALIVE
          ALL-VERSUS-ALL FILE SURVIVAL
```

### Exploring the Arena

```
alice@bashgame:/arena$ ls
bob.flag  powerup_shield_a1b2  hideout  secret_dir

alice@bashgame:/arena$ tree
.
├── bob.flag
├── powerup_shield_a1b2
├── hideout
│   └── alice.flag
└── secret_dir
    ├── decoy1.txt
    └── decoy2.txt
```

### Picking up a Power-up

```
alice@bashgame:/arena$ mv powerup_shield_a1b2 safe/shield_pickup
⭐ Power-up acquired: 🛡️  Shield (40s)

alice@bashgame:/arena$ interact
Active power-ups:
  🛡️  Shield (40s)
  ⚡ Speed Boost (30s)
```

### Using Radar to Detect Opponents

```
alice@bashgame:/arena$ interact
Active power-ups:
  📡 Radar (20s)

alice@bashgame:/arena$ scan
Detected 2 online player(s):
  - bob
  - charlie
```

### Attempting to Eliminate a Shielded Player

```
alice@bashgame:/arena$ rm bob.flag
bashgame: cannot remove 'bob' - they are shielded by powerup!
```

### Dashboard View

The dashboard at [http://localhost:8080](http://localhost:8080) shows:
- Live player scoreboard with elimination counts
- Connection status (online/offline)
- Game status (alive/eliminated)
- Real-time folder tree visualization
- Reset round controls (admin only)

## Strategy Tips

- **Shield Timing**: Use shields right before risky moves or when enemies are actively hunting.
- **Radar Strategy**: Scout other players' locations before making aggressive moves.
- **Speed Boost**: Speeds up command execution for rapid escapes or attacks.
- **Decoy Files**: Create fake `.flag` files to throw off hunters.
- **Directory Nesting**: Hide your flag multiple directories deep (but remember: shields won't protect against deeper searches).
- **Power-up Competition**: Multiple power-ups spawn each round—rush to find them before enemies do!

