#!/usr/bin/env python3
"""Dungeon visualization for the Bashgame dashboard."""

import os
from pathlib import Path

ARENA = Path(os.environ.get("BASHGAME_ARENA", "/arena"))


def build_tree_structure(directory=None, prefix="", is_last=True, include_files=False):
    """Build an ASCII tree visualization of the dungeon structure."""
    if directory is None:
        directory = ARENA
    
    lines = []
    
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return lines
    
    # Filter to only show folders
    folders = [e for e in entries if (directory / e).is_dir() and not (directory / e).is_symlink()]
    files = [e for e in entries if (directory / e).is_file() and not (directory / e).is_symlink()] if include_files else []
    
    all_items = folders + files
    if not all_items:
        return lines
    
    for index, item in enumerate(all_items):
        is_last_item = index == len(all_items) - 1
        item_path = directory / item
        
        # Determine if it's a folder or file
        is_folder = item_path.is_dir() and not item_path.is_symlink()
        
        # Create the tree connector
        if is_last:
            connector = "└── " if is_last_item else "├── "
            extension = "    " if is_last_item else "│   "
        else:
            connector = "├── " if not is_last_item else "└── "
            extension = "│   " if not is_last_item else "    "
        
        # Add emoji based on type
        emoji = "📁" if is_folder else "📄"
        
        lines.append(prefix + connector + emoji + " " + item)
        
        # Recursively add subfolders
        if is_folder:
            sub_lines = build_tree_structure(
                item_path,
                prefix + extension,
                is_last_item,
                include_files
            )
            lines.extend(sub_lines)
    
    return lines


def create_dungeon_map(player_locations=None, jails=None):
    """
    Create an ASCII dungeon map showing player positions and jails.
    Shows full nested dungeon structure.
    
    Args:
        player_locations: dict of {username: {"folder": path, "trapped": bool}}
        jails: list of jail folder paths
    
    Returns: ASCII string representation of dungeon with players
    """
    if player_locations is None:
        player_locations = {}
    if jails is None:
        jails = []
    
    lines = []
    lines.append("=" * 60)
    lines.append("🗺️  DUNGEON MAP")
    lines.append("=" * 60)
    lines.append("")
    
    def add_folder_tree(directory, prefix="", jails_set=None):
        """Recursively add folders to the map."""
        if jails_set is None:
            jails_set = set(jails)
        
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            return
        
        folders = [
            e for e in entries 
            if (directory / e).is_dir() and not (directory / e).is_symlink()
        ]
        
        for index, folder_name in enumerate(folders):
            is_last = index == len(folders) - 1
            folder_path = directory / folder_name
            
            # Calculate relative path for jail checking
            try:
                rel_path = str(folder_path.relative_to(ARENA))
            except ValueError:
                rel_path = folder_name
            
            is_jail = rel_path in jails_set or f"./{rel_path}" in jails_set
            
            # Count players in this folder
            players_here = [
                username for username, info in player_locations.items()
                if info["folder"] == rel_path
            ]
            
            trapped_here = [
                username for username, info in player_locations.items()
                if info["folder"] == rel_path and info["trapped"]
            ]
            
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            
            # Show folder with jail indicator
            folder_icon = "🔒" if is_jail else "🚪"
            folder_line = prefix + connector + folder_icon + " " + folder_name + "/"
            
            if players_here:
                player_chars = " ".join([f"🔴" for _ in range(len(players_here))])
                folder_line += f" [{player_chars}]"
            
            if is_jail and trapped_here:
                folder_line += " ⚠️ "
            
            lines.append(folder_line)
            
            # Recursively add subfolders (limited depth for readability)
            try:
                depth = len(rel_path.split('/'))
                if depth < 3:  # Limit recursion depth for display
                    add_folder_tree(folder_path, prefix + extension, jails_set)
            except (OSError, ValueError):
                pass
    
    lines.append("🏠 root/")
    try:
        add_folder_tree(ARENA, "", set(jails))
    except OSError:
        lines.append("   (Error loading dungeon)")
    
    lines.append("")
    lines.append("-" * 60)
    lines.append("Legend:")
    lines.append("  🏠 = Root folder")
    lines.append("  🚪 = Regular room")
    lines.append("  🔒 = Trap room")
    lines.append("  🔴 = Player in this room")
    lines.append("  ⚠️  = Trap has trapped players")
    lines.append("-" * 60)
    
    return "\n".join(lines)


def create_compact_dungeon_visualization(player_locations=None):
    """Create a compact single-line representation of dungeon status for API."""
    if player_locations is None:
        player_locations = {}
    
    # Group players by location
    locations_map = {}
    for username, info in player_locations.items():
        folder = info["folder"] or "root"
        if folder not in locations_map:
            locations_map[folder] = []
        locations_map[folder].append({"name": username, "trapped": info["trapped"]})
    
    # Build compact visualization
    result = {
        "locations": locations_map,
        "player_count": len(player_locations),
        "online_locations": list(locations_map.keys()),
    }
    
    return result


def render_tree_for_html(directory=None):
    """Render tree structure as JSON for HTML visualization."""
    if directory is None:
        directory = ARENA
    
    def build_node(path):
        try:
            entries = sorted(os.listdir(path))
        except OSError:
            return {"name": path.name, "children": []}
        
        folders = [e for e in entries if (path / e).is_dir() and not (path / e).is_symlink()]
        files = [e for e in entries if (path / e).is_file() and not (path / e).is_symlink()]
        
        children = []
        for folder in folders:
            child_path = path / folder
            children.append(build_node(child_path))
        
        for file in files:
            children.append({"name": file, "children": [], "is_file": True})
        
        return {
            "name": path.name if path != ARENA else "arena",
            "children": children,
        }
    
    return build_node(directory)
