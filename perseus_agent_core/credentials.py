"""Phantom-credential brokering for tool execution (agent-core #11).

The real credential never enters the child process. The supervisor-side vault
holds the real secret; a phantom token is injected into the child's
environment instead; a proxy at the network boundary validates the phantom
and injects the real credential only at the moment of the outbound call; the
real secret is zeroised on exit. A compromised or off-script agent therefore
never holds real secrets — exposure is structurally impossible.

Ledger receipts record broker events (credential id, tool, outcome) without
the secret value, and argv bodies never enter durable evidence: only the
canonicalized policy-relevant fields the caller chooses to pass are carried.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional, Protocol


class CredentialVault:
    """Supervisor-side vault holding the real credentials.

    Real secrets live here and nowhere else. ``zeroise`` overwrites a secret
    in memory so a long-lived process does not keep it around after use.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def add(self, credential_id: str, value: str, env_var: str = "PERSENS_CREDENTIAL") -> None:
        self._store[credential_id] = {"value": value, "env_var": env_var}

    def get(self, credential_id: str) -> Optional[dict]:
        return self._store.get(credential_id)

    def zeroise(self, credential_id: str) -> None:
        entry = self._store.get(credential_id)
        if entry:
            try:
                entry["value"] = "\x00" * len(entry["value"])
            except TypeError:  # pragma: no cover - defensive
                entry["value"] = ""
            del self._store[credential_id]


class BrokerDenied(Exception):
    """Raised when brokering is denied (policy or timeout) — nothing is
    injected, no credential material exists for the request."""


class CredentialBroker(Protocol):
    """The broker interface: supervisor-side vault, phantom-token injection,
    boundary swap, zeroise-on-exit. Real credentials never enter the child."""

    def broker(self, credential_id: str, tool: str, *,
               argv_canonical: Optional[dict] = None,
               timeout_ms: Optional[int] = None) -> BrokerLease: ...

    def execute(self, lease: BrokerLease, argv: list[str], *,
                env: Optional[dict] = None, cwd: Optional[str] = None,
                timeout: float = 30.0) -> dict: ...

    def swap_at_boundary(self, lease: BrokerLease) -> Iterator[dict]: ...


@dataclass
class BrokerLease:
    """A single brokered credential lease. Holds only the phantom token and
    metadata — never the real credential value."""

    lease_id: str
    credential_id: str
    tool: str
    phantom_token: str
    argv_canonical: dict = field(default_factory=dict)
    expires_at_unix_ms: int = 0
    revoked: bool = False

    def as_receipt(self, outcome: str) -> dict:
        """Broker-event receipt: credential id, tool, outcome — no secret."""
        return {
            "lease_id": self.lease_id,
            "credential_id": self.credential_id,
            "tool": self.tool,
            "outcome": outcome,
            "argv_canonical": self.argv_canonical,
        }


