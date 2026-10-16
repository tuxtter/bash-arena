# Power-ups Implementation Guide

## Overview

Power-ups are special files that spawn randomly in the arena each round (5-8 total). Players can pick them up by moving or touching them, granting temporary abilities for competitive advantages.

## Power-up Types

### ⚡ Speed Boost (30 seconds)
- **File**: `powerup_speed_boost_XXXX`
- **Effect**: Increases command execution speed
- **Use Case**: Quick escapes or rapid flag repositioning
- **Database**: Stored as `power_up_type = 'speed_boost'` in `power_ups` table

### 🛡️ Shield (40 seconds)
- **File**: `powerup_shield_XXXX`
- **Effect**: Flag becomes temporarily invulnerable
- **Protection**: Blocks both `rm` and `mv` operations that target your flag
- **Use Case**: Defense when enemies are hunting
- **Database**: Stored as `power_up_type = 'shield'` in `power_ups` table
- **Logic**: Checked before allowing flag removal/replacement

### 📡 Radar (20 seconds)
- **File**: `powerup_radar_XXXX`
- **Effect**: Detect all currently online players
- **Usage**: Type `scan` command to see online players
- **Database**: Stored as `power_up_type = 'radar'` in `power_ups` table
- **Query**: Returns all players with active sessions

## Database Schema

New table created in `initialize_database()`:

```sql
CREATE TABLE power_ups (
    username TEXT NOT NULL REFERENCES players(username),
    power_up_type TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY (username, power_up_type)
)
```

## Implementation Details

### Game State Functions (game_state.py)

1. **`acquire_power_up(username, power_up_type)`**
   - Records a power-up acquisition in the database
   - Sets expiration time based on power-up duration
   - Allows replacing existing power-ups of same type (extends duration)

2. **`get_active_power_ups(username)`**
   - Returns list of active power-ups for a player
   - Automatically cleans up expired power-ups from DB
   - Returns empty list if none active

3. **`is_shielded(username)`**
   - Checks if a player has active shield
   - Used by `rm` and `mv` commands before elimination
   - Returns boolean

4. **`create_power_up_file(power_up_type)`**
   - Creates a physical power-up file in arena
   - File name: `powerup_{type}_{random_token}`
   - Readable by all players

5. **`get_player_radar(username)`**
   - Returns list of currently online players
   - Called by `scan` command
   - Filters by session TTL (8 seconds)

### Shell Commands (bashgame_shell.py)

#### New Commands

1. **`interact`** - Check active power-ups
   ```
   usage: interact
   Shows all currently active power-ups with their remaining duration
   ```

2. **`scan`** - Use Radar power-up to detect opponents
   ```
   usage: scan
   Requires active radar power-up
   Lists all online players
   ```

#### Modified Commands

1. **`mv`** - Power-up pickup & shield protection
   - Acquires power-up if moving a power-up file
   - Checks shield status of target player before replacement
   - Shows "⭐ Power-up acquired" message on pickup

2. **`rm`** - Shield protection enforcement
   - Checks if target player has active shield
   - Blocks removal if shielded
   - Error message: "cannot remove 'X' - they are shielded by powerup!"

### Power-up Spawning (game_state.py)

In `reset_round()`:
- Clears all expired power-ups from previous round
- Creates 5-8 random power-ups
- Distribution: randomly selected from all 3 types
- Placement: scattered in arena root directory

## Gameplay Flow

### Acquiring a Power-up
1. Player sees power-up file: `powerup_shield_abc123`
2. Player moves/touches it: `mv powerup_shield_abc123 mydir/`
3. System detects power-up and calls `acquire_power_up()`
4. Player sees: `⭐ Power-up acquired: 🛡️  Shield (40s)`
5. Power-up added to DB with expiration timestamp

### Using a Power-up
1. Player checks active: `interact`
2. See: `🛡️  Shield (40s)` with remaining time
3. Shield automatically blocks attacks for 40 seconds
4. After expiration, attempts auto-deleted from DB

### Radar Detection
1. Player has `powerup_radar_xyz`
2. Type: `scan`
3. System checks for active radar in DB
4. Returns list of online players
5. Shows: "Detected 2 online player(s): alice, bob"

## Edge Cases Handled

- **Power-up Expiration**: DB query auto-cleans expired entries each check
- **Multiple Same Type**: Can only hold one of each type; new acquisition extends duration
- **Shield During Move**: `mv` checks victim's shield status BEFORE attempting move
- **Offline Players Not Shielded**: Only checks online session for shield validation
- **Power-up Rename**: File is consumed on first `mv`/`touch`, doesn't persist if moved away

## Testing Checklist

- [ ] Power-up files spawn on round reset (5-8 total)
- [ ] `interact` shows active power-ups correctly
- [ ] `mv` power-up file triggers acquisition
- [ ] Shield blocks `rm` and `mv` elimination attempts
- [ ] Shield expires after 40 seconds
- [ ] `scan` works with active radar
- [ ] `scan` fails without radar power-up
- [ ] Speed boost command execution (cosmetic for now)
- [ ] Power-ups reset on round reset

