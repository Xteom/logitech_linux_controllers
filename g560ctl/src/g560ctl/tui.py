"""DEAD CODE — legacy G560-only module, not on the runtime path.

Superseded by ``logitech_lighting.tui``. Both console scripts (``g560ctl`` and
``logitech-lighting``) run the ``logitech_lighting`` package; ``g560ctl/cli.py``
is only a thin shim that imports it. This module is retained for reference and
is not wired to any console script — do not extend it.
"""

from __future__ import annotations

from dataclasses import replace

from .colors import PRESET_COLORS, parse_color
from .controller import G560Controller
from .models import Color, G560Error, LightingRequest, Mode, SessionState, ValidationError
from .zones import ZONE_LABELS, resolve_zones

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.message import Message
    from textual.reactive import reactive
    from textual.widgets import (
        Button,
        Checkbox,
        Footer,
        Header,
        Input,
        Label,
        ListItem,
        ListView,
        Select,
        Static,
    )

    TEXTUAL_AVAILABLE = True
except ImportError:  # pragma: no cover
    TEXTUAL_AVAILABLE = False


MODE_OPTIONS = [
    ("Off", Mode.OFF.value),
    ("Solid", Mode.SOLID.value),
    ("Breathe", Mode.BREATHE.value),
    ("Cycle", Mode.CYCLE.value),
]


class SimpleColorPreview(Static):  # pragma: no cover - UI widget
    color_hex = reactive("ff6600")

    def render(self) -> str:
        color = self.color_hex.lower().lstrip("#")
        if len(color) != 6:
            return "Invalid color"
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        block = f"[black on rgb({r},{g},{b})]{' ' * 20}[/]"
        return f"{block}\n#{color.upper()}  rgb({r}, {g}, {b})"


class PresetPressed(Message):  # pragma: no cover - UI message
    def __init__(self, color_hex: str) -> None:
        super().__init__()
        self.color_hex = color_hex


class PresetButton(Button):  # pragma: no cover - UI widget
    def __init__(self, name: str, color_hex: str) -> None:
        super().__init__(name, id=f"preset-{color_hex}")
        self.color_hex = color_hex

    def on_button_pressed(self) -> None:
        self.post_message(PresetPressed(self.color_hex))


