# Runbook: Suspicious Login / Account Takeover Indicators

**Category:** security
**Severity:** SEV-2 by default, SEV-1 if admin account
**Tags:** auth, sso, account-takeover, security

## Symptoms
- Authentication logs show successful logins from impossible-travel locations (e.g., two countries within 10 minutes).
- A burst of failed-then-successful logins on a single account.
- MFA challenges being approved from an unfamiliar device fingerprint.

## Triage Steps
1. Pull the full session history for the suspect account for the last 7 days. Tag every IP, user-agent, and device-fingerprint pair.
2. Determine the role and privileges of the account. Admin / production-data access triggers higher severity.
3. Check whether any sensitive actions (data exports, permission grants, credential rotations) happened in the suspicious sessions.
4. Look for related accounts on the same suspicious device fingerprint — takeovers often pivot.

## Mitigation
1. Revoke all active sessions for the affected account.
2. Force a password reset and re-enrollment of MFA.
3. Temporarily disable the account if there is any evidence of malicious action, pending interview with the user.
4. If admin privileges were used, reset all secrets and tokens the admin had access to, treating them as leaked.

## Validation
- No further logins from the suspicious geography / fingerprint.
- The legitimate user confirms their access has been restored.
- A forensic record of the suspicious session has been preserved.

## Post-incident
- Add the suspicious IP / ASN to the elevated-risk list for adaptive auth.
- If a phishing email was the root cause, alert the broader org with the indicators.
