import pytest

from _helpers import FakeLLM


@pytest.fixture
def fake_llm():
    return FakeLLM()
