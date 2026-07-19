from qutebrowser.config.configfiles import ConfigAPI
from qutebrowser.config.config import ConfigContainer


def apply(config: ConfigAPI, _: ConfigContainer):
    config.bind("<Ctrl-x><Ctrl-e>", "edit-command", mode="command")
