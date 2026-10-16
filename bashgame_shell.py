#!/usr/bin/env python3
import contextlib
import hashlib
import hmac
import io
import os
import pwd
import secrets
import select
import shlex
import stat
import sys
import termios
import threading
import time
import tty
import unicodedata
from pathlib import Path, PurePosixPath

import game_state

ARENA = Path(os.environ.get("BASHGAME_ARENA", "/arena"))
STATE_DIR = Path("/var/lib/bashgame/players")
POLL_INTERVAL = 0.1
CURRENT_DIR = ()
WILDCARD_CHARS = frozenset("*?[]")
ANSI_RESET = "\x1b[0m"
ANSI_COLORS = {
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "bold": "\x1b[1m",
}
LOGO = (
    " ____  _____ ____  _   _  ____    _    __  __ _____ ",
    "| __ )| ____|  _ \\| | | |/ ___|  / \\  |  \\/  | ____|",
    "|  _ \\|  _| | |_) | |_| | |  _  / _ \\ | |\\/| |  _|  ",
    "| |_) | |___|  _ <|  _  | |_| |/ ___ \\| |  | | |___ ",
    "|____/|_____|_| \\_\\_| |_|\\____/_/   \\_\\_|  |_|_____|",
)


def welcome_banner_lines(username):
    safe_username = sanitize_terminal_text(username)
    return [
        *LOGO,
        "",
        f"                 WELCOME, {safe_username}",
        f"          KEEP YOUR {safe_username}.flag ALIVE",
        "          ALL-VERSUS-ALL FILE SURVIVAL",
    ]


def print_welcome_banner(username):
    lines = welcome_banner_lines(username)
    if supports_terminal_colors():
        for index, line in enumerate(lines):
            color = ("cyan", "blue", "magenta", "yellow", "green")[index % 5]
            print(f"{ANSI_COLORS[color]}{line}{ANSI_RESET}")
    else:
        print("\n".join(lines))


class CommandError(Exception):
    pass


def supports_terminal_colors(stdout=None, term=None):
    stdout = sys.stdout if stdout is None else stdout
    term = os.environ.get("TERM", "") if term is None else term
    return stdout.isatty() and term.lower() not in ("", "dumb") and "NO_COLOR" not in os.environ


def supports_interactive_terminal(stdin=None, stdout=None, term=None):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    term = os.environ.get("TERM", "") if term is None else term
    return stdin.isatty() and stdout.isatty() and term.lower() not in ("", "dumb")


def sanitize_terminal_text(text):
    return "".join(
        character if not unicodedata.category(character).startswith("C") else "?"
        for character in text
    )


