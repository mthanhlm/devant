"""Bench fixture: the golden symbols/edges live in expected.json next to this file."""
import json


class Store:
    def __init__(self, path):
        self.path = path

    def load(self):
        with open(self.path) as fh:
            return json.load(fh)


class CachedStore(Store):
    def load(self):
        data = super().load()
        return data


def read_config(path):
    store = Store(path)
    return store.load()
