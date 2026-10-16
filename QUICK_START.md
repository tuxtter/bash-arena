# Quick Start - Power-ups Guide

## Power-up Cheat Sheet

| Power-up | Duration | File | How to Use | Benefit |
|----------|----------|------|-----------|---------|
| ⚡ Speed Boost | 30s | `powerup_speed_boost_*` | Acquire via `mv` | Faster execution |
| 🛡️  Shield | 40s | `powerup_shield_*` | Acquire via `mv` | Block attacks |
| 📡 Radar | 20s | `powerup_radar_*` | Acquire + use `scan` | Detect players |

## How to Pick Up a Power-up

```bash
# Spot a power-up in the arena
$ ls
alice.flag  powerup_shield_abc123  mydir

# Move it to claim it
$ mv powerup_shield_abc123 mydir/
⭐ Power-up acquired: 🛡️  Shield (40s)

# Or touch a power-up file
$ touch powerup_radar_xyz789
⭐ Power-up acquired: 📡 Radar (20s)
```

## Check Your Active Power-ups

```bash
$ interact
Active power-ups:
  🛡️  Shield (40s)
  ⚡ Speed Boost (30s)
```

## Use Radar to Scan

```bash
# First, acquire a radar power-up
# Then use scan to see who's online
$ scan
Detected 3 online player(s):
  - alice
  - bob
  - charlie
```

## Shield Protection in Action

When someone tries to eliminate you while shielded:

```bash
# Attacker tries to remove your flag
alice@bashgame:/arena$ rm bob.flag
bashgame: cannot remove 'bob' - they are shielded by powerup!

# Attacker tries to move something onto your flag
alice@bashgame:/arena$ mv dummy bob.flag
bashgame: cannot move file onto bob - they are shielded by powerup!
```

## Strategy Tips

### Early Game
- Rush for power-ups after round start
- Power-ups spawn randomly (5-8 per round)
- Use `find .` to search the arena quickly

### Mid Game
- Use Radar to scout before aggressive moves
- Grab Shield when enemies are hunting
- Speed Boost for quick escapes

### Defense
- Stay online while using Shield (40 seconds)
- After Shield expires, move your flag to new location
- Create decoy files to confuse hunters

### Offense
- Use Radar to know when opponents are active
- Coordinate attacks when multiple enemies are shielded
- Hide power-ups to prevent enemies from gaining advantages

## Common Scenarios

**Scenario 1: You Find a Shield**
```bash
$ ls
powerup_shield_abc
$ mv powerup_shield_abc my_safe_zone/
⭐ Power-up acquired: 🛡️  Shield (40s)
# Now you're protected for 40 seconds - use it wisely!
```

**Scenario 2: Radar Detects an Enemy**
```bash
$ interact
Active power-ups:
  📡 Radar (20s)
$ scan
Detected 1 online player(s):
  - bob
# Bob is online - be careful!
```

**Scenario 3: Attack Blocked by Shield**
```bash
$ rm alice.flag
bashgame: cannot remove 'alice' - they are shielded by powerup!
# Alice has a shield - wait for it to expire or find her new flag location
```

## Commands Reference

| Command | Purpose | Requires |
|---------|---------|----------|
| `interact` | See active power-ups | Nothing |
| `scan` | Detect online players | Active radar power-up |
| `ls` | List files/directories | Nothing (standard) |
| `tree` | Show folder tree | Nothing (standard) |
| `find [dir]` | Search for files | Nothing (standard) |
| `pwd` | Show current directory | Nothing (standard) |
| `cd [dir]` | Change directory | Nothing (standard) |
| `mkdir [dir]` | Create directory | Nothing (standard) |
| `touch [file]` | Create/pick up file | Nothing (standard) |
| `mv [src] [dst]` | Move file / pick up power-up | Nothing (standard) |
| `rm [file]` | Delete file / eliminate player | Nothing (standard) |

## FAQ

**Q: Can I hold multiple of the same power-up?**  
A: No, only one of each type. Re-acquiring extends the duration.

**Q: Does shield protect against everything?**  
A: Only against `rm` and `mv` attacks on your flag. You can still move other files.

**Q: Who can see me when I use Radar?**  
A: Only you see the results of `scan`. It's private information.

**Q: What happens when a power-up expires?**  
A: It's automatically removed from the database. You can acquire new ones.

**Q: Do power-ups drop when I'm eliminated?**  
A: No, they disappear when they expire or you pick them up.

**Q: Can I share power-ups with teammates?**  
A: No, each player holds their own power-ups.

## Gameplay Flow Example

```
Round Start
  ↓ (5-8 power-ups spawn)
Find powerup_shield_xyz
  ↓
mv powerup_shield_xyz ./safe_zone
  ↓
⭐ Power-up acquired: 🛡️  Shield (40s)
  ↓
interact → See shield active
  ↓
Hunt for another player
  ↓
Try to eliminate but... blocked by their shield!
  ↓
Use interact to check your remaining shield time
  ↓
Find powerup_radar_abc
  ↓
mv powerup_radar_abc ./
  ↓
⭐ Power-up acquired: 📡 Radar (20s)
  ↓
scan → See bob is online
  ↓
Plan your next move knowing where enemies are!
```

## Performance Notes

Power-ups have minimal performance impact:
- 1 extra database query when attempting to eliminate someone
- Expired power-ups auto-cleaned on each status check
- No background processes or timers needed

---

**Ready to play?** Start a game and hunt for power-ups!
