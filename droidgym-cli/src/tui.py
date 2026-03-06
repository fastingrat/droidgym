import os

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
)

from manager import EmulatorConfig, EmulatorManager, EmulatorStatus


class CreateAVDScreen(ModalScreen[tuple[str, str, str]]):
    def compose(self) -> ComposeResult:
        yield Container(
            Label("Create New AVD"),
            Input(placeholder="Name", id="name"),
            Input(
                placeholder="SDK",
                value="system-images;android-33;google_apis;arm64-v8a",
                id="sdk",
            ),
            Label("Orientation"),
            Select([("Landscape", "medium_tablet"), ("Potrait", "medium_phone")], value="medium_tablet", id="device"),
            Horizontal(
                Button("Create", variant="primary", id="create"),
                Button("Cancel", variant="error", id="cancel"),
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            name = self.query_one("#name", Input).value
            sdk = self.query_one("#sdk", Input).value
            device = self.query_one("#device", Select).value
            if name and sdk:
                self.dismiss((name, sdk, device))
        else:
            self.dismiss(None)


class SpawnScreen(ModalScreen[EmulatorConfig]):
    CSS = """
    SpawnScreen {
        align: center middle;
    }

    #dialog {
        padding: 1 2;
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
    }

    .field {
        margin-bottom: 1;
    }
    """

    def __init__(self, avd_list: list[str], manager: EmulatorManager):
        super().__init__()
        self.avd_list = avd_list
        self.manager = manager

    def compose(self) -> ComposeResult:
        avd_options = [(a, a) for a in self.avd_list]
        first_avd = self.avd_list[0] if self.avd_list else None
        snapshot_options = self._get_snapshot_options(first_avd)
        yield Container(
            Label("Spawn New Emulator", classes="header"),
            Label("AVD Image:"),
            Select(
                avd_options,
                id="avd_select",
                value=first_avd,
            ),
            Label("Memory (MB):"),
            Input("768", id="memory_input", type="integer"),
            Horizontal(
                Checkbox("Headless", True, id="headless_chk"),
                Checkbox("Read Only", True, id="read_only_chk"),
                Checkbox("Use Snapshot", True, id="use_snapshot_chk"),
                classes="field",
            ),
            Label("Snapshot:"),
            Select(
                snapshot_options,
                id="snapshot_select",
                allow_blank=True,
            ),
            Horizontal(
                Button("Spawn", variant="primary", id="spawn"),
                Button("Cancel", variant="error", id="cancel"),
                classes="buttons",
            ),
            id="dialog",
        )

    def _get_snapshot_options(self, avd_name: str | None) -> list[tuple[str, str]]:
        if not avd_name:
            return []
        snapshots = self.manager.list_snapshots(avd_name)
        return [(s, s) for s in snapshots] if snapshots else []

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "avd_select":
            snapshot_select = self.query_one("#snapshot_select", Select)
            options = self._get_snapshot_options(event.value)
            snapshot_select.set_options(options)
            if not options:
                snapshot_select.clear()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "spawn":
            try:
                name = self.query_one("#avd_select", Select).value
                mem = int(self.query_one("#memory_input", Input).value)
                headless = self.query_one("#headless_chk", Checkbox).value
                readonly = self.query_one("#read_only_chk", Checkbox).value
                use_snapshot = self.query_one("#use_snapshot_chk", Checkbox).value
                snapshot_name = self.query_one("#snapshot_select", Select).value
                if not name:
                    self.notify("Please select an AVD", severity="error")
                    return

                config = EmulatorConfig(
                    avd_name=name,
                    memory=mem,
                    headless=headless,
                    read_only=readonly,
                    use_snapshot=use_snapshot,
                    snapshot_name=snapshot_name if use_snapshot and snapshot_name != Select.BLANK else "default_boot",
                )

                self.dismiss(config)
            except ValueError:
                self.notify("Invalid input", severity="error")


class DroidGymApp(App):
    CSS = """
    Screen {
        height: 50%;
    }

    RichLog {
        height: 30%;
        border: solid $secondary;
        background: $surface;
    }

    DataTable {
        height: 1fr;
        border: solid $accent;
    }
    """

    BINDINGS = [
        ("c", "create_avd", "Create AVD"),
        ("k", "kill", "Kill Selected"),
        ("q", "quit", "Quit"),
        ("r", "refresh", "Force Refresh"),
        ("s", "spawn", "Spawn Emulator"),
    ]

    def __init__(self):
        super().__init__()
        self.debug_mode = os.environ.get("DROIDGYM_DEBUG", "false").lower() == "true"
        self.manager = EmulatorManager(log_callback=None)

    def compose(self) -> ComposeResult:
        yield Header()
        if self.debug_mode:
            log = RichLog(id="logs", highlight=True, markup=True)
            log.can_focus = True
            yield log
        yield DataTable(id="device_table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        if self.debug_mode:
            log_widget = self.query_one("#logs", RichLog)
            log_widget.clear()
            self.manager.log_callback = log_widget.write
        table = self.query_one(DataTable)
        table.add_columns("Port", "AVD", "PID", "Status", "Memory")

        self.set_interval(5.0, self.update_table)
        self.update_table()

    @work(exclusive=True)
    async def update_table(self):
        self.manager.check_health()

        table = self.query_one(DataTable)

        table.clear()

        for port, instance in self.manager.active.items():
            status_style = (
                "green" if instance.status == EmulatorStatus.READY else "yellow"
            )

            if instance.status == EmulatorStatus.DEAD:
                status_style = "red"

            table.add_row(
                str(port),
                instance.config.avd_name,
                str(instance.pid),
                f"[{status_style}]{instance.status.name}[/]",
                f"{instance.config.memory} MB",
                key=str(port),
            )

    def action_spawn(self):
        avds = self.manager.list_avds()
        if not avds:
            self.notify(
                "No AVDs found! \n Create one with `c`",
                severity="warning",
            )
            return

        def handle_submit(config: EmulatorConfig):
            if config:
                try:
                    self.manager.spawn_emulator(config)
                    self.notify(f"Spawing {config.avd_name}")
                    self.update_table()
                except Exception as e:
                    self.notify(f"Spawn failed: {e}", severity="error")
                    self.manager._log(f"SPAWN ERROR: {e}")

        self.push_screen(SpawnScreen(avds, self.manager), handle_submit)

    def action_kill(self):
        table = self.query_one(DataTable)
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if row_key:
                port = int(row_key.value)
                self.manager.kill_emulators(port)
                self.notify(f"Killed instance on port {port}")
                self.update_table()
        except Exception:
            self.notify("No selection", severity="warning")

    def action_create_avd(self):
        def handle_create(result):
            if result:
                name, sdk, device = result
                self.run_avd_creation(name, sdk, device)

        self.push_screen(CreateAVDScreen(), handle_create)

    @work(thread=True)
    def run_avd_creation(self, name: str, sdk: str, device: str):
        try:
            self.notify(f"Starting AVD creation: {name}..")
            self.manager._log("TUI device: {device}")
            sucess = self.manager.create_avd(name, sdk, device)

            if sucess:
                self.notify(
                    f"AVD `{name}` created successfully", severity="information"
                )
            else:
                self.notify(f"Failed to create AVD `{name}`", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
            self.manager._log(f"CRITICAL ERROR: {e}")


if __name__ == "__main__":
    app = DroidGymApp()
    app.run(inline=True)
