# Product analytics agent guide

## Insight deletion and related resources

These rules apply when changing insight deletion, restoration, or a resource attached to an insight.

An insight's normal deletion is a soft delete (`deleted=True`).
Setting that field does not invoke Django's `on_delete=models.CASCADE`, model `delete()` methods, or delete signals.
Foreign-key cascades only apply to hard deletion; soft deletion needs explicit related-resource cleanup.

### Cleanup contract

Single and bulk insight deletion must apply the same cleanup in the transaction that marks the insight deleted:

| Related resource                                                               | Behavior when the insight is soft-deleted                                                         |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Insight subscriptions, including paused and already soft-deleted subscriptions | Hard-delete through each subscription's `delete()` method; delivery history and contexts cascade. |
| Alert configurations                                                           | Hard-delete through each alert's `delete()` method.                                               |
| Dashboard tiles containing the insight                                         | Hide through `hide_tiles_for_insights`. Keep the dashboard itself.                                |

Only related resources within the authorized project scope may change.
Deleting a subscription directly through its API remains a soft delete; deletion with its parent insight is permanent.
Skipping delivery for a deleted insight does not replace deleting its subscriptions: surviving rows still appear in subscription management.

Restoring an insight does not recreate its subscriptions or alerts.
Do not revive independently deleted related resources when adding or changing restore behavior.

### Where to make changes

- Read [the insight API](backend/presentation/insight.py) when changing deletion or restore behavior. `InsightSerializer.update` handles single deletion; `InsightViewSet.bulk_delete` bypasses model saves with a queryset update, so it must perform cleanup explicitly.
- Read [the exports facade](../exports/backend/facade/api.py) when changing subscription cleanup. `delete_insight_subscriptions` calls each subscription's `delete()` method so model activity logging runs.
- Read [the alerts facade](../alerts/backend/facade/api.py) when changing alert cleanup. `delete_insight_alerts` calls each alert's `delete()` method to preserve activity logging; queryset deletion bypasses that override.
- Read [the dashboards facade](../dashboards/backend/facade/api.py) when changing tile cleanup or restoration. Use `hide_tiles_for_insights` and `restore_tiles_for_insights` rather than duplicating their rules.
- Extend [the existing insight API tests](backend/tests/api/test_insight.py) when changing these behaviors. Cover single and bulk deletion, unrelated resources surviving, and restore behavior.

New deletion entry points, including background cleanup, must honor this contract.
Setting `deleted=True` through a model save or queryset update does not run the API's cleanup automatically.
When adding another related resource, define its deletion and restore behavior explicitly and apply it to both single and bulk operations.