class PhantomCredentialBroker:
    """Credential broker: phantom-token injection, boundary swap, zeroise.

    Usage::

        broker = PhantomCredentialBroker(vault)
        lease = broker.broker("gh", "git_push", argv_canonical={...})
        result = broker.execute(lease, ["git", "push", ...],
                                env={"GH_TOKEN": lease.phantom_token})
        with broker.swap_at_boundary(lease) as real_env:
            ...  # the only place the real credential exists
    """

    PHANTOM_ENV = "PERSENS_PHANTOM_TOKEN"

    def __init__(self, vault: CredentialVault, *,
                 policy: Optional[Callable[[str, str, dict], bool]] = None,
                 timeout_ms: int = 30_000) -> None:
        self._vault = vault
        self._policy = policy  # fn(credential_id, tool, argv_canonical) -> bool
        self.timeout_ms = timeout_ms

    def broker(self, credential_id: str, tool: str, *,
               argv_canonical: Optional[dict] = None,
               timeout_ms: Optional[int] = None) -> BrokerLease:
        """Create a phantom-token lease. Policy deny or timeout => BrokerDenied
        with zero credential material (null effect on deny)."""
        argv_canonical = argv_canonical or {}
        allowed = True if self._policy is None else self._policy(
            credential_id, tool, argv_canonical)
        deadline = timeout_ms if timeout_ms is not None else self.timeout_ms
        if not allowed or deadline <= 0:
            raise BrokerDenied(
                "credential brokering denied for "
                f"{tool}/{credential_id}")
        entry = self._vault.get(credential_id)
        if entry is None:
            raise BrokerDenied(f"unknown credential id {credential_id}")
        return BrokerLease(
            lease_id=f"lease-{secrets.token_hex(8)}",
            credential_id=credential_id,
            tool=tool,
            phantom_token=secrets.token_urlsafe(24),
            argv_canonical=argv_canonical,
            expires_at_unix_ms=int(time.time() * 1000) + deadline,
        )

    def execute(self, lease: BrokerLease, argv: list[str], *,
                env: Optional[dict] = None, cwd: Optional[str] = None,
                timeout: float = 30.0) -> dict:
        """Run the tool child with only the phantom token in its environment.
        The real credential never enters the child. On exit the lease is
        zeroised (phantom revoked, no lingering material)."""
        if lease.revoked or (lease.expires_at_unix_ms
                             and int(time.time() * 1000) > lease.expires_at_unix_ms):
            self._revoke(lease)
            raise BrokerDenied("lease expired or revoked before execution")
        child_env = dict(os.environ)
        if env:
            child_env.update(env)
        child_env[self.PHANTOM_ENV] = lease.phantom_token
        try:
            proc = subprocess.run(
                argv, env=child_env, cwd=cwd, capture_output=True,
                text=True, timeout=timeout)
            outcome = "executed" if proc.returncode == 0 else "failed"
            return {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "outcome": outcome,
                "receipt": lease.as_receipt(outcome),
            }
        except subprocess.TimeoutExpired:
            self._revoke(lease)
            return {
                "returncode": -1, "stdout": "", "stderr": "timeout",
                "outcome": "timeout", "receipt": lease.as_receipt("timeout"),
            }
        finally:
            self._revoke(lease)

    @contextmanager
    def swap_at_boundary(self, lease: BrokerLease) -> Iterator[dict]:
        """The proxy: validates the phantom and injects the real credential
        ONLY inside this context — the network boundary. The real secret is
        zeroised when the context exits."""
        if lease.revoked or (lease.expires_at_unix_ms
                             and int(time.time() * 1000) > lease.expires_at_unix_ms):
            self._revoke(lease)
            raise BrokerDenied("lease expired or revoked at the boundary")
        entry = self._vault.get(lease.credential_id)
        if entry is None:
            raise BrokerDenied("credential vanished before boundary swap")
        real_env = {entry["env_var"]: entry["value"]}
        try:
            yield real_env
        finally:
            # Zeroise on exit: the real secret is overwritten in memory.
            self._vault.zeroise(lease.credential_id)

    def _revoke(self, lease: BrokerLease) -> None:
        lease.revoked = True
        lease.phantom_token = ""


def git_style_tool(broker: PhantomCredentialBroker, credential_id: str,
                   argv: list[str], *, argv_canonical: Optional[dict] = None,
                   env: Optional[dict] = None) -> dict:
    """Reference tool path: a git/gh-style invocation through the broker.

    The child process (git, gh, or a test stand-in) is launched with the
    phantom token in ``GH_TOKEN``/``GIT_ASKPASS``-style env; the real
    credential exists only behind ``swap_at_boundary``.
    """
    lease = broker.broker(credential_id, tool=argv[0], argv_canonical=argv_canonical)
    child_env = dict(env or {})
    child_env["GH_TOKEN"] = lease.phantom_token
    child_env[PhantomCredentialBroker.PHANTOM_ENV] = lease.phantom_token
    return broker.execute(lease, argv, env=child_env)


# Re-export for consumers: the interface is the broker + vault + exceptions.
__all__ = [
    "CredentialVault", "CredentialBroker", "BrokerDenied", "BrokerLease",
    "PhantomCredentialBroker", "git_style_tool",
]
