# Runbook: Leaked Credentials in Public Source

**Category:** security
**Severity:** SEV-1
**Tags:** secrets, leak, rotation, github, security

## Symptoms
- Secret-scanner (GitHub, GitGuardian, internal scanner) alerts on a committed key.
- A public repository, gist, paste-bin, or container image is reported to contain a live credential.
- Anomalous usage of the credentialed account is observed in audit logs.

## Triage Steps
1. Confirm the credential is real and active. Match the leaked prefix against the issuing system (AWS IAM, GCP service account, internal SSO, etc.).
2. Determine the blast radius: which services / data does this credential authorize?
3. Pull audit logs for the credential for the last 90 days to see if it has been used by an unexpected source.
4. Identify how the credential was committed (which commit, which author, which branch) — needed for the post-incident root cause but does NOT block rotation.

## Mitigation
1. Rotate the credential immediately. Do not wait to "investigate first" — assume it is compromised.
2. Revoke any sessions or short-lived tokens derived from it.
3. If the credential is in git history, revoke first, then scrub via `git filter-repo` or BFG, then force-push. (Coordinate with the repo owner first if it is a shared branch.)
4. Notify the security on-call channel and open an incident ticket — even on suspected false-positives, security tracks all rotations.

## Validation
- Old credential rejected by the issuing system.
- New credential propagated to all consuming services (verify via a synthetic call).
- No production traffic still using the old credential ID in audit logs.

## Post-incident
- Add a pre-commit hook or repo-side push protection if not already in place.
- Run a corpus-wide secret scan on the same repo to catch sibling leaks.