class G560Tui(App[None]):  # pragma: no cover - UI app
    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    #left, #middle, #right {
        width: 1fr;
        padding: 1;
    }

    #status {
        height: auto;
        padding: 1;
    }

    .section-title {
        margin-bottom: 1;
        text-style: bold;
    }

    .preset-grid {
        layout: vertical;
    }

    .preset-row {
        height: auto;
    }

    Button {
        margin-bottom: 1;
    }
    """

    def __init__(self, controller: G560Controller) -> None:
        super().__init__()
        self.controller = controller
        self.session = SessionState()
        self.current_request = LightingRequest(
            mode=Mode.SOLID,
            zones=resolve_zones("all"),
            color=Color("ff6600"),
            rate_ms=3000,
            brightness=100,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Ready", id="status")

        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Label("Mode", classes="section-title")
                yield Select(MODE_OPTIONS, value=Mode.SOLID.value, id="mode-select")

                yield Label("Parameters", classes="section-title")
                yield Input(value="ff6600", placeholder="Hex color", id="color-input")
                yield Input(value="3000", placeholder="Rate ms", id="rate-input")
                yield Input(value="100", placeholder="Brightness", id="brightness-input")

            with Vertical(id="middle"):
                yield Label("Zones", classes="section-title")
                for zone, label in ZONE_LABELS.items():
                    checked = zone in self.current_request.zones
                    yield Checkbox(label, value=checked, id=f"zone-{zone.value}")

                yield Button("All zones", id="zones-all")
                yield Button("Clear zones", id="zones-clear")

            with Vertical(id="right"):
                yield Label("Preview", classes="section-title")
                yield SimpleColorPreview(id="preview")
                yield Label("Presets", classes="section-title")

                with Vertical(classes="preset-grid"):
                    for name, color_hex in PRESET_COLORS:
                        yield PresetButton(f"{name} #{color_hex}", color_hex)

                yield Button("Preview", id="preview-button", variant="primary")
                yield Button("Apply", id="apply-button", variant="success")
                yield Button("Restore previous", id="restore-button")
                yield Button("Quit", id="quit-button", variant="error")

        yield Footer()

    def on_mount(self) -> None:
        self._sync_widgets_from_request(self.current_request)

    def on_preset_pressed(self, message: PresetPressed) -> None:
        color_input = self.query_one("#color-input", Input)
        color_input.value = message.color_hex
        self.query_one("#preview", SimpleColorPreview).color_hex = message.color_hex
        self._set_status(f"Preset selected: #{message.color_hex}")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "color-input":
            self.query_one("#preview", SimpleColorPreview).color_hex = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "zones-all":
            for checkbox in self.query(Checkbox):
                if checkbox.id and checkbox.id.startswith("zone-"):
                    checkbox.value = True
            self._set_status("Selected all zones")
        elif button_id == "zones-clear":
            for checkbox in self.query(Checkbox):
                if checkbox.id and checkbox.id.startswith("zone-"):
                    checkbox.value = False
            self._set_status("Cleared zone selection")
        elif button_id == "preview-button":
            self._preview()
        elif button_id == "apply-button":
            self._apply()
        elif button_id == "restore-button":
            self._restore_previous()
        elif button_id == "quit-button":
            self._quit_with_restore()

    def _build_request_from_widgets(self) -> LightingRequest:
        mode_value = self.query_one("#mode-select", Select).value
        mode = Mode(str(mode_value))

        selected_zone_names: list[str] = []
        for checkbox in self.query(Checkbox):
            if checkbox.id and checkbox.id.startswith("zone-") and checkbox.value:
                selected_zone_names.append(checkbox.id.removeprefix("zone-"))

        zones = resolve_zones(selected_zone_names)

        color_text = self.query_one("#color-input", Input).value.strip()
        rate_text = self.query_one("#rate-input", Input).value.strip()
        brightness_text = self.query_one("#brightness-input", Input).value.strip()

        if mode == Mode.OFF:
            return LightingRequest(
                mode=mode,
                zones=zones,
                color=Color("000000"),
            )

        if mode == Mode.SOLID:
            return LightingRequest(
                mode=mode,
                zones=zones,
                color=parse_color(color_text),
            )

        if mode == Mode.BREATHE:
            return LightingRequest(
                mode=mode,
                zones=zones,
                color=parse_color(color_text),
                rate_ms=int(rate_text or "3000"),
                brightness=int(brightness_text or "100"),
            )

        if mode == Mode.CYCLE:
            return LightingRequest(
                mode=mode,
                zones=zones,
                rate_ms=int(rate_text or "8000"),
                brightness=int(brightness_text or "100"),
            )

        raise ValidationError("Unsupported mode")

    def _preview(self) -> None:
        try:
            request = self._build_request_from_widgets()
            self.controller.apply(request)
            self.session.last_previewed = request
            self.current_request = request
            self._set_status("Preview applied")
        except G560Error as exc:
            self._set_status(f"Preview failed: {exc}", error=True)

    def _apply(self) -> None:
        try:
            request = self._build_request_from_widgets()
            self.controller.apply(request)
            self.session.last_committed = request
            self.session.last_previewed = request
            self.current_request = request
            self._set_status("Applied")
        except G560Error as exc:
            self._set_status(f"Apply failed: {exc}", error=True)

    def _restore_previous(self) -> None:
        previous = self.session.last_committed
        if previous is None:
            self._set_status("No committed state to restore", error=True)
            return

        try:
            self.controller.apply(previous)
            self.current_request = previous
            self._sync_widgets_from_request(previous)
            self._set_status("Restored previous committed state")
        except G560Error as exc:
            self._set_status(f"Restore failed: {exc}", error=True)

    def _quit_with_restore(self) -> None:
        previous = self.session.last_committed
        if previous is not None:
            try:
                self.controller.apply(previous)
            except G560Error:
                pass
        self.exit()

    def _sync_widgets_from_request(self, request: LightingRequest) -> None:
        self.query_one("#mode-select", Select).value = request.mode.value

        for checkbox in self.query(Checkbox):
            if checkbox.id and checkbox.id.startswith("zone-"):
                zone_name = checkbox.id.removeprefix("zone-")
                checkbox.value = zone_name in {zone.value for zone in request.zones}

        color_input = self.query_one("#color-input", Input)
        rate_input = self.query_one("#rate-input", Input)
        brightness_input = self.query_one("#brightness-input", Input)
        preview = self.query_one("#preview", SimpleColorPreview)

        if request.color is not None:
            color_input.value = request.color.hex_value
            preview.color_hex = request.color.hex_value

        if request.rate_ms is not None:
            rate_input.value = str(request.rate_ms)

        if request.brightness is not None:
            brightness_input.value = str(request.brightness)

    def _set_status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#status", Static)
        if error:
            status.update(f"[bold red]{text}[/]")
        else:
            status.update(f"[bold green]{text}[/]")


def run_tui(controller: G560Controller) -> int:
    if not TEXTUAL_AVAILABLE:
        print(
            "The TUI requires the optional 'textual' dependency.\n"
            "Install it with: pip install '.[tui]'",
        )
        return 1

    app = G560Tui(controller)
    app.run()
    return 0