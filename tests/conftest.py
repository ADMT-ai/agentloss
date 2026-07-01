import pytest

from agentloss.core import STORE


@pytest.fixture(autouse=True)
def clean_store():
    """The SDK store is a process-global; isolate every test."""
    STORE.decisions.clear()
    STORE.outcomes.clear()
    yield
    STORE.decisions.clear()
    STORE.outcomes.clear()
