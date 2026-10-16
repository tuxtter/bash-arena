# Dungeon Generation & Visualization Feature

## Overview
Transforms the arena into a procedurally-generated dungeon with:
- Random folder hierarchies (different each round)
- Trap rooms ("jails") that trap players until others enter to rescue them
- Real-time ASCII visualization on the dashboard

## Architecture

### 1. Dungeon Generation (game_state.py)
- **Procedural generation**: Create random folder trees with configurable depth/breadth
- **Jail markers**: Special folders marked with trap metadata in database
- **Spawn algorithm**: Place player flags in random, distributed locations
- **Seed-based**: Use round number as seed for reproducibility (optional)

**New Functions:**
- `generate_dungeon(width, depth, jail_probability)` → folder structure
- `create_dungeon_folders()` → write to filesystem
- `get_dungeon_map()` → return structure for visualization
- `get_player_locations()` → current folder paths of all players
- `try_rescue_player(rescuer_username, trapped_username)` → attempt to free a jailed player

**Database Changes:**
- `jails` table: folder_path, created_at, trapped_players (JSON)
- `player_locations` table: username, current_folder_path, last_updated
- `dungeon_metadata` table: round_number, width, depth, seed

### 2. Jail Mechanics (bashgame_shell.py)
- **Entry detection**: When player `cd` into a jail folder
- **Trap activation**: Lock player in folder
- **Rescue system**: Another player entering triggers rescue prompt
- **State tracking**: Monitor who's trapped and where

**New Command:**
- `rescue` - Free a trapped ally (if you're in their jail)

**Enhanced Commands:**
- `cd` - Check if folder is a jail, trap if so
- `ls` - Show if current folder has trapped players

### 3. Dashboard Visualization (bashgame_dashboard.py)
- **Map rendering**: ASCII art dungeon with rooms and corridors
- **Player positions**: Unicode characters representing each player
- **Real-time updates**: WebSocket or polling for live movement
- **Legend**: Show power-ups, jails, player names
- **Animation**: Smooth transitions as players move

**Map Format:**
```
┌─────────────────────────────────────────┐
│ 🏠 root                                  │
│  ├─ 🚪 hall1                             │
│  │  ├─ 🔒 jail_north (🔴 alice trapped) │
│  │  ├─ 📦 storage    (⚡ power-up)       │
│  │  └─ 🟢 bob                            │
│  ├─ 🚪 hall2                             │
│  │  └─ 🔴 charlie                        │
│  └─ 🌴 treasure_room                     │
│     └─ 🏆 flag.txt                       │
└─────────────────────────────────────────┘
```

**Legend:**
- 🏠 = Root folder
- 🚪 = Regular folder
- 🔒 = Jail (trap folder)
- 🔴 🟢 🔵 = Players
- 🔴 (muted) = Trapped player
- ⚡ = Power-up
- 📦 = Other items

## Gameplay Changes

### Before
- Flat arena with only files
- No positional mechanics
- Simple elimination

### After
- Hierarchical dungeon structure
- Positional gameplay (location matters)
- Risk/reward of exploring jails
- Team rescue mechanics
- Strategic folder control

## Implementation Phases

### Phase 1: Core Generation & Tracking
- [ ] Implement `generate_dungeon()` function
- [ ] Create database schema for jails and locations
- [ ] Modify `reset_round()` to generate dungeon
- [ ] Track player locations as they move

### Phase 2: Jail Mechanics
- [ ] Implement trap detection in `command_cd()`
- [ ] Implement rescue system
- [ ] Add database queries for trap state
- [ ] Update `ls` output to show trapped players

### Phase 3: Dashboard Visualization
- [ ] Create ASCII dungeon renderer
- [ ] Display player positions with characters
- [ ] Show jail locations with visual indicators
- [ ] Real-time updates via API endpoint

### Phase 4: Polish
- [ ] Add dungeon stats to dashboard
- [ ] Implement dungeon complexity settings
- [ ] Create rescue announcement system
- [ ] Performance optimization

## Technical Decisions

### Generation Algorithm
**Random Tree Algorithm:**
1. Start at root
2. For each folder, randomly decide to create 1-3 subfolders
3. Recursively generate to depth N
4. Randomly mark 10-20% of leaf folders as jails

### Trap Mechanics
- Jail = folder marked as trap in database
- Entry = player cd into jail folder
- Trapped = can't cd out (only ls/pwd work)
- Rescue = another player cd into same jail triggers rescue
- Consequences = Risk/reward exploration

### Visualization
- ASCII art using box-drawing characters
- Compact tree notation to fit dashboard
- Update interval: 1-2 seconds
- Handle large dungeons with scrolling/pagination

## Performance Considerations
- Dungeon generation: ~50-100ms (one-time per round)
- Location tracking: O(1) per move operation
- Visualization rendering: ~200-300ms (cached)
- Database: Indexed location lookups

## Future Enhancements
- [ ] Dynamic dungeon difficulty settings
- [ ] Boss rooms with special rules
- [ ] Treasure rooms with rare power-ups
- [ ] Dungeon themes (castle, cave, spaceship)
- [ ] Multi-level dungeons
- [ ] Monster AI that blocks corridors