class TerminalUI:
    def __init__(self, username):
        self.username = username
        self.enabled = supports_interactive_terminal()
        self.buffer = bytearray()
        self.old_terminal = None
        self.escape_state = 0

    def __enter__(self):
        if not self.enabled:
            return self
        fd = sys.stdin.fileno()
        self.old_terminal = termios.tcgetattr(fd)
        print_welcome_banner(self.username)
        tty.setraw(fd)
        self.write_message(
            f"PLAYER {self.username}  |  STATUS ALIVE  |  LOCATION /arena",
            "green",
        )
        self.write_message(
            "COMMANDS ls tree find cd pwd touch mkdir mv rm exit  |  NO WILDCARDS",
            "yellow",
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.enabled:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old_terminal)
            sys.stdout.write(ANSI_RESET + "\r\n")
            sys.stdout.flush()
        return False

    def write_message(self, message, color="cyan"):
        safe_message = sanitize_terminal_text(str(message))
        if supports_terminal_colors():
            sys.stdout.write(f"{ANSI_COLORS[color]}{safe_message}{ANSI_RESET}\r\n")
        else:
            sys.stdout.write(safe_message + "\r\n")
        sys.stdout.flush()

    def write_output(self, output, color="cyan"):
        for line in output.splitlines():
            self.write_message(line, color)

    @property
    def input_text(self):
        return self.buffer.decode("utf-8", errors="replace")

    def read_line(self, lost_event):
        fd = sys.stdin.fileno()
        self.buffer.clear()
        cwd = "/arena" + ("/" + "/".join(CURRENT_DIR) if CURRENT_DIR else "")
        prompt = f"{self.username}@bashgame:{cwd}$ "
        if supports_terminal_colors():
            sys.stdout.write(f"{ANSI_COLORS['bold']}{ANSI_COLORS['blue']}{prompt}{ANSI_RESET}")
        else:
            sys.stdout.write(prompt)
        sys.stdout.flush()
        while not lost_event.is_set():
            readable, _, _ = select.select([fd], [], [], 0.2)
            if not readable:
                continue
            data = os.read(fd, 1)
            if not data:
                return None
            for value in data:
                if self.escape_state:
                    if self.escape_state == 1:
                        self.escape_state = 2 if value == ord("[") else 0
                    elif 0x40 <= value <= 0x7e:
                        self.escape_state = 0
                    continue
                if value == 0x1b:
                    self.escape_state = 1
                elif value in (10, 13):
                    result = self.input_text
                    self.buffer.clear()
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return result
                elif value in (8, 127):
                    if self.buffer:
                        self.buffer.pop()
                        while self.buffer:
                            try:
                                self.buffer.decode("utf-8")
                                break
                            except UnicodeDecodeError:
                                self.buffer.pop()
                        os.write(1, b"\b \b")
                elif value == 3:
                    erased = len(self.input_text)
                    self.buffer.clear()
                    os.write(1, b"\b \b" * erased)
                    sys.stdout.write("^C\r\n")
                    sys.stdout.flush()
                elif value == 4:
                    if not self.buffer:
                        return None
                    erased = len(self.input_text)
                    self.buffer.clear()
                    os.write(1, b"\b \b" * erased)
                elif value == 21:
                    erased = len(self.input_text)
                    self.buffer.clear()
                    os.write(1, b"\b \b" * erased)
                elif value >= 32 and len(self.buffer) < 4096:
                    self.buffer.append(value)
                    try:
                        text = self.buffer.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    os.write(1, text[-1].encode("utf-8"))
        return None


def player_token_path(username):
    return ARENA / f"{username}.flag"


def expected_token_hash(username):
    path = STATE_DIR / f"{username}.sha256"
    try:
        digest = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise CommandError(f"cannot read player state: {exc.strerror}") from exc
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise CommandError("invalid player state")
    return digest


def token_matches(path, expected_hash):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CommandError(f"cannot check player file: {exc.strerror}") from exc
    return hmac.compare_digest(digest, expected_hash)


def locate_token(identity, expected_hash):
    directories = [ARENA]
    while directories:
        directory = directories.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise CommandError(f"cannot inspect arena: {exc.strerror}") from exc
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(info.st_mode):
                directories.append(Path(entry.path))
            elif stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity:
                path = Path(entry.path)
                if token_matches(path, expected_hash):
                    return path
    return None


