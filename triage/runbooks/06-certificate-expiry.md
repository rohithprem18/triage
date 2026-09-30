# Expired TLS certificate

## Symptoms
Calls that use TLS or mutual TLS start failing all at once, often at the top of an hour or at midnight UTC, with errors such as "x509: certificate has expired or is not yet valid" or "TLS handshake failed: certificate expired". The error rate on the affected service jumps to nearly 100% for those calls, with no gradual ramp, and requests to the peer drop sharply because the handshake never completes. There is no matching deploy or config change.

## Confirm
- Check the certificate's NotAfter date against the onset time.
- Only connections using that certificate fail; other calls from the same service succeed.

## Mitigate
Issue and deploy a renewed certificate (or roll the secret) and restart the clients that cache it. Afterwards, automate renewal and alert on certificates expiring within 30 days.
