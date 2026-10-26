# Engineering API Standards

New HTTP APIs use resource-oriented paths, JSON request bodies, and explicit response schemas. Every
request receives a request ID. Validation errors use a stable machine-readable code and a short safe
message. Services must not expose stack traces, database keys, secrets, or the names of restricted
resources.

Authentication is checked before business logic. Authorization is evaluated from current server-side
roles and departments rather than values sent by a client. Breaking changes require a new version or a
documented migration window. Each endpoint needs unit tests for validation and integration tests for
its most important success and failure paths. Logs should include timing and request IDs but exclude
passwords, access tokens, full document text, and personal information.
