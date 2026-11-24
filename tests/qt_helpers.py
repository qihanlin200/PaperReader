"""Deterministic dialog choices for Qt tests without nested event loops."""
from contextlib import contextmanager
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox


@contextmanager
def choose_message_button(label):
    def execute(dialog):
        button = next((item for item in dialog.buttons() if item.text() == label), None)
        if button is None:
            raise AssertionError(f'No message-box button named {label!r}')
        button.click()
        return dialog.result()

    with patch.object(QMessageBox, 'exec', execute):
        yield