def resolve_path(name):
    path = PurePosixPath(name)
    if path.is_absolute():
        if path.parts[:2] != ("/", "arena"):
            raise CommandError("paths must stay inside /arena")
        parts = []
    else:
        parts = list(CURRENT_DIR)

    for part in path.parts[2:] if path.is_absolute() else path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise CommandError("paths must stay inside /arena")
            parts.pop()
        else:
            parts.append(part)

    resolved = ARENA
    for index, part in enumerate(parts):
        resolved = resolved / part
        try:
            info = resolved.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise CommandError(f"cannot access '{part}': {exc.strerror}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise CommandError("symbolic links are not allowed")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise CommandError(f"'{part}' is not a directory")
    return resolved


def is_arena_directory(name):
    return name in ("", ".", "/", "/arena")


def require_regular_file(path, *, must_exist=True):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if must_exist:
            raise CommandError(f"'{path.name}' does not exist")
        return False
    except OSError as exc:
        raise CommandError(f"cannot access '{path.name}': {exc.strerror}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CommandError("only regular files can be used")
    return True


def command_ls(args):
    if len(args) > 1:
        raise CommandError("usage: ls [path]")
    if not args:
        path = ARENA.joinpath(*CURRENT_DIR)
    elif is_arena_directory(args[0]):
        path = ARENA
    else:
        path = resolve_path(args[0])

    username = pwd.getpwuid(os.getuid()).pw_name
    
    if path == ARENA or path.is_dir():
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name)
        except OSError as exc:
            raise CommandError(f"cannot list directory: {exc.strerror}") from exc
        
        # List directory contents with colors
        colored_entries = []
        for entry in entries:
            if entry.is_dir():
                colored_name = f"{ANSI_COLORS['blue']}{entry.name}/{ANSI_RESET}"
            else:
                colored_name = entry.name
            colored_entries.append(colored_name)
        print("  ".join(colored_entries))
        
        # Check for and acquire powerups in this directory
        powerup_descriptions = []
        for entry in entries:
            if entry.name.startswith("powerup_"):
                try:
                    with open(entry.path, "r") as f:
                        power_up_type = f.read().strip()
                    if power_up_type in game_state.POWERUP_TYPES:
                        game_state.acquire_power_up(username, power_up_type)
                        desc = game_state.POWERUP_TYPES[power_up_type]["description"]
                        powerup_descriptions.append(f"⭐ {desc}")
                except (OSError, game_state.GameStateError):
                    pass
        
        if powerup_descriptions:
            for desc in powerup_descriptions:
                print(desc)
        
        # Show trapped players in this room
        relative_path = str(path.relative_to(ARENA)) if path != ARENA else ""
        try:
            trapped = game_state.get_trapped_players(relative_path)
            if trapped:
                print(f"[🔒 Trapped players: {', '.join(trapped)}]")
        except game_state.GameStateError:
            pass
        return

    require_regular_file(path)
    print(path.name)


def command_tree(args):
    if len(args) > 1:
        raise CommandError("usage: tree [directory]")
    if not args:
        root = ARENA.joinpath(*CURRENT_DIR)
    elif args[0] == ".":
        root = ARENA.joinpath(*CURRENT_DIR)
    elif is_arena_directory(args[0]):
        root = ARENA
    else:
        root = resolve_path(args[0])
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise CommandError(f"cannot access tree root: {exc.strerror}") from exc
    if not stat.S_ISDIR(root_info.st_mode):
        raise CommandError("tree requires a directory")

    print("." if root == ARENA.joinpath(*CURRENT_DIR) else root.name)
    try:
        children = sorted(os.scandir(root), key=lambda entry: entry.name)
        visible_children = [
            entry for entry in children
            if not entry.is_symlink()
            and (entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False))
        ]
        stack = [
            (Path(entry.path), 0, index == len(visible_children) - 1, entry.is_dir(follow_symlinks=False))
            for index, entry in reversed(list(enumerate(visible_children)))
        ]
        while stack:
            path, depth, is_last, is_directory = stack.pop()
            print(f"{'│   ' * depth}{'└── ' if is_last else '├── '}{path.name}")
            if is_directory:
                try:
                    children = sorted(os.scandir(path), key=lambda entry: entry.name)
                except OSError as exc:
                    raise CommandError(f"cannot list '{path.name}': {exc.strerror}") from exc
                child_entries = [
                    entry for entry in children
                    if not entry.is_symlink()
                    and (entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False))
                ]
                stack.extend(
                    (
                        Path(entry.path),
                        depth + 1,
                        index == len(child_entries) - 1,
                        entry.is_dir(follow_symlinks=False),
                    )
                    for index, entry in reversed(list(enumerate(child_entries)))
                )
    except OSError as exc:
        raise CommandError(f"cannot list tree: {exc.strerror}") from exc


def command_find(args):
    if len(args) > 1:
        raise CommandError("usage: find [directory]")
    if not args or args[0] == ".":
        root = ARENA.joinpath(*CURRENT_DIR)
        display_root = "."
    elif is_arena_directory(args[0]):
        root = ARENA
        display_root = "/arena"
    else:
        root = resolve_path(args[0])
        display_root = args[0].rstrip("/") or "."

    try:
        info = root.lstat()
    except OSError as exc:
        raise CommandError(f"cannot access find root: {exc.strerror}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise CommandError("find requires a directory")

    def entries_in(directory):
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise CommandError(f"cannot search '{directory.name}': {exc.strerror}") from exc
        return [
            entry for entry in entries
            if not entry.is_symlink()
            and (entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False))
        ]

    print(display_root)
    stack = list(reversed(entries_in(root)))
    while stack:
        entry = stack.pop()
        relative = Path(entry.path).relative_to(root)
        print(f"{display_root}/{relative.as_posix()}")
        if entry.is_dir(follow_symlinks=False):
            stack.extend(reversed(entries_in(Path(entry.path))))


