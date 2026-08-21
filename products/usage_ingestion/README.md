# Usage ingestion

This product owns the Django-written team-to-organization HyperCache used by
the usage-ingestion service. Each team has one mapping at:

```text
posthog:1:cache/teams/<team_id>/usage_ingestion/organization_id.json
```

`USAGE_INGESTION_REDIS_URL` gates the whole publisher: unset, the signal
receiver and both periodic tasks return immediately. No compose stack sets it,
so nothing writes until you opt in. Point it at the same store the
usage-ingestion service reads, which is `redis://redis7:6379/2` in the local
stack and a dedicated Valkey cluster in cloud.

Warm existing mappings after enabling the cache:

```sh
python manage.py warm_team_organization_cache
```

Team saves publish after transaction commit; team deletion clears the mapping.
