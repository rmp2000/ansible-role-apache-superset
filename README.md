# Native Apache Superset
Pinned Python application in its own virtual environment, served by Gunicorn.
Dedicated PostgreSQL 14 metadata cluster on port 5433, bound to loopback with data
under `/srv/apache-superset`. Independent from the dCache namespace database.
The UI listens on loopback by default; use an SSH tunnel. Never expose it with
an unauthenticated public endpoint. CSRF and authenticated sessions remain on.
Provide a strong per-deployment application key and separate admin/database passwords.
When analytics integration is enabled, provision a read-only ClickHouse connection,
a dataset, a table and a chart dashboard. The ClickHouse TLS identity is verified.
Persistence and a real metadata backup restored into an isolated database are tested.
