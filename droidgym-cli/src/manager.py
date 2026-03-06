from dataclasses import dataclass, field
from enum import Enum, auto
import os
import socket
import subprocess
import time
from typing import Dict, List, Optional
import re


class EmulatorStatus(Enum):
    OFF = auto()
    INITIALIZING = auto()
    BOOTING = auto()
    READY = auto()
    OFFLINE = auto()
    DEAD = auto()
    LOCKED = auto()


@dataclass
class EmulatorConfig:
    avd_name: str
    port: Optional[int] = None
    cores: int = 2
    memory: int = 768
    headless: bool = True
    read_only: bool = True
    use_snapshot: bool = True
    snapshot_name: str = "default_boot"
    gpu_mode: str = "swiftshader_indirect"
    flags: List[str] = field(default_factory=list)


@dataclass
class EmulatorInstance:
    config: EmulatorConfig
    port: int
    pid: int
    process: subprocess.Popen
    status: EmulatorStatus = EmulatorStatus.INITIALIZING
    start_time: float = field(default_factory=time.time)
    last_connect_attempt: float = 0.0


class EmulatorManager:
    def __init__(self, root_dir: str = ".", log_callback=None):
        # setup local .android_home folder
        self.root_dir = os.path.abspath(root_dir)
        self.android_home = os.path.join(self.root_dir, ".android_home")

        os.makedirs(self.android_home, exist_ok=True)

        self.active: Dict[int, EmulatorInstance] = {}
        self.adb = "adb"
        self.emulator = "emulator"
        self.avdmanager = "avdmanager"

        self.adb_port = int(os.environ.get("ANDROID_ADB_SERVER_PORT", 5037))

        # Loggin
        self.debug = os.environ.get("DROIDGYM_DEBUG", "false").lower() == "true"
        self.log_callback = log_callback

    @property
    def env(self) -> Dict[str, str]:
        # Use .android_home for emulator and avd
        env = os.environ.copy()
        env["ANDROID_USER_HOME"] = self.android_home
        env["ANDROID_EMULATOR_HOME"] = self.android_home
        env["ANDROID_AVD_HOME"] = os.path.join(self.android_home, "avd")
        return env

    def create_avd(
        self,
        name: str,
        sdk: str,
        device: Optional[str] = None,
    ) -> bool:
        # fmt: off
        cmd = [
            self.avdmanager,
            "create", "avd",
            "-n", name,
            "-k", sdk,
            "--force",
        ]
        # fmt: on

        if device:
            cmd.extend(["-d", device])
        try:
            result = self._run_cmd(cmd, input="\n")
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            self._log(f"Failed to create AVD: {e}")
            return False

    def list_avds(self) -> List[str]:
        try:
            result = self._run_cmd([self.emulator, "-list-avds"])
            return [line for line in result.stdout.splitlines() if line.strip()]
        except Exception:
            return []

    def list_snapshots(self, avd_name: str) -> List[str]:
        """List available snapshots for a given AVD."""
        avd_home = self.env.get("ANDROID_AVD_HOME", os.path.join(self.android_home, "avd"))
        snapshots_dir = os.path.join(avd_home, f"{avd_name}.avd", "snapshots")
        if not os.path.isdir(snapshots_dir):
            return []
        return [
            d for d in os.listdir(snapshots_dir)
            if os.path.isdir(os.path.join(snapshots_dir, d))
        ]

    def spawn_emulator(self, config: EmulatorConfig) -> EmulatorInstance:
        port = config.port or self._find_free_port()
        if port in self.active:
            raise ValueError(f"Port {port} is already managed")

        cmd = [
            self.emulator,
            "@" + config.avd_name,
            "-port",
            str(port),
            "-memory",
            str(config.memory),
            "-cores",
            str(config.cores),
            "-accel",
            "on",
            "-gpu",
            config.gpu_mode,
            "-no-audio",
            "-no-boot-anim",
        ]

        if config.headless:
            cmd.append("-no-window")
        if config.read_only:
            cmd.append("-read-only")
        if config.use_snapshot:
            cmd.extend(["-snapshot", config.snapshot_name, "-no-snapshot-save"])
        else:
            cmd.append("-no-snapshot-load")

        cmd.extend(config.flags)

        self._log(f"SPAWNING: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            start_new_session=True,
            text=True,
        )

        instance = EmulatorInstance(
            config,
            port,
            pid=process.pid,
            process=process,
            status=EmulatorStatus.INITIALIZING,
        )
        self.active[port] = instance

        return instance

    def kill_emulators(self, port):
        if port in self.active:
            # Try killing emulator
            try:
                self._run_cmd([self.adb, "-s", f"emulator-{port}", "emu", "kill"])
            except Exception:
                pass

            instance = self.active[port]

            # clean up
            if instance.process.poll() is None:
                instance.process.terminate()

            del self.active[port]

    def check_health(self):
        self._ensure_adb_alive()
        devices = self._get_adb_devices()
        self._log(f"check_health: {devices}")

        for port, instance in self.active.items():
            if instance.process.poll() is not None:
                instance.status = EmulatorStatus.DEAD
                continue

            adb_status = devices.get(port)

            if adb_status == "device":
                instance.status = EmulatorStatus.READY
            elif adb_status == "offline":
                instance.status = EmulatorStatus.OFFLINE
            elif adb_status == "unauthorized":
                instance.status = EmulatorStatus.LOCKED
            else:
                instance.status = EmulatorStatus.BOOTING

    def _find_free_port(self, start_port: int = 6000) -> int:
        # ADB prefers porty 5554-5584
        # But doesnt matter in over case as we are using seriel and
        # only need even ports
        port = start_port
        while port < 7000:
            if port not in self.active and not self._is_port_in_use(port):
                return port
            port += 2
        raise RuntimeError("No free ports for emulator found")

    def _is_port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("localhost", port)) == 0

    def _ensure_adb_alive(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(("127.0.0.1", self.adb_port))
                return True
        except (ConnectionRefusedError, socket.timeout):
            self._log("ADB Server down. Restarting...")
            subprocess.run([self.adb, "start-server"], stdout=subprocess.DEVNULL)
            return False

    def _get_adb_devices(self) -> Dict[int, str]:
        devices = {}
        port_regex = re.compile(r"(?:emulator-|localhost:|127\.0\.0\.1:)(\d+)\b")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", self.adb_port))
                s.sendall(b"000chost:devices")

                status = s.recv(4).decode("utf-8")
                if status != "OKAY":
                    return {}

                len_str = s.recv(4).decode("utf-8")
                if not len_str:
                    return {}
                length = int(len_str, 16)

                data = b""
                while len(data) < length:
                    chunk = s.recv(length - len(data))
                    if not chunk:
                        break
                    data += chunk

                payload = data.decode("utf-8")

                for line in payload.splitlines():
                    match = port_regex.search(line)
                    if match:
                        port = int(match.group(1))
                        status = line.split()[1] if len(line.split()) >= 2 else "unknown"
                        devices[port] = status
        except Exception:
            pass

        return devices

    def _log(self, message: str):
        if self.debug and self.log_callback:
            self.log_callback(message)

    def _run_cmd(
        self, cmd: list[str], input: Optional[str] = None
    ) -> subprocess.CompletedProcess:
        self._log(f"CMD: {' '.join(cmd)}")
        timeout = 300

        res = subprocess.run(
            cmd,
            input=input,
            capture_output=True,
            text=True,
            env=self.env,
            timeout=timeout,
        )

        stdout = res.stdout.strip()
        stderr = res.stderr.strip()

        is_noisy = (
            "already connected" in stdout.lower()
            or "already connected" in stderr.lower()
        )

        if stdout and self.debug and not is_noisy:
            self._log(f"OUT: {stdout}")

        if stderr and self.debug and not is_noisy:
            self._log(f"ERR: {stderr}")

        return res
