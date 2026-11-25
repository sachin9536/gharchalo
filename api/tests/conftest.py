"""Shared test setup.

Tests must never read a developer's real Flagsmith: with a server key in api/.env or
api/.env.local, a dashboard change (say tatkal_level = 3) would silently break
unrelated tests. Every test starts with Flagsmith disconnected, so flags fall back to
their built-in defaults. Tests that need Flagsmith behaviour set their own flag values.
"""

import pytest

import config
import flags


@pytest.fixture(autouse=True)
def _flagsmith_disconnected(monkeypatch):
    monkeypatch.setattr(config, "FLAGSMITH_SERVER_KEY", "")
    monkeypatch.setattr(config, "FLAGSMITH_OFFLINE_FILE", "")
    flags.reset_for_tests()
    yield
    flags.reset_for_tests()