def command_cd(args):
    if len(args) > 1:
        raise CommandError("usage: cd [directory]")
    global CURRENT_DIR
    
    username = pwd.getpwuid(os.getuid()).pw_name
    
    # CHECK: If player is already trapped, don't allow movement anywhere
    if game_state.is_player_trapped(username):
        raise CommandError("🔒 You are TRAPPED in this room and cannot move! Wait for another player to enter and rescue you!")
    
    if not args:
        CURRENT_DIR = ()
        return
    path = ARENA if is_arena_directory(args[0]) else resolve_path(args[0])
    try:
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise CommandError(f"'{args[0]}' is not a directory")
    except OSError as exc:
        raise CommandError(f"cannot access '{args[0]}': {exc.strerror}") from exc
    
    # Update player location in database
    relative_path = str(path.relative_to(ARENA)) if path != ARENA else ""
    try:
        game_state.update_player_location(username, relative_path)
    except game_state.GameStateError:
        pass  # Location tracking is best-effort
    
    # Check if this is a jail folder
    if game_state.is_jail_folder(relative_path):
        trapped_players = game_state.get_trapped_players(relative_path)
        if trapped_players:
            # Another player is trapped here - rescue them!
            print(f"⭐ You entered a dangerous room and encountered trapped players!")
            for trapped in trapped_players:
                game_state.rescue_player(trapped)
                print(f"🔓 {trapped} has been freed from the trap!")
        else:
            # You just got trapped!
            game_state.trap_player(username, relative_path)
            print(f"🔒 DANGER! You've entered a TRAP ROOM!")
            print(f"You are now trapped in: {relative_path}")
            print(f"💡 Tip: Another player must enter this room to free you!")
            CURRENT_DIR = tuple(path.relative_to(ARENA).parts)
            return
    
    CURRENT_DIR = tuple(path.relative_to(ARENA).parts)


def command_mkdir(args):
    if not args:
        raise CommandError("usage: mkdir directory [directory ...]")
    for name in args:
        path = resolve_path(name)
        try:
            path.mkdir(mode=0o2770)
            path.chmod(0o2770)
        except FileExistsError as exc:
            raise CommandError(f"'{name}' already exists") from exc
        except OSError as exc:
            raise CommandError(f"cannot create directory '{name}': {exc.strerror}") from exc


def command_touch(args):
    if not args:
        raise CommandError("usage: touch file [file ...]")
    for name in args:
        path = resolve_path(name)
        if require_regular_file(path, must_exist=False):
            try:
                os.utime(path, None, follow_symlinks=False)
            except OSError as exc:
                raise CommandError(f"cannot touch '{path.name}': {exc.strerror}") from exc
        else:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o660)
                os.close(fd)
            except OSError as exc:
                raise CommandError(f"cannot create '{path.name}': {exc.strerror}") from exc


def check_power_up(path, username):
    """Check if a file is a power-up and acquire it if so."""
    try:
        if path.name.startswith("powerup_"):
            with open(path, "r") as f:
                power_up_type = f.read().strip()
            if power_up_type in game_state.POWERUP_TYPES:
                game_state.acquire_power_up(username, power_up_type)
                description = game_state.POWERUP_TYPES[power_up_type]["description"]
                return description
    except (OSError, game_state.GameStateError):
        pass
    return None


def command_interact(args):
    """Acquire a power-up when player navigates to its directory."""
    if args:
        raise CommandError("usage: interact")
    username = pwd.getpwuid(os.getuid()).pw_name
    try:
        power_ups = game_state.get_active_power_ups(username)
        if power_ups:
            print("Active power-ups:")
            for power_up_type in power_ups:
                print(f"  {game_state.POWERUP_TYPES[power_up_type]['description']}")
        else:
            print("No active power-ups. Find powerup_* files to gain abilities!")
    except game_state.GameStateError as exc:
        raise CommandError(f"cannot check power-ups: {exc}") from exc


def command_scan(args):
    """Radar power-up: detect online players."""
    if args:
        raise CommandError("usage: scan")
    username = pwd.getpwuid(os.getuid()).pw_name
    try:
        if "radar" not in game_state.get_active_power_ups(username):
            raise CommandError("radar power-up not active (find powerup_radar files)")
        online_players = game_state.get_player_radar(username)
        if online_players:
            print(f"Detected {len(online_players)} online player(s):")
            for player in sorted(online_players):
                print(f"  - {player}")
        else:
            print("No other players online.")
    except game_state.GameStateError as exc:
        raise CommandError(f"cannot scan: {exc}") from exc


