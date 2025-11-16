# ORM Call Site Clustering Summary

## Person.objects Method Distribution

| Method | Count | Needs Dual-Table? |
|--------|-------|-------------------|
| `.get()` | 8 | ✅ YES - Critical |
| `.filter()` | 19 | ✅ YES - Critical |
| `.bulk_create()` | 3 | ⚠️ Partial - Test/demo code |
| `.create()` | 1 | ⚠️ Partial - Test/demo code |
| `.all()` | 1 | ⚠️ Maybe - API queryset |
| `.db_manager()` | 17 | ✅ YES - Read routing |

**Total Person.objects calls:** ~42 unique call sites

---

## Person FK Relation Usage (Critical for Dual-Table)

| Pattern | Count | Impact |
|---------|-------|--------|
| `persondistinctid__distinct_id` | 5 | 🔴 CRITICAL - FK join breaks |
| `persondistinctid__distinct_id__in` | Subset of above | 🔴 CRITICAL |
| `persondistinctid_set` prefetch | 7 | ✅ OK - Works once have Person |

**Key insight:** 5 locations use reverse FK joins that will ONLY find persons in old table.

---

## PersonDistinctId.objects Method Distribution

| Method | Count | Dual-Table Impact? |
|--------|-------|-------------------|
| `.filter()` | 8 | ✅ OK - PDI has person_id, works for both |
| `.bulk_create()` | 3 | ✅ OK - No table dependency |
| `.create()` | 2 | ✅ OK - No table dependency |

**Total PersonDistinctId.objects calls:** ~13 call sites
**Status:** ✅ PersonDistinctId queries work regardless of person table

---

## Priority Call Sites Requiring Dual-Table Support

### P0 - CRITICAL (8 .get() calls)

1. `posthog/tasks/split_person.py:13` - `.get(pk=person_id)`
2. `posthog/management/commands/split_person.py:55` - `.get(pk=person_id)`
3. `posthog/models/person/person.py:166` - `.get(pk=self.pk)` (in split_person)
4. `posthog/session_recordings/models/session_recording.py:142` - `.get(persondistinctid__...)` 🔴 FK join
5. `posthog/api/cohort.py:1125` - `.get(team_id=..., uuid=...)`
6. `posthog/models/cohort/cohort.py:592` - `.get(team_id=..., uuid=...)`
7. `posthog/models/event/util.py:183` - `.get(persondistinctid__...)` 🔴 FK join
8. `posthog/api/person.py:551` - via `get_pk_or_uuid()`

### P0 - CRITICAL (5 persondistinctid__ FK joins)

1. `posthog/models/person/util.py:196` - `get_persons_by_distinct_ids()` 🔴 MOST CRITICAL
2. `posthog/models/feature_flag/flag_matching.py:520` - Feature flag evaluation 🔴 CRITICAL
3. `posthog/session_recordings/models/session_recording.py:143` - Session recording link
4. `posthog/models/event/util.py:184` - Event person lookup
5. `posthog/api/person.py:400` - Bulk delete by distinct_id

### P1 - HIGH (19 .filter() calls)

Most critical filters:

- `posthog/models/person/util.py:193` - `get_persons_by_distinct_ids()` base query
- `posthog/models/feature_flag/flag_matching.py:518,1240` - Feature flag queries
- `posthog/models/team/util.py:38` - Team deletion (must delete from both tables!)
- `posthog/api/person.py:551` - Person API via get_pk_or_uuid

### P2 - MEDIUM (Management commands, demos)

- Various admin/management commands
- Demo data generation
- Export/sync utilities

---

## Implementation Strategy

### Phase 1: Override Core Manager Methods

```python
class DualPersonManager(models.Manager):
    def get(self, *args, **kwargs):
        # Smart routing for pk, uuid lookups
        # Handle FK joins (persondistinctid__) specially

    def filter(self, *args, **kwargs):
        # Query both tables, merge results
```

This fixes all 8 `.get()` calls + 19 `.filter()` calls automatically.

### Phase 2: Fix Critical Helper Functions

- `get_persons_by_distinct_ids()` - Custom dual-table implementation
- Feature flag matching - Update FK joins
- Team deletion - Ensure deletes from both tables

### Phase 3: Monitor & Test

- Verify all call sites work with dual-table
- Performance testing
- Gradual rollout

---

## Files Generated

- `CLUSTERED_CALLS.txt` - Full output with line numbers
- `ORM_CALL_SITES.txt` - Complete grep with context
- `cluster_calls.sh` - Reproducible clustering script
