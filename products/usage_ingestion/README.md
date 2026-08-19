# Usage ingestion

This product owns the Django-written team-to-organization HyperCache used by
the usage-ingestion service. Each team has one mapping at:

```text
posthog:1:cache/teams/<team_id>/usage_ingestion/organization_id.json
```

Set `USAGE_INGESTION_REDIS_URL` to the dedicated Redis connection before
running the publisher. In local Docker development it uses Redis database 2.

Warm existing mappings after enabling the cache:

```sh
python manage.py warm_team_organization_cache
```

Team saves publish after transaction commit; team deletion clears the mapping.
