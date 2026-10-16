import hashlib
import hmac
import os
import pwd
import secrets
import sqlite3
import stat
import tempfile
import time
from pathlib import Path

ARENA = Path(os.environ.get("BASHGAME_ARENA", "/arena"))
STATE_DIR = Path(os.environ.get("BASHGAME_STATE_DIR", "/var/lib/bashgame/players"))
DATABASE = Path(os.environ.get("BASHGAME_DATABASE", "/var/lib/bashgame/scores.sqlite3"))
SESSION_TTL_SECONDS = 8


class GameStateError(Exception):
    pass


def connect():
    return sqlite3.connect(DATABASE, timeout=10)


def initialize_database(usernames):
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = connect()
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS players ("
            "username TEXT PRIMARY KEY, score INTEGER NOT NULL DEFAULT 0)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS online_sessions ("
            "session_id TEXT PRIMARY KEY, "
            "username TEXT NOT NULL REFERENCES players(username), "
            "last_seen REAL NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS power_ups ("
            "username TEXT NOT NULL REFERENCES players(username), "
            "power_up_type TEXT NOT NULL, "
            "acquired_at REAL NOT NULL, "
            "expires_at REAL NOT NULL, "
            "PRIMARY KEY (username, power_up_type))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS jails ("
            "folder_path TEXT PRIMARY KEY, "
            "created_at REAL NOT NULL, "
            "round_number INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS player_locations ("
            "username TEXT NOT NULL REFERENCES players(username), "
            "folder_path TEXT NOT NULL, "
            "last_updated REAL NOT NULL, "
            "is_trapped INTEGER DEFAULT 0, "
            "PRIMARY KEY (username))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS dungeon_metadata ("
            "round_number INTEGER PRIMARY KEY, "
            "dungeon_seed INTEGER, "
            "dungeon_depth INTEGER, "
            "dungeon_width INTEGER, "
            "total_jails INTEGER, "
            "created_at REAL NOT NULL)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS online_sessions_last_seen "
            "ON online_sessions(last_seen)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS jails_round "
            "ON jails(round_number)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS locations_folder "
            "ON player_locations(folder_path)"
        )
        with connection:
            connection.execute("DELETE FROM players")
            connection.executemany(
                "INSERT INTO players (username, score) VALUES (?, 0)",
                [(username,) for username in usernames],
            )
            connection.execute("DELETE FROM online_sessions")
            connection.execute("DELETE FROM power_ups")
            connection.execute("DELETE FROM jails")
            connection.execute("DELETE FROM player_locations")
    finally:
        connection.close()


def _remove_arena_entry(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise GameStateError(f"cannot inspect arena entry '{path.name}': {exc}") from exc
    if stat.S_ISDIR(info.st_mode):
        try:
            with os.scandir(path) as entries:
                children = [Path(entry.path) for entry in entries]
        except OSError as exc:
            raise GameStateError(f"cannot clear arena directory '{path.name}': {exc}") from exc
        for child in children:
            _remove_arena_entry(child)
        try:
            path.rmdir()
        except OSError as exc:
            raise GameStateError(f"cannot remove arena directory '{path.name}': {exc}") from exc
    else:
        try:
            path.unlink()
        except OSError as exc:
            raise GameStateError(f"cannot remove arena entry '{path.name}': {exc}") from exc


def _write_player_flag(username, token, flag_path=None):
    try:
        account = pwd.getpwnam(username)
    except KeyError as exc:
        raise GameStateError(f"no system account exists for player '{username}'") from exc

    flag_path = ARENA / f"{username}.flag" if flag_path is None else flag_path
    try:
        fd = os.open(flag_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
        with os.fdopen(fd, "wb") as flag_file:
            flag_file.write(token)
        os.chown(flag_path, account.pw_uid, account.pw_gid)
        os.chmod(flag_path, 0o660)
    except OSError as exc:
        raise GameStateError(f"cannot create flag for '{username}': {exc}") from exc

    digest_path = STATE_DIR / f"{username}.sha256"
    try:
        fd, temporary_path = tempfile.mkstemp(prefix=f".{username}.", dir=STATE_DIR)
        with os.fdopen(fd, "w", encoding="ascii") as digest_file:
            digest_file.write(hashlib.sha256(token).hexdigest())
        os.chmod(temporary_path, 0o444)
        os.replace(temporary_path, digest_path)
    except OSError as exc:
        raise GameStateError(f"cannot store reset state for '{username}': {exc}") from exc
    finally:
        if "temporary_path" in locals():
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def clear_arena():
    try:
        entries = list(ARENA.iterdir())
    except OSError as exc:
        raise GameStateError(f"cannot list arena for cleanup: {exc}") from exc
    for entry in entries:
        _remove_arena_entry(entry)


def reset_round():
    try:
        connection = connect()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot open game scores: {exc}") from exc

    try:
        connection.execute("BEGIN IMMEDIATE")
        usernames = [
            row[0]
            for row in connection.execute("SELECT username FROM players ORDER BY username")
        ]
        clear_arena()
        
        # Get current round number (increment it)
        current_round = (
            connection.execute("SELECT MAX(round_number) FROM dungeon_metadata").fetchone()[0] or 0
        ) + 1
        
        # Generate dungeon structure
        dungeon = generate_dungeon_structure(depth=3, width=3, jail_probability=0.15)
        jails, total_folders = create_dungeon_folders(dungeon)
        
        # Register jails in database
        for jail_path in jails:
            connection.execute(
                "INSERT OR REPLACE INTO jails (folder_path, created_at, round_number) "
                "VALUES (?, ?, ?)",
                (jail_path, time.time(), current_round)
            )
        
        # Store dungeon metadata
        connection.execute(
            "INSERT INTO dungeon_metadata (round_number, dungeon_seed, dungeon_depth, dungeon_width, total_jails, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (current_round, 0, 3, 3, len(jails), time.time())
        )
        
        # Initialize player locations at root
        connection.execute("DELETE FROM player_locations")
        for username in usernames:
            connection.execute(
                "INSERT INTO player_locations (username, folder_path, last_updated, is_trapped) "
                "VALUES (?, ?, ?, 0)",
                (username, "", time.time())
            )
        
        # Write player flags at root
        for username in usernames:
            _write_player_flag(username, secrets.token_hex(32).encode("ascii"))
        
        connection.execute("UPDATE players SET score = 0")
        connection.execute("DELETE FROM online_sessions")
        connection.execute("DELETE FROM power_ups")
        connection.commit()
        
        # Create random power-ups scattered throughout the dungeon (8-12 total)
        # Place them in random dungeon folders, not just at root
        num_powerups = secrets.randbelow(5) + 8
        power_up_types = list(POWERUP_TYPES.keys())
        
        # Get all dungeon folders
        all_folders = []
        try:
            for directory, subdirectories, _ in os.walk(ARENA, followlinks=False):
                dir_path = Path(directory).relative_to(ARENA)
                if str(dir_path) != ".":
                    all_folders.append(str(dir_path))
        except OSError:
            pass
        
        # If we have folders, place powerups in them; otherwise at root
        for _ in range(num_powerups):
            power_up_type = power_up_types[secrets.randbelow(len(power_up_types))]
            try:
                # Choose random folder or root
                if all_folders and secrets.randbelow(10) < 7:  # 70% chance to place in dungeon
                    folder = all_folders[secrets.randbelow(len(all_folders))]
                    folder_path = ARENA / folder
                else:
                    folder_path = ARENA
                
                # Create powerup file in chosen location
                powerup_file = folder_path / f"powerup_{power_up_type}_{secrets.token_hex(4)}"
                fd = os.open(powerup_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o664)
                with os.fdopen(fd, "w") as f:
                    f.write(power_up_type)
            except (OSError, GameStateError):
                pass  # powerup creation is best-effort
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot reset round scores: {exc}") from exc
    except OSError as exc:
        connection.rollback()
        raise GameStateError(f"cannot reset arena files: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(usernames)


def respawn_player(username):
    try:
        connection = connect()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot open game scores: {exc}") from exc

    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone() is None:
            raise GameStateError(f"unknown player '{username}'")

        hashes = load_player_hashes()
        if username not in hashes:
            raise GameStateError(f"cannot find player state for '{username}'")
        expected_hash = hashes[username]

        def fail_walk(exc):
            raise exc

        try:
            for directory, subdirectories, filenames in os.walk(
                ARENA, followlinks=False, onerror=fail_walk
            ):
                subdirectories[:] = [
                    name
                    for name in subdirectories
                    if not (Path(directory) / name).is_symlink()
                ]
                for filename in filenames:
                    path = Path(directory) / filename
                    if player_for_file(path, hashes) == username:
                        raise GameStateError(f"player '{username}' is already in the game")
        except OSError as exc:
            raise GameStateError(f"cannot inspect game arena: {exc}") from exc

        token = secrets.token_hex(32).encode("ascii")
        flag_path = ARENA / f"{username}.flag"
        try:
            flag_path.lstat()
        except FileNotFoundError:
            pass
        else:
            flag_path = ARENA / f"{username}-respawn-{token[:8].decode('ascii')}.flag"
        _write_player_flag(username, token, flag_path)
        connection.execute(
            "DELETE FROM online_sessions WHERE username = ?", (username,)
        )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot respawn player '{username}': {exc}") from exc
    except OSError as exc:
        connection.rollback()
        raise GameStateError(f"cannot respawn player '{username}': {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_player_hashes():
    hashes = {}
    try:
        files = sorted(STATE_DIR.glob("*.sha256"))
        for path in files:
            username = path.name.removesuffix(".sha256")
            digest = path.read_text(encoding="ascii").strip()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise GameStateError(f"invalid player state for '{username}'")
            hashes[username] = digest
    except OSError as exc:
        raise GameStateError(f"cannot read player state: {exc}") from exc
    return hashes


def player_for_file(path, player_hashes=None):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return None
        contents = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise GameStateError(f"cannot inspect '{path.name}': {exc}") from exc

    file_hash = hashlib.sha256(contents).hexdigest()
    hashes = player_hashes if player_hashes is not None else load_player_hashes()
    for username, expected_hash in hashes.items():
        if hmac.compare_digest(file_hash, expected_hash):
            return username
    return None


def register_session(username, session_id):
    try:
        with connect() as connection:
            connection.execute(
                "INSERT INTO online_sessions (session_id, username, last_seen) "
                "VALUES (?, ?, ?)",
                (session_id, username, time.time()),
            )
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot register online session: {exc}") from exc


def heartbeat_session(session_id):
    try:
        with connect() as connection:
            cursor = connection.execute(
                "UPDATE online_sessions SET last_seen = ? WHERE session_id = ?",
                (time.time(), session_id),
            )
            if cursor.rowcount != 1:
                raise GameStateError("online session is no longer registered")
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot update online session: {exc}") from exc


def unregister_session(session_id):
    try:
        with connect() as connection:
            connection.execute(
                "DELETE FROM online_sessions WHERE session_id = ?",
                (session_id,),
            )
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot unregister online session: {exc}") from exc


def mutate_and_score(actor, path, mutation):
    try:
        connection = connect()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot open game scores: {exc}") from exc
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM players WHERE username = ?", (actor,)
        ).fetchone() is None:
            raise GameStateError(f"unknown player '{actor}'")

        victim = player_for_file(path)
        if victim is not None:
            online = connection.execute(
                "SELECT 1 FROM online_sessions "
                "WHERE username = ? AND last_seen >= ? LIMIT 1",
                (victim, time.time() - SESSION_TTL_SECONDS),
            ).fetchone()
            if online is None:
                raise GameStateError(
                    f"cannot remove or replace '{victim}' while they are offline"
                )
        mutation()
        if victim is not None and victim != actor:
            cursor = connection.execute(
                "UPDATE players SET score = score + 1 WHERE username = ?",
                (actor,),
            )
            if cursor.rowcount != 1:
                raise GameStateError(f"cannot record elimination of '{victim}'")
        connection.commit()
        return victim if victim != actor else None
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot update game scores: {exc}") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def scoreboard():
    try:
        with connect() as connection:
            players = connection.execute(
                "SELECT players.username, players.score, EXISTS ("
                "SELECT 1 FROM online_sessions "
                "WHERE online_sessions.username = players.username "
                "AND online_sessions.last_seen >= ?) "
                "FROM players ORDER BY players.score DESC, players.username",
                (time.time() - SESSION_TTL_SECONDS,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot read game scores: {exc}") from exc

    hashes = load_player_hashes()
    alive_hashes = {digest: username for username, digest in hashes.items()}
    alive = set()

    def fail_walk(exc):
        raise exc

    try:
        for directory, subdirectories, filenames in os.walk(
            ARENA, followlinks=False, onerror=fail_walk
        ):
            subdirectories[:] = [
                name
                for name in subdirectories
                if not (Path(directory) / name).is_symlink()
            ]
            for filename in filenames:
                owner = player_for_file(Path(directory) / filename, hashes)
                if owner is not None:
                    alive.add(owner)
    except OSError as exc:
        raise GameStateError(f"cannot inspect game arena: {exc}") from exc

    return [
        {
            "username": username,
            "score": score,
            "alive": username in alive,
            "online": bool(online),
        }
        for username, score, online in players
    ]


def folder_tree():
    root = {"name": "/arena", "children": []}
    nodes = {Path("."): root}

    def fail_walk(exc):
        raise GameStateError(f"cannot build folder tree: {exc}") from exc

    try:
        for directory, subdirectories, _ in os.walk(
            ARENA, followlinks=False, onerror=fail_walk
        ):
            parent_path = Path(directory).relative_to(ARENA)
            parent = nodes[parent_path]
            subdirectories[:] = sorted(
                name
                for name in subdirectories
                if not (Path(directory) / name).is_symlink()
            )
            for name in subdirectories:
                child_path = parent_path / name
                child = {"name": name, "children": []}
                parent["children"].append(child)
                nodes[child_path] = child
    except OSError as exc:
        raise GameStateError(f"cannot build folder tree: {exc}") from exc
    return root


# Power-ups constants and durations
POWERUP_TYPES = {
    "speed_boost": {"duration": 30, "description": "⚡ Speed Boost (30s)"},
    "shield": {"duration": 40, "description": "🛡️  Shield (40s)"},
    "radar": {"duration": 20, "description": "📡 Radar (20s)"},
}


def acquire_power_up(username, power_up_type):
    """Acquire a power-up for a player."""
    if power_up_type not in POWERUP_TYPES:
        raise GameStateError(f"invalid power-up type: {power_up_type}")

    try:
        with connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO power_ups (username, power_up_type, acquired_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    username,
                    power_up_type,
                    time.time(),
                    time.time() + POWERUP_TYPES[power_up_type]["duration"],
                ),
            )
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot acquire power-up: {exc}") from exc


def get_active_power_ups(username):
    """Get active power-ups for a player."""
    try:
        with connect() as connection:
            connection.execute("DELETE FROM power_ups WHERE expires_at < ?", (time.time(),))
            power_ups = connection.execute(
                "SELECT power_up_type FROM power_ups WHERE username = ? AND expires_at >= ? "
                "ORDER BY power_up_type",
                (username, time.time()),
            ).fetchall()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot read power-ups: {exc}") from exc

    return [row[0] for row in power_ups]


def is_shielded(username):
    """Check if a player has an active shield."""
    try:
        with connect() as connection:
            connection.execute("DELETE FROM power_ups WHERE expires_at < ?", (time.time(),))
            result = connection.execute(
                "SELECT 1 FROM power_ups WHERE username = ? AND power_up_type = 'shield' "
                "AND expires_at >= ? LIMIT 1",
                (username, time.time()),
            ).fetchone()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot check shield status: {exc}") from exc

    return result is not None


def create_power_up_file(power_up_type):
    """Create a power-up file in the arena."""
    if power_up_type not in POWERUP_TYPES:
        raise GameStateError(f"invalid power-up type: {power_up_type}")

    try:
        path = ARENA / f"powerup_{power_up_type}_{secrets.token_hex(4)}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o664)
        with os.fdopen(fd, "w") as f:
            f.write(power_up_type)
    except OSError as exc:
        raise GameStateError(f"cannot create power-up file: {exc}") from exc

    return path


def get_player_radar(username):
    """Get list of online players (radar power-up effect)."""
    try:
        with connect() as connection:
            players = connection.execute(
                "SELECT DISTINCT online_sessions.username FROM online_sessions "
                "WHERE online_sessions.last_seen >= ?",
                (time.time() - SESSION_TTL_SECONDS,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot read online players: {exc}") from exc

    return [row[0] for row in players]


# ============================================================================
# DUNGEON GENERATION & JAIL MECHANICS
# ============================================================================

def initialize_dungeon_database():
    """Add dungeon-related tables to the database."""
    connection = connect()
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS jails ("
            "folder_path TEXT PRIMARY KEY, "
            "created_at REAL NOT NULL, "
            "round_number INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS player_locations ("
            "username TEXT NOT NULL REFERENCES players(username), "
            "folder_path TEXT NOT NULL, "
            "last_updated REAL NOT NULL, "
            "is_trapped INTEGER DEFAULT 0, "
            "PRIMARY KEY (username))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS dungeon_metadata ("
            "round_number INTEGER PRIMARY KEY, "
            "dungeon_seed INTEGER, "
            "dungeon_depth INTEGER, "
            "dungeon_width INTEGER, "
            "total_jails INTEGER, "
            "created_at REAL NOT NULL)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS jails_round "
            "ON jails(round_number)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS locations_folder "
            "ON player_locations(folder_path)"
        )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot create dungeon tables: {exc}") from exc
    finally:
        connection.close()


def generate_dungeon_structure(depth=3, width=3, jail_probability=0.15):
    """
    Generate a random dungeon structure as a tree.
    Creates a proper labyrinth with nested subdirectories.
    
    Returns: dict with 'name', 'children', and 'is_jail' keys
    """
    def generate_node(current_depth, path_prefix=""):
        # Always generate at least to depth-1, then probabilistically continue
        if current_depth >= depth:
            return None
        
        node_name = secrets.choice([
            f"hall_{secrets.randbelow(100)}", 
            f"chamber_{secrets.randbelow(100)}",
            f"vault_{secrets.randbelow(100)}",
            f"passage_{secrets.randbelow(100)}",
            f"cavern_{secrets.randbelow(100)}",
            f"sanctuary_{secrets.randbelow(100)}",
        ])
        
        children = []
        # Generate children up to depth limit
        if current_depth < depth - 1:
            # Generate 2-3 children at intermediate depths
            num_children = secrets.randbelow(width) + 2
        else:
            # At deepest level, still generate some children (makes it more maze-like)
            num_children = max(1, secrets.randbelow(width))
        
        for _ in range(num_children):
            child = generate_node(current_depth + 1, path_prefix + "/" + node_name)
            if child:
                children.append(child)
        
        is_jail = secrets.randbelow(100) < (jail_probability * 100)
        
        return {
            "name": node_name,
            "path": path_prefix + "/" + node_name,
            "children": children,
            "is_jail": is_jail,
            "level": current_depth,
        }
    
    root_children = []
    # Generate 3-4 top-level rooms
    num_root_children = secrets.randbelow(2) + 3
    for _ in range(num_root_children):
        child = generate_node(0, "")
        if child:
            root_children.append(child)
    
    return {
        "name": "root",
        "path": "",
        "children": root_children,
        "is_jail": False,
        "level": 0,
    }


def create_dungeon_folders(dungeon_tree, arena_path=ARENA):
    """Create folder structure in arena based on dungeon tree."""
    jails = []
    total_created = 0
    
    def create_folder_recursive(node, parent_path=None):
        nonlocal total_created
        
        if node["name"] == "root":
            folder_path = arena_path
        else:
            # Create folder under parent
            if parent_path is None:
                folder_path = arena_path / node["name"]
            else:
                folder_path = parent_path / node["name"]
        
        if node["name"] != "root":
            try:
                folder_path.mkdir(exist_ok=True, parents=True)
                total_created += 1
            except OSError as exc:
                raise GameStateError(f"cannot create dungeon folder '{node['name']}': {exc}") from exc
        
        if node["is_jail"]:
            jails.append(str(folder_path.relative_to(arena_path)))
        
        # Recursively create children under this folder
        for child in node.get("children", []):
            create_folder_recursive(child, folder_path)
    
    create_folder_recursive(dungeon_tree)
    return jails, total_created


def register_jails(jails, round_number):
    """Register jail folders in the database."""
    connection = connect()
    try:
        for jail_path in jails:
            connection.execute(
                "INSERT OR REPLACE INTO jails (folder_path, created_at, round_number) "
                "VALUES (?, ?, ?)",
                (jail_path, time.time(), round_number)
            )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot register jails: {exc}") from exc
    finally:
        connection.close()


def is_jail_folder(folder_path):
    """Check if a folder is a jail."""
    connection = connect()
    try:
        result = connection.execute(
            "SELECT 1 FROM jails WHERE folder_path = ?",
            (folder_path,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot check jail status: {exc}") from exc
    finally:
        connection.close()
    
    return result is not None


def trap_player(username, folder_path):
    """Trap a player in a jail."""
    connection = connect()
    try:
        connection.execute(
            "INSERT OR REPLACE INTO player_locations "
            "(username, folder_path, last_updated, is_trapped) "
            "VALUES (?, ?, ?, 1)",
            (username, folder_path, time.time())
        )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot trap player '{username}': {exc}") from exc
    finally:
        connection.close()


def is_player_trapped(username):
    """Check if a player is trapped."""
    connection = connect()
    try:
        result = connection.execute(
            "SELECT folder_path FROM player_locations WHERE username = ? AND is_trapped = 1",
            (username,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot check trap status: {exc}") from exc
    finally:
        connection.close()
    
    return result[0] if result else None


def get_trapped_players(folder_path):
    """Get list of players trapped in a folder."""
    connection = connect()
    try:
        results = connection.execute(
            "SELECT username FROM player_locations WHERE folder_path = ? AND is_trapped = 1",
            (folder_path,)
        ).fetchall()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot get trapped players: {exc}") from exc
    finally:
        connection.close()
    
    return [row[0] for row in results]


def rescue_player(username):
    """Free a trapped player."""
    connection = connect()
    try:
        connection.execute(
            "UPDATE player_locations SET is_trapped = 0 WHERE username = ?",
            (username,)
        )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot rescue player '{username}': {exc}") from exc
    finally:
        connection.close()


def update_player_location(username, folder_path):
    """Update a player's current location in the dungeon."""
    connection = connect()
    try:
        connection.execute(
            "INSERT OR REPLACE INTO player_locations "
            "(username, folder_path, last_updated, is_trapped) "
            "VALUES (?, ?, ?, "
            "  COALESCE((SELECT is_trapped FROM player_locations WHERE username = ?), 0)"
            ")",
            (username, folder_path, time.time(), username)
        )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise GameStateError(f"cannot update player location: {exc}") from exc
    finally:
        connection.close()


def get_all_player_locations():
    """Get current location of all players."""
    connection = connect()
    try:
        results = connection.execute(
            "SELECT username, folder_path, is_trapped FROM player_locations"
        ).fetchall()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot get player locations: {exc}") from exc
    finally:
        connection.close()
    
    return {row[0]: {"folder": row[1], "trapped": bool(row[2])} for row in results}


def get_dungeon_map_for_round():
    """Get the current dungeon structure for visualization."""
    connection = connect()
    try:
        # For now, return basic metadata
        result = connection.execute(
            "SELECT dungeon_depth, dungeon_width, total_jails FROM dungeon_metadata "
            "ORDER BY round_number DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error as exc:
        raise GameStateError(f"cannot get dungeon map: {exc}") from exc
    finally:
        connection.close()
    
    if result:
        return {
            "depth": result[0],
            "width": result[1],
            "total_jails": result[2],
        }
    return {"depth": 0, "width": 0, "total_jails": 0}
