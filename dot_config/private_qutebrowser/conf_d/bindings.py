from qutebrowser.config.configfiles import ConfigAPI
from qutebrowser.config.config import ConfigContainer


def apply(config: ConfigAPI, _: ConfigContainer):
    config.bind("<Ctrl-x><Ctrl-e>", "edit-command", mode="command")
    config.bind(
        "<Alt-j>", "completion-item-focus --history next", mode="command"
    )
    config.bind(
        "<Alt-k>", "completion-item-focus --history prev", mode="command"
    )
