import subprocess
import catppuccin
from qutebrowser.config.configfiles import ConfigAPI
from qutebrowser.config.config import ConfigContainer


def get_system_theme() -> str:
    """Return 'dark' or 'light' depending on system theme, or 'light' as fallback."""
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            check=True,
            text=True,
        )
        if "prefer-dark" in result.stdout:
            return "dark"
        return "light"
    except Exception:
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                capture_output=True,
                check=True,
                text=True,
            )
            theme = result.stdout.strip().strip("'\"")
            if theme.lower().endswith("-dark"):
                return "dark"
        except Exception:
            pass
        return "light"


def apply(config: ConfigAPI, c: ConfigContainer):
    theme_style = get_system_theme()
    catppuccin_palette = "mocha" if theme_style == "dark" else "latte"
    catppuccin.setup(c, catppuccin_palette, True)
    config.set("colors.webpage.darkmode.enabled", theme_style == "dark")
    config.set("colors.webpage.bg", "black" if theme_style == "dark" else "white")
