# DroidGym
An android emulator orchestrator for RL and agentic needs.

### Prerequisites
- **OS**: macOS only (for now)
- **Environment**: Nix (Flakes enabled)
- **Package Manager**: UV

### Setup
1. Enter Nix environment:
   ```bash
   nix develop --command fish
   ```
2. Install dependencies:
   ```bash
   uv sync
   ```

### Running
1. Launch TUI:
   ```bash
   DROIDGYM_DEBUG=true uv run droidgym-cli/src/tui.py
   ```

### Manual Interaction
- List devices: `adb devices -l`
- Target specific emulator: `adb -s emulator-6000 <cmd>`
- View screen: `scrcpy -s emulator-6000`
- Kill instance: `adb -s emulator-6000 emu kill`

### Implementation Rules
- Always use **even ports** (6000, 6002, ...) to prevent ADB pairing conflicts.
- **No `adb connect`**: The orchestrator relies on auto-discovery; manual connects cause ghost/offline devices.
- Uses local `.android_home` for sandbox isolation.
