# Decision record: request-bound credential proof (DPoP-style) for agent tool calls

Status: decision record — evaluation only, no implementation commitment
Date: 2026-08-04
Resolves: #13
Related: phantom-credential brokering (#11) ·
ledger two-layer integrity (ledger#206) ·
Vault AAR control plane (perseus-vault#768)

## Decision

**Adopt the request-bound proof-of-possession concept at the tool boundary
and in the credential broker** — a proof that the caller held the key *for
this specific request* — implemented as a lightweight binding, **not** as the
full OAuth DPoP stack. Request-binding belongs in **both** places: the tool
boundary defines and signs the request context; the credential broker
consumes and verifies the proof at the phantom-token swap, refusing the swap
when the binding does not match the request. Delivery is tracked as a
follow-up issue so the binding layer is explicit and testable rather than
silently folded into the broker's first slice.

## Why request-bound and not session-bound

| Threat | Session-bound proof | Request-bound proof |
|---|---|---|
| Replay | A captured session token is usable for any later request in the session | Each proof is bound to one request (request id / one-time nonce); replay across requests fails |
| Tamper | Session token says nothing about what the request *was*; argv can be swapped after capture | The proof commits to canonicalized request fields (actor, boundary, tool, policy-relevant argv, credential id); any swap breaks the binding |
| Cross-request leakage | A leaked session credential authorizes everything the session could do | A leaked proof authorizes exactly one request, then expires |
| Ledger value | Receipt can only say "a session was used" | Receipt can say "this specific request was proven to the broker", with a binding digest |

The manifest authority model is agent/workspace manifests — a different
identity domain from OAuth. What transfers is the *binding discipline*, not
the OAuth machinery.

## Where the binding lives

1. **Tool boundary** — the tool layer canonicalizes the request (actor,
   boundary, tool, canonicalized policy-relevant argv fields, credential id,
   one-time nonce, expiry) and signs the canonical form with the caller's
   key. Canonicalization is the same discipline the Vault AAR argv-policy
   work uses (perseus-vault#836): only policy-relevant fields, never raw argv
   bodies, prompts, or secrets.
2. **Credential broker** — at the phantom-token swap (#11), the broker
   verifies the proof against the live request before injecting the real
   credential at the boundary. Verification failure = no swap (fail closed),
   mirroring null-effect-on-deny.
3. **Ledger receipts** — the broker records the *binding*, never the secret:
   request binding id (hash), binding digest, credential id, proof outcome,
   expiry. Raw secrets and full argv never enter the receipt.

## Replay and tamper cases (explicit)

- **Replay:** a captured proof presented with a different request id, or
  presented twice, fails verification (one-time nonce consumed at first use;
  request id mismatch on the second).
- **Tamper:** altering the tool, argv, or credential id after signing breaks
  the canonical binding digest; the broker rejects the swap.
- **Cross-request leakage:** even a fully captured request (proof + argv) is
  scoped to the one request it names; the broker treats any other request as
  a different binding.
- **Stale proof:** expiry is part of the canonical form; a proof presented
  after its window is rejected and the denial is itself receipted.

## Non-goals

- No OAuth-stack mandate: this is not an adoption of OAuth 2.0 DPoP, its
  client-registration model, or its token endpoints.
- No claim that DPoP maps 1:1 onto the manifest authority model: manifests
  identify agents and workspaces, not OAuth clients; the request-bound
  construct is adapted, not copied.
- No new identity system and no change to the authority-manifest model.

## How the binding appears in ledger receipts without raw secrets

Receipt fields (all hash-only or policy-relevant):

```json
{
  "request_binding_id": "sha256(actor‖boundary‖tool‖credential_id‖nonce‖expiry)",
  "binding_digest": "sha256(canonicalized policy-relevant fields)",
  "credential_id": "non-secret id of the brokered credential",
  "proof_outcome": "verified | rejected | expired",
  "expires_at_unix_ms": 0
}
```

The value of the credential never appears; full argv bodies never appear;
only canonicalized policy-relevant fields contribute to the binding digest —
the same boundary the AAR argv-policy evaluation uses.

## Rationale

1. Session-bound proof leaves a replay window that request-binding closes at
   the cost of one canonicalization + signature per request — cheap next to
   the tool call itself.
2. The broker (#11) is the natural enforcement point: it already sits between
   the agent and the real credential, so verifying the request-bound proof at
   the swap adds no new trust boundary.
3. Receipts stay secret-free: binding digests are evidence of *what was
   proven*, not of the credential or the request internals.
4. Starting with a lightweight binding (rather than DPoP machinery) keeps the
   manifest authority model intact and avoids importing OAuth semantics that
   do not apply.

## Follow-up

- Implementation issue opened for the binding layer at the broker/tool
  boundary (this sprint), referencing this record and #11.
