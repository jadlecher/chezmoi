import importlib
import pkgutil
import conf_d
from qutebrowser.config.configfiles import ConfigAPI
from qutebrowser.config.config import ConfigContainer

# Suppress linter errors
config: ConfigAPI = config  # noqa: F821 # pyright: ignore[reportUndefinedVariable]
c: ConfigContainer = c  # noqa: F821 # pyright: ignore[reportUndefinedVariable]

config.load_autoconfig()
for module_info in pkgutil.iter_modules(conf_d.__path__):
    module = importlib.import_module(f"conf_d.{module_info.name}")
    if hasattr(module, "apply"):
        module.apply(config, c)

# Configure FreeIPA Kerberos SPNEGO only for the modeled authentik endpoint.
c.qt.args = [
    "auth-server-allowlist=sso.apps.k8s.infrastructure.lab.example.com",
    "auth-negotiate-delegate-allowlist=sso.apps.k8s.infrastructure.lab.example.com",
]

# Set nvim as the default editor
c.editor.command = [
    "kitty",
    "-o",
    "allow_remote_control=yes",
    "nvim",
    "-f",
    "{file}",
    "-c",
    "normal {line}G{column0}l",
]

google = "www.google.com"
c.url.start_pages = [google]
c.url.default_page = google
c.url.searchengines = {
    "DEFAULT": "https://google.com/search?hl=en&q={}",
}