def command_mv(args):
    if len(args) != 2:
        raise CommandError("usage: mv source destination")
    source = resolve_path(args[0])
    destination = resolve_path(args[1])
    require_regular_file(source)
    require_regular_file(destination, must_exist=False)
    if source == destination:
        return

    username = pwd.getpwuid(os.getuid()).pw_name
    try:
        victim = game_state.player_for_file(destination)
        if victim and victim != username and game_state.is_shielded(victim):
            raise CommandError(f"cannot move file onto {victim} - they are shielded by powerup!")
    except game_state.GameStateError:
        pass

    def move_file():
        os.replace(source, destination)

    try:
        victim = game_state.mutate_and_score(username, destination, move_file)
    except OSError as exc:
        raise CommandError(f"cannot move '{source.name}': {exc.strerror}") from exc
    if victim:
        print(f"You eliminated {victim}.")
        
    # Check for power-up pickup
    powerup = check_power_up(source, username)
    if powerup:
        print(f"⭐ Power-up acquired: {powerup}")


def command_rm(args):
    if not args:
        raise CommandError("usage: rm file [file ...]")
    for name in args:
        path = resolve_path(name)
        require_regular_file(path)

        username = pwd.getpwuid(os.getuid()).pw_name
        try:
            victim = game_state.player_for_file(path)
            if victim and victim != username and game_state.is_shielded(victim):
                raise CommandError(f"cannot remove '{victim}' - they are shielded by powerup!")
        except game_state.GameStateError:
            pass

        def remove_file():
            path.unlink()

        try:
            victim = game_state.mutate_and_score(username, path, remove_file)
        except OSError as exc:
            raise CommandError(f"cannot remove '{path.name}': {exc.strerror}") from exc
        if victim:
            print(f"You eliminated {victim}.")


def command_pwd(args):
    if args:
        raise CommandError("usage: pwd")
    print("/arena" + ("/" + "/".join(CURRENT_DIR) if CURRENT_DIR else ""))


def command_exit(args):
    if args:
        raise CommandError("usage: exit")
    return False


def command_status(args):
    """Display current dungeon status and player status."""
    if args:
        raise CommandError("usage: status")
    
    username = pwd.getpwuid(os.getuid()).pw_name
    
    # Check if trapped
    trapped_in = game_state.is_player_trapped(username)
    if trapped_in:
        print(f"🔒 STATUS: You are TRAPPED in {trapped_in or 'root'}")
        print(f"   Wait for another player to enter this room to free you!")
    else:
        current_location = "/arena" + ("/" + "/".join(CURRENT_DIR) if CURRENT_DIR else "")
        print(f"✓ STATUS: Free in {current_location}")
    
    # Show dungeon stats
    try:
        dungeon_map = game_state.get_dungeon_map_for_round()
        print(f"\n📍 Dungeon Statistics:")
        print(f"   Depth: {dungeon_map['depth']}")
        print(f"   Width: {dungeon_map['width']}")
        print(f"   Traps: {dungeon_map['total_jails']}")
    except game_state.GameStateError:
        pass
    
    # Show active power-ups
    try:
        powerups = game_state.get_active_power_ups(username)
        if powerups:
            print(f"\n⚡ Active Power-ups:")
            for ptype, remaining in powerups:
                print(f"   {ptype} ({remaining:.0f}s remaining)")
    except game_state.GameStateError:
        pass


def reject_wildcards(words):
    if any(any(character in WILDCARD_CHARS for character in word) for word in words):
        raise CommandError("wildcards are not allowed")


COMMANDS = {
    "ls": command_ls,
    "tree": command_tree,
    "find": command_find,
    "cd": command_cd,
    "pwd": command_pwd,
    "touch": command_touch,
    "mkdir": command_mkdir,
    "mv": command_mv,
    "rm": command_rm,
    "interact": command_interact,
    "scan": command_scan,
    "status": command_status,
    "exit": command_exit,
}


