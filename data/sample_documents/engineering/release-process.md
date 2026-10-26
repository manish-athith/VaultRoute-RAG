# Engineering Release Process

Changes move from review to automated tests, staging, and then production. A release owner confirms
database migrations, rollback instructions, monitoring, and customer impact before approval. High-risk
changes require a second engineer and a scheduled observation period after deployment.

Database migrations must be backward compatible during a rolling release. Secrets are supplied by the
deployment environment and never committed. If error rate or latency crosses the agreed threshold, the
release owner pauses rollout and chooses rollback or repair. The incident channel records timestamps,
decisions, and owners. Emergency fixes still require review and a follow-up test. A release is complete
only when health checks are green and the change log has been updated.
