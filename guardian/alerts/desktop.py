"""Desktop notification channel — OPT-IN ([desktop] extra) per BUILD-PLAN §3.3.

`desktop-notifier` 6.2.0 with `DesktopNotifierSync`.
macOS requires a SIGNED python.org Python — Homebrew Python silently fails.
"""

from __future__ import annotations


class DesktopChannel:
    name = "desktop"

    def __init__(self, app_name: str = "Webcam Guardian") -> None:
        try:
            from desktop_notifier import DesktopNotifierSync  # optional extra
        except ImportError as e:
            raise RuntimeError(
                "desktop channel needs the [desktop] extra: pip install '.[desktop]'"
            ) from e
        self.notifier = DesktopNotifierSync(app_name=app_name)

    def send(self, title: str, body: str, image_path: str | None = None) -> None:
        self.notifier.send(title=title, message=body)