def watch_player_file(identity, expected_hash, username, session_id, lost_event, session_state, interactive):
    def report_failure(message):
        session_state["message"] = message
        lost_event.set()
        if not interactive:
            os.write(1, f"\n{message}\n".encode())
            try:
                game_state.unregister_session(session_id)
            except game_state.GameStateError:
                pass
            os._exit(1)

    next_heartbeat = time.monotonic()
    while True:
        try:
            if locate_token(identity, expected_hash) is None:
                report_failure(f"Your {username}.flag was removed. You are out of the game.")
                return
            if time.monotonic() >= next_heartbeat:
                game_state.heartbeat_session(session_id)
                next_heartbeat = time.monotonic() + 2
        except CommandError as exc:
            report_failure(f"bashgame monitor error: {exc}")
            return
        except game_state.GameStateError as exc:
            report_failure(f"bashgame session error: {exc}")
            return
        time.sleep(POLL_INTERVAL)


def run_interactive_session(username, ui, lost_event, session_state):
    with ui:
        while True:
            line = ui.read_line(lost_event)
            if lost_event.is_set():
                ui.buffer.clear()
                ui.write_message(
                    session_state.get("message", "Your session has ended."),
                    "red",
                )
                return 1
            if line is None:
                return 0
            if not line:
                continue

            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            should_exit = False
            try:
                with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                    words = shlex.split(line)
                    if words:
                        reject_wildcards(words)
                        command, *args = words
                        handler = COMMANDS.get(command)
                        if handler is None:
                            raise CommandError(
                                "command not allowed; use ls, tree, find, cd, pwd, touch, mkdir, mv, rm, interact, scan, or exit"
                            )
                        should_exit = handler(args) is False
            except ValueError as exc:
                ui.write_message(f"bashgame: invalid command syntax: {exc}", "red")
            except CommandError as exc:
                ui.write_message(f"bashgame: {exc}", "red")
            except game_state.GameStateError as exc:
                ui.write_message(f"bashgame: {exc}", "red")
            ui.write_output(stdout_buffer.getvalue(), "cyan")
            ui.write_output(stderr_buffer.getvalue(), "red")
            if should_exit:
                return 0


def main():
    username = pwd.getpwuid(os.getuid()).pw_name
    token_path = player_token_path(username)
    try:
        digest = expected_token_hash(username)
        if not token_matches(token_path, digest):
            print(f"Your {username}.flag is missing or invalid; you are out of the game.", file=sys.stderr)
            return 1
        info = token_path.lstat()
    except (CommandError, OSError) as exc:
        print(f"bashgame: {exc}", file=sys.stderr)
        return 1

    identity = (info.st_dev, info.st_ino)
    session_id = secrets.token_hex(16)
    try:
        game_state.register_session(username, session_id)
    except game_state.GameStateError as exc:
        print(f"bashgame: {exc}", file=sys.stderr)
        return 1

    ui = TerminalUI(username)
    lost_event = threading.Event()
    session_state = {}
    threading.Thread(
        target=watch_player_file,
        args=(identity, digest, username, session_id, lost_event, session_state, ui.enabled),
        daemon=True,
    ).start()

    try:
        if ui.enabled:
            return run_interactive_session(username, ui, lost_event, session_state)

        print_welcome_banner(username)
        print(f"Welcome, {username}. Keep your {username}.flag alive.")
        print("Commands: ls, tree, find, cd, pwd, touch, mkdir, mv, rm, exit. Wildcards are not allowed; paths stay inside /arena.")
        while True:
            try:
                line = input(f"{username}@bashgame:/arena$ ")
            except EOFError:
                return 0
            except KeyboardInterrupt:
                print()
                continue

            try:
                words = shlex.split(line)
                if not words:
                    continue
                reject_wildcards(words)
                command, *args = words
                handler = COMMANDS.get(command)
                if handler is None:
                    raise CommandError("command not allowed; use ls, tree, find, cd, pwd, touch, mkdir, mv, rm, interact, scan, or exit")
                if handler(args) is False:
                    return 0
            except ValueError as exc:
                print(f"bashgame: invalid command syntax: {exc}", file=sys.stderr)
            except CommandError as exc:
                print(f"bashgame: {exc}", file=sys.stderr)
            except game_state.GameStateError as exc:
                print(f"bashgame: {exc}", file=sys.stderr)
    finally:
        try:
            game_state.unregister_session(session_id)
        except game_state.GameStateError as exc:
            print(f"bashgame: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
