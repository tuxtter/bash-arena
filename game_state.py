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
            "CREATE INDEX IF NOT EXISTS online_sessions_last_seen "
            "ON online_sessions(last_seen)"
        )
        with connection:
            connection.execute("DELETE FROM players")
            connection.executemany(
                "INSERT INTO players (username, score) VALUES (?, 0)",
                [(username,) for username in usernames],
            )
            connection.execute("DELETE FROM online_sessions")
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
        for username in usernames:
            _write_player_flag(username, secrets.token_hex(32).encode("ascii"))
        connection.execute("UPDATE players SET score = 0")
        connection.execute("DELETE FROM online_sessions")
        connection.commit()
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
