"""Phantom-credential brokering (agent-core #11) tests.

Asserts the core guarantee: the child process never holds the real
credential — only the phantom token; the boundary swap injects the real
credential and zeroises it on exit; denied/aborted paths leave no credential
material; and the ledger receipt records the broker event without the secret.
"""
import json
import os
import subprocess
import sys

import pytest

from perseus_agent_core.credentials import (
    BrokerDenied, CredentialVault, PhantomCredentialBroker, git_style_tool,
)

REAL = "ghp_S3cr3t-Value-That-Must-Never-Leak"
_ENV_PROBE = (
    "import json, os; print(json.dumps({k: os.environ.get(k) for k in"
    " ['GH_TOKEN', 'PERSENS_PHANTOM_TOKEN', 'PERSENS_CREDENTIAL']}))"
)


def _broker(**kw):
    vault = CredentialVault()
    vault.add("gh", REAL, env_var="PERSENS_CREDENTIAL")
    return PhantomCredentialBroker(vault, **kw), vault


# --------------------------- child never holds the real credential ----------
def test_child_process_holds_only_phantom_token():
    broker, _ = _broker()
    lease = broker.broker("gh", "git")
    phantom = lease.phantom_token  # captured before execute zeroises the lease
    result = broker.execute(
        lease, [sys.executable, "-c", _ENV_PROBE],
        env={"GH_TOKEN": phantom})
    child_env = json.loads(result["stdout"])
    assert child_env["GH_TOKEN"] == phantom
    assert child_env["PERSENS_PHANTOM_TOKEN"] == phantom
    assert child_env["PERSENS_CREDENTIAL"] is None, \
        "the real credential must never enter the child"
    assert REAL not in json.dumps(result), "real secret must not leak via output"
    assert lease.phantom_token == "", "lease phantom must be zeroised on exit"


def test_reference_git_style_tool_runs_child_with_phantom_only():
    broker, _ = _broker()
    result = git_style_tool(broker, "gh", [sys.executable, "-c", _ENV_PROBE])
    child_env = json.loads(result["stdout"])
    assert child_env["GH_TOKEN"], "phantom token injected as the tool credential"
    assert child_env["PERSENS_CREDENTIAL"] is None, \
        "the real credential must never enter the child"
    assert result["outcome"] == "executed"
    assert REAL not in result["receipt"]


# --------------------------------- boundary swap + zeroise on exit ----------
def test_boundary_swap_injects_real_credential_and_zeroises_on_exit():
    broker, vault = _broker()
    lease = broker.broker("gh", "git")
    with broker.swap_at_boundary(lease) as real_env:
        assert real_env["PERSENS_CREDENTIAL"] == REAL, \
            "the real credential exists only inside the boundary"
    # Zeroise on exit: the vault no longer holds the secret.
    assert vault.get("gh") is None, "real credential must be zeroised after use"


def test_aborted_path_leaves_no_credential_material():
    broker, vault = _broker()
    lease = broker.broker("gh", "git")
    lease.revoked = True  # aborted before execution
    with pytest.raises(BrokerDenied):
        with broker.swap_at_boundary(lease):
            pass  # pragma: no cover
    assert vault.get("gh") is not None  # never swapped => never leaked
    assert lease.phantom_token == ""  # phantom revoked


# ------------------------------------ denied path is null-effect ------------
def test_policy_deny_raises_with_no_credential_material():
    broker, vault = _broker(
        policy=lambda credential_id, tool, argv: tool != "rm")
    with pytest.raises(BrokerDenied):
        broker.broker("gh", "rm", argv_canonical={"path": "/etc"})
    # Denied before any lease: no phantom, no swap, secret untouched in vault.
    assert vault.get("gh") is not None


def test_timeout_resolves_to_deny():
    broker, _ = _broker()
    with pytest.raises(BrokerDenied):
        broker.broker("gh", "git", timeout_ms=0)


# ----------------------------------------- receipts never carry secrets ----
def test_receipt_records_broker_event_without_secret():
    broker, _ = _broker()
    lease = broker.broker("gh", "git", argv_canonical={"action": "push"})
    phantom = lease.phantom_token  # captured before execute zeroises the lease
    result = broker.execute(
        lease, [sys.executable, "-c", _ENV_PROBE],
        env={"GH_TOKEN": phantom})
    receipt = result["receipt"]
    assert receipt["credential_id"] == "gh"
    assert receipt["tool"] == "git"
    assert receipt["outcome"] in ("executed", "failed")
    assert receipt["argv_canonical"] == {"action": "push"}
    blob = json.dumps(receipt)
    assert REAL not in blob, "receipt must never contain the secret value"
    assert phantom not in blob, \
        "receipt must never contain the phantom token either"
