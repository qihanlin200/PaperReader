"""Delay heavyweight PDF/network/keyring imports until their first operation."""
import importlib


class LazyModule:
    def __init__(self, name):
        self._name = name
        self._module = None

    def __getattr__(self, attribute):
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return getattr(self._module, attribute)


fitz = LazyModule('fitz')
httpx = LazyModule('httpx')
keyring = LazyModule('keyring')
