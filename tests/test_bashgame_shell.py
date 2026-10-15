import importlib.util
import base64
import hashlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "bashgame_shell.py"
SPEC = importlib.util.spec_from_file_location("bashgame_shell", MODULE_PATH)
game = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(game)
DASHBOARD_SPEC = importlib.util.spec_from_file_location(
    "bashgame_dashboard",
    Path(__file__).resolve().parents[1] / "bashgame_dashboard.py",
)
dashboard = importlib.util.module_from_spec(DASHBOARD_SPEC)
DASHBOARD_SPEC.loader.exec_module(dashboard)


class BashgameShellTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_arena = game.ARENA
        self.original_current_dir = game.CURRENT_DIR
        self.original_state_arena = game.game_state.ARENA
        self.original_state_dir = game.game_state.STATE_DIR
        self.original_database = game.game_state.DATABASE
        temp_root = Path(self.temp_dir.name)
        game.ARENA = temp_root / "arena"
        game.ARENA.mkdir()
        game.CURRENT_DIR = ()
        game.game_state.ARENA = game.ARENA
        game.game_state.STATE_DIR = temp_root / "state"
        game.game_state.DATABASE = temp_root / "scores.sqlite3"
        game.game_state.STATE_DIR.mkdir()
        game.game_state.initialize_database(["alice", "bob"])

    def tearDown(self):
        game.ARENA = self.original_arena
        game.CURRENT_DIR = self.original_current_dir
        game.game_state.ARENA = self.original_state_arena
        game.game_state.STATE_DIR = self.original_state_dir
        game.game_state.DATABASE = self.original_database
        self.temp_dir.cleanup()

    def add_player_token(self, username, path):
        contents = f"{username}-private-token".encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        digest = hashlib.sha256(contents).hexdigest()
        (game.game_state.STATE_DIR / f"{username}.sha256").write_text(digest)

    def test_file_paths_are_confined_to_arena_root(self):
        self.assertEqual(game.resolve_path("alice.flag"), game.ARENA / "alice.flag")
        self.assertEqual(game.resolve_path("/arena/alice.flag"), game.ARENA / "alice.flag")
        for path in ("/etc/passwd", "../../../outside", "/arena/../outside"):
            with self.subTest(path=path), self.assertRaises(game.CommandError):
                game.resolve_path(path)

    def test_mkdir_creates_shared_arena_directory_and_supports_nested_paths(self):
        game.command_mkdir(["games"])
        self.assertTrue((game.ARENA / "games").is_dir())
        self.assertEqual((game.ARENA / "games").stat().st_mode & 0o7777, 0o2770)

        game.command_cd(["games"])
        self.assertEqual(game.resolve_path("alice.flag"), game.ARENA / "games" / "alice.flag")
        game.command_mkdir(["round"])
        self.assertTrue((game.ARENA / "games" / "round").is_dir())
        self.assertEqual(game.CURRENT_DIR, ("games",))

    def test_mkdir_rejects_paths_outside_arena(self):
        with self.assertRaises(game.CommandError):
            game.command_mkdir(["../../outside"])

    def test_mkdir_remains_allowlisted(self):
        self.assertIn("mkdir", game.COMMANDS)

    def test_tree_command_lists_nested_files_and_directories(self):
        game.command_mkdir(["hideout"])
        (game.ARENA / "hideout" / "flag").write_text("content")
        (game.ARENA / "readme").write_text("content")
        output = io.StringIO()

        with redirect_stdout(output):
            game.command_tree([])

        self.assertEqual(
            output.getvalue().splitlines(),
            [".", "├── hideout", "│   └── flag", "└── readme"],
        )

    def test_find_lists_nested_files_and_directories(self):
        game.command_mkdir(["hideout"])
        (game.ARENA / "hideout" / "flag").write_text("content")
        (game.ARENA / "readme").write_text("content")
        output = io.StringIO()

        with redirect_stdout(output):
            game.command_find([])

        self.assertEqual(
            output.getvalue().splitlines(),
            [".", "./hideout", "./hideout/flag", "./readme"],
        )

    def test_find_rejects_outside_paths_and_extra_arguments(self):
        with self.assertRaises(game.CommandError):
            game.command_find(["../../outside"])
        with self.assertRaises(game.CommandError):
            game.command_find([".", "extra"])
        with self.assertRaises(game.CommandError):
            game.command_find(["missing"])

    def test_folder_tree_includes_directories_but_not_files_or_symlinks(self):
        game.command_mkdir(["hideout"])
        (game.ARENA / "hideout" / "nested").mkdir()
        (game.ARENA / "hideout" / "flag").write_text("content")
        (game.ARENA / "file").write_text("content")
        try:
            (game.ARENA / "shortcut").symlink_to(game.ARENA / "hideout", target_is_directory=True)
        except OSError:
            self.skipTest("symlinks are unavailable")

        self.assertEqual(
            game.game_state.folder_tree(),
            {
                "name": "/arena",
                "children": [
                    {
                        "name": "hideout",
                        "children": [{"name": "nested", "children": []}],
                    }
                ],
            },
        )

    def test_exit_is_allowlisted_and_exits_without_arguments(self):
        self.assertIn("exit", game.COMMANDS)
        self.assertIs(game.command_exit([]), False)
        with self.assertRaises(game.CommandError):
            game.command_exit(["now"])

    def test_wildcards_are_rejected_in_commands_and_arguments(self):
        for words in (["ls", "*"], ["rm", "player?"], ["touch", "[ab].flag"], ["ls", "dir]"]):
            with self.subTest(words=words), self.assertRaisesRegex(game.CommandError, "wildcards"):
                game.reject_wildcards(words)
        game.reject_wildcards(["ls", "player.flag"])

    def test_interactive_terminal_requires_a_real_non_dumb_tty(self):
        class FakeTerminal:
            def __init__(self, is_tty):
                self._is_tty = is_tty

            def isatty(self):
                return self._is_tty

        self.assertTrue(
            game.supports_interactive_terminal(
                FakeTerminal(True), FakeTerminal(True), term="xterm-256color"
            )
        )
        self.assertFalse(
            game.supports_interactive_terminal(
                FakeTerminal(True), FakeTerminal(True), term="dumb"
            )
        )
        self.assertFalse(
            game.supports_interactive_terminal(
                FakeTerminal(False), FakeTerminal(True), term="xterm"
            )
        )

    def test_color_support_respects_terminal_and_no_color_setting(self):
        class FakeTerminal:
            def isatty(self):
                return True

        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(game.supports_terminal_colors(FakeTerminal(), "xterm"))
            self.assertFalse(game.supports_terminal_colors(FakeTerminal(), "dumb"))
        with patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertFalse(game.supports_terminal_colors(FakeTerminal(), "xterm"))

    def test_terminal_messages_cannot_inject_control_sequences(self):
        self.assertEqual(
            game.sanitize_terminal_text("\x1b[31malert\x07"),
            "?[31malert?",
        )
        self.assertEqual(game.sanitize_terminal_text("\x85message"), "?message")
        self.assertTrue(all(line.isascii() for line in game.LOGO))

    def test_ssh_welcome_banner_includes_ascii_art_and_player_name(self):
        output = io.StringIO()
        with redirect_stdout(output):
            game.print_welcome_banner("alice")

        banner = output.getvalue()
        self.assertIn(game.LOGO[0], banner)
        self.assertIn("WELCOME, alice", banner)
        self.assertIn("KEEP YOUR alice.flag ALIVE", banner)

    def test_welcome_banner_uses_terminal_colors_when_available(self):
        class FakeTerminal(io.StringIO):
            def isatty(self):
                return True

        output = FakeTerminal()
        with patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            with redirect_stdout(output):
                game.print_welcome_banner("alice")

        self.assertIn("\033[36m", output.getvalue())
        self.assertIn("\033[0m", output.getvalue())

    def test_file_marker_can_be_found_inside_created_directories(self):
        game.command_mkdir(["games"])
        marker = game.ARENA / "alice.flag"
        marker.write_text("private-token")
        identity = (marker.stat().st_dev, marker.stat().st_ino)
        moved = game.ARENA / "games" / "hidden"
        marker.rename(moved)

        digest = hashlib.sha256(b"private-token").hexdigest()
        self.assertEqual(game.locate_token(identity, digest), moved)

    def test_marker_follows_rename_and_is_not_confused_by_replacement(self):
        marker = game.ARENA / "alice.flag"
        marker.write_text("private-token")
        identity = (marker.stat().st_dev, marker.stat().st_ino)

        moved = game.ARENA / "hidden-in-plain-sight"
        marker.rename(moved)
        digest = hashlib.sha256(b"private-token").hexdigest()
        self.assertEqual(game.locate_token(identity, digest), moved)

        replacement = game.ARENA / "replacement"
        replacement.touch()
        replacement.replace(moved)
        self.assertIsNone(game.locate_token(identity, digest))

    def test_marker_content_prevents_rejoining_after_recreation(self):
        marker = game.ARENA / "alice.flag"
        marker.write_text("private-token")
        digest = hashlib.sha256(b"private-token").hexdigest()
        self.assertTrue(game.token_matches(marker, digest))
        marker.unlink()
        marker.touch()
        self.assertFalse(game.token_matches(marker, digest))

    def test_removing_opponent_flag_increments_actor_score(self):
        marker = game.ARENA / "bob.flag"
        self.add_player_token("bob", marker)
        game.game_state.register_session("bob", "bob-session")

        victim = game.game_state.mutate_and_score("alice", marker, marker.unlink)

        self.assertEqual(victim, "bob")
        self.assertFalse(marker.exists())
        self.assertEqual(
            [player["score"] for player in game.game_state.scoreboard()],
            [1, 0],
        )

    def test_replacing_opponent_flag_increments_only_attacker(self):
        destination = game.ARENA / "bob.flag"
        self.add_player_token("bob", destination)
        source = game.ARENA / "alice-moved.flag"
        self.add_player_token("alice", source)
        game.game_state.register_session("bob", "bob-session")

        victim = game.game_state.mutate_and_score(
            "alice", destination, lambda: source.replace(destination)
        )

        self.assertEqual(victim, "bob")
        self.assertEqual(game.game_state.player_for_file(destination), "alice")
        scores = {player["username"]: player["score"] for player in game.game_state.scoreboard()}
        self.assertEqual(scores, {"alice": 1, "bob": 0})

    def test_offline_player_cannot_be_eliminated_or_have_flag_replaced(self):
        marker = game.ARENA / "bob.flag"
        self.add_player_token("bob", marker)
        replacement = game.ARENA / "replacement"
        replacement.write_text("replacement")

        with self.assertRaisesRegex(game.game_state.GameStateError, "while they are offline"):
            game.game_state.mutate_and_score("alice", marker, marker.unlink)

        with self.assertRaisesRegex(game.game_state.GameStateError, "while they are offline"):
            game.game_state.mutate_and_score(
                "alice", marker, lambda: replacement.replace(marker)
            )

        self.assertTrue(marker.exists())
        self.assertTrue(replacement.exists())
        players = {
            player["username"]: player
            for player in game.game_state.scoreboard()
        }
        self.assertTrue(players["bob"]["alive"])
        self.assertFalse(players["bob"]["online"])
        self.assertEqual(players["alice"]["score"], 0)

    def test_self_elimination_does_not_award_a_point(self):
        marker = game.ARENA / "alice.flag"
        self.add_player_token("alice", marker)
        game.game_state.register_session("alice", "alice-session")

        victim = game.game_state.mutate_and_score("alice", marker, marker.unlink)

        self.assertIsNone(victim)
        self.assertEqual(
            {player["username"]: player["score"] for player in game.game_state.scoreboard()},
            {"alice": 0, "bob": 0},
        )

    def test_reset_round_clears_arena_respawns_players_and_resets_scores(self):
        with patch(
            "game_state.pwd.getpwnam",
            side_effect=lambda username: SimpleNamespace(
                pw_uid=os.getuid(),
                pw_gid=os.getgid(),
            ),
        ):
            alice_flag = game.ARENA / "alice.flag"
            bob_flag = game.ARENA / "bob.flag"
            self.add_player_token("alice", alice_flag)
            self.add_player_token("bob", bob_flag)
            game.game_state.register_session("bob", "bob-session")
            game.game_state.mutate_and_score("alice", bob_flag, bob_flag.unlink)
            game.game_state.register_session("alice", "active-session")
            decoy_dir = game.ARENA / "hideout"
            decoy_dir.mkdir()
            (decoy_dir / "decoy").write_text("old round")

            self.assertEqual(game.game_state.reset_round(), 2)

        self.assertEqual(
            sorted(path.name for path in game.ARENA.iterdir()),
            ["alice.flag", "bob.flag"],
        )
        hashes = game.game_state.load_player_hashes()
        self.assertTrue(game.game_state.player_for_file(alice_flag, hashes) == "alice")
        self.assertTrue(game.game_state.player_for_file(bob_flag, hashes) == "bob")
        players = {
            player["username"]: player
            for player in game.game_state.scoreboard()
        }
        self.assertEqual(players["alice"]["score"], 0)
        self.assertEqual(players["bob"]["score"], 0)
        self.assertTrue(players["alice"]["alive"])
        self.assertTrue(players["bob"]["alive"])
        self.assertFalse(players["alice"]["online"])

    def test_respawn_player_restores_eliminated_player_without_resetting_scores(self):
        alice_flag = game.ARENA / "alice.flag"
        bob_flag = game.ARENA / "bob.flag"
        self.add_player_token("alice", alice_flag)
        self.add_player_token("bob", bob_flag)
        game.game_state.register_session("bob", "bob-session")
        game.game_state.mutate_and_score("alice", bob_flag, bob_flag.unlink)
        bob_flag.write_text("an unrelated file using the original flag name")

        with patch(
            "game_state.pwd.getpwnam",
            side_effect=lambda username: SimpleNamespace(
                pw_uid=os.getuid(),
                pw_gid=os.getgid(),
            ),
        ):
            game.game_state.respawn_player("bob")

        players = {
            player["username"]: player
            for player in game.game_state.scoreboard()
        }
        self.assertTrue(players["bob"]["alive"])
        self.assertFalse(players["bob"]["online"])
        self.assertEqual(players["alice"]["score"], 1)
        self.assertEqual(players["bob"]["score"], 0)
        self.assertEqual(
            bob_flag.read_text(),
            "an unrelated file using the original flag name",
        )
        self.assertTrue(
            any(
                game.game_state.player_for_file(path) == "bob"
                for path in game.ARENA.iterdir()
            )
        )

    def test_respawn_player_rejects_alive_and_unknown_players(self):
        alice_flag = game.ARENA / "alice.flag"
        self.add_player_token("alice", alice_flag)

        with self.assertRaisesRegex(game.game_state.GameStateError, "already in the game"):
            game.game_state.respawn_player("alice")
        with self.assertRaisesRegex(game.game_state.GameStateError, "unknown player"):
            game.game_state.respawn_player("mallory")

    def test_startup_arena_cleanup_removes_nested_files_and_symlinks(self):
        decoy_directory = game.ARENA / "decoys"
        decoy_directory.mkdir()
        (decoy_directory / "old.txt").write_text("old round")
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("do not remove")
        (game.ARENA / "shortcut").symlink_to(outside, target_is_directory=True)

        game.game_state.clear_arena()

        self.assertEqual(list(game.ARENA.iterdir()), [])
        self.assertTrue((outside / "keep.txt").is_file())

    def test_dashboard_reset_auth_requires_configured_admin_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            password_path = Path(temp_dir) / "admin.password"
            password_path.write_text("test-admin-password")
            with patch.object(dashboard, "ADMIN_PASSWORD_FILE", str(password_path)):
                header = "Basic " + base64.b64encode(
                    b"admin:test-admin-password"
                ).decode("ascii")
                self.assertTrue(dashboard.DashboardHandler._authorized(header))
                self.assertFalse(dashboard.DashboardHandler._authorized("Basic invalid"))
                wrong = "Basic " + base64.b64encode(
                    b"admin:wrong-password"
                ).decode("ascii")
                self.assertFalse(dashboard.DashboardHandler._authorized(wrong))

    def test_dashboard_offers_respawn_for_eliminated_players(self):
        page = dashboard.PAGE.decode("utf-8")
        self.assertIn('respawnButton.textContent = "Respawn"', page)
        self.assertIn('postAdminAction("/api/respawn"', page)

    def test_scoreboard_marks_player_online_while_ssh_session_is_registered(self):
        game.game_state.register_session("alice", "alice-session")

        players = {
            player["username"]: player
            for player in game.game_state.scoreboard()
        }
        self.assertTrue(players["alice"]["online"])
        self.assertFalse(players["bob"]["online"])

        game.game_state.unregister_session("alice-session")
        players = {
            player["username"]: player
            for player in game.game_state.scoreboard()
        }
        self.assertFalse(players["alice"]["online"])

    def test_scoreboard_stops_counting_stale_ssh_sessions(self):
        game.game_state.register_session("bob", "stale-session")
        with game.game_state.connect() as connection:
            connection.execute(
                "UPDATE online_sessions SET last_seen = ? WHERE session_id = ?",
                (0, "stale-session"),
            )

        players = {
            player["username"]: player
            for player in game.game_state.scoreboard()
        }
        self.assertFalse(players["bob"]["online"])

    def test_arena_root_aliases_are_recognized(self):
        for path in ("", ".", "/", "/arena"):
            self.assertTrue(game.is_arena_directory(path))
        self.assertFalse(game.is_arena_directory("/etc"))
        self.assertFalse(game.is_arena_directory("games"))


if __name__ == "__main__":
    unittest.main()
