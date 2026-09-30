"""Live LLM tests — require real API keys; excluded from default `make test`."""
import pytest

from src.agents.nodes import llm_triage
from src.services.llm_factory import provider_status

_, _, key_present, _ = provider_status()
needs_key = pytest.mark.skipif(not key_present, reason="no LLM key configured")


@needs_key
def test_llm_triage_vpn():
    d = llm_triage("VPN not connecting",
                   "The VPN client fails with an MFA error on macOS")
    assert d.category == "IT"
