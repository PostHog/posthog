# Endpoint Version History & Materialization Management - UI Plan

## Overview

Add UI capabilities to view historical versions of endpoints and manage materialization for multiple versions. Each version stores a snapshot of the query and configuration (cache age, sync frequency), and users can materialize any version independently.

## Current State

**Already Implemented (Backend):**
- ✅ `EndpointVersion` model stores immutable query snapshots
- ✅ API endpoints for listing versions and getting specific versions
- ✅ Version auto-increment on query changes
- ✅ Ability to run specific versions (used in playground)
- ✅ Materialization toggle (current version only)

**Missing (Frontend):**
- ❌ No UI to browse version history
- ❌ No way to view old versions of queries/configurations
- ❌ No ability to materialize old versions
- ❌ No visualization of which versions are materialized

---

## Key Design Decisions

1. **Configuration is versioned**: Each version stores its own cache_age and sync_frequency settings
2. **Sync frequency is per-version**: Each materialized version can have different sync frequencies
3. **No new API endpoints**: Use existing endpoints with version parameters in body
4. **Table naming includes version**: Materialized tables named as `{name}_v{version}` (e.g., `user_metrics_v2`)
5. **Query time version selection**: Router selects correct versioned table based on request
6. **No limits**: No limit on number of materialized versions or total versions kept
7. **No auto-materialization**: New versions don't auto-materialize even if previous version was materialized
8. **Reuse existing components**: Use LemonTable, LemonButton, etc. - follow existing patterns

---

## UI Changes

### 1. Configuration Tab - Add Version History Section

Add a new section in `EndpointConfiguration.tsx` below the existing materialization settings.

**Visual Structure:**
```
┌─────────────────────────────────────────────────────────────┐
│ Version History                                              │
│ ─────────────────────────────────────────────────────────── │
│ View previous versions and manage materialization           │
│                                                              │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ Ver │ Created         │ By    │ Status      │ Actions │  │
│ ├─────┼─────────────────┼───────┼─────────────┼─────────┤  │
│ │ v3  │ Jan 13, 2:45 PM │ Alice │ ● Mat.      │ [View]  │  │ <- Current
│ │     │                 │       │ Sync: 1h    │         │  │
│ │ v2  │ Jan 12, 3:30 PM │ Bob   │ ○ Not mat.  │ [View] [Mat.] │
│ │ v1  │ Jan 10, 1:20 PM │ Alice │ ● Mat.      │ [View] [Unmat.] │
│ │     │                 │       │ Sync: 6h    │         │  │
│ └─────┴─────────────────┴───────┴─────────────┴─────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Table Columns:**
- **Version** - Version number with "Current" badge for latest
- **Created** - Timestamp (relative time, hover for absolute)
- **Created by** - User who created the version
- **Materialization Status**:
  - `● Materialized` (green) + sync frequency below
  - `○ Not materialized` (gray)
  - `⟳ Syncing...` (animated) - if actively syncing
  - `⚠ Error` (red) - if materialization failed
- **Actions**:
  - `View` button - Switch to read-only view of this version
  - `Materialize` button - For non-materialized versions only
  - `Unmaterialize` button - For materialized non-current versions only

**Implementation Notes:**
- Use existing LemonTable component
- Current version row highlighted (subtle background color)
- Show last materialized timestamp on hover or below status
- Pagination if versions exceed 10-15 items
- Current version uses the existing materialization toggle in the section above (no duplicate controls)

---

### 2. Version Viewing Mode (Read-Only)

When clicking "View" on an old version, switch entire UI to read-only mode.

**Header Banner (`EndpointHeader.tsx`):**
```
┌──────────────────────────────────────────────────────────────┐
│ ⚠ Viewing historical version v2 (Read-only)                  │
│ ──────────────────────────────────────────────────────────── │
│ This is a previous version. Editing is disabled.             │
│ [Return to current version (v3)]                             │
└──────────────────────────────────────────────────────────────┘
```

**Component Behavior Changes:**

**Query Tab:**
- Display query as it was in that version
- Make query editor read-only (disable editing)
- For HogQL: Read-only code viewer
- For Insights: Read-only query visualization (use existing read-only components)
- Hide "Edit in SQL Editor" button
- Small indicator: "Viewing version vX query"

**Configuration Tab:**
- Display configuration values from that version:
  - Cache age (as it was configured for vX)
  - Sync frequency (as it was configured for vX)
- All inputs disabled/read-only
- Version history table remains interactive (can view other versions)
- Materialization controls work for other versions, but selected version shows read-only status

**Playground Tab:**
- Remains functional for testing
- Automatically uses the selected version for queries
- Show indicator: "Testing with version vX"

**History Tab:**
- No changes (activity log is global)

**State Management:**
- Add `viewingVersion: number | null` to `endpointSceneLogic.tsx`
  - `null` = viewing current version (editable)
  - `number` = viewing specific historical version (read-only)
- When `viewingVersion` is set, load version data via existing `getVersion()` API
- Hide Save/Discard buttons when in read-only mode
- Show "Return to current version" button

---

### 3. Materialization Management

**Current Version:**
- Existing toggle in Configuration tab controls current version materialization
- Existing sync frequency selector (when materialized)
- Existing materialization status display

**Old Versions:**
- Each version in history table has independent materialization control
- Clicking "Materialize":
  - Shows inline sync frequency selector (dropdown with hourly/daily/weekly options)
  - User MUST select sync frequency (no default value)
  - After selection, calls existing update endpoint with version-specific materialization flag
  - Updates table row status to "Syncing..." then "Materialized"
- Clicking "Unmaterialize":
  - Shows confirmation dialog: "Remove materialized data for version vX?"
  - On confirm, calls update endpoint to disable materialization for that version
  - Updates UI status to "Not materialized"

**Materialization Status Display:**
- Keep simple for now (detailed metrics can be added later)
- Show: materialized/not materialized + sync frequency
- Don't overcomplicate with detailed health metrics initially

---

## Backend Changes Required

### 1. Data Model Updates

**EndpointVersion Model** (`products/endpoints/backend/models.py`):

Add fields to store configuration snapshot:
```python
class EndpointVersion(models.Model):
    # Existing fields
    id = models.UUIDField(...)
    endpoint = models.ForeignKey(...)
    version = models.IntegerField(...)
    query = models.JSONField(...)
    created_at = models.DateTimeField(...)
    created_by = models.ForeignKey(...)

    # New fields
    cache_age_seconds = models.IntegerField(default=300)
    is_materialized = models.BooleanField(default=False)
    sync_frequency = models.CharField(
        max_length=20,
        choices=[
            ('hourly', 'Hourly'),
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
        ],
        null=True,
        blank=True
    )
    last_materialized_at = models.DateTimeField(null=True, blank=True)
    materialization_error = models.TextField(null=True, blank=True)
```

**Update `create_new_version()` method**:
- When creating new version, snapshot current configuration values:
  - `cache_age_seconds`
  - `sync_frequency` (if materialized)
- Don't auto-materialize new version (per requirements)

### 2. Saved Query Table Naming

**Current Implementation:**
The saved query name is currently set as:
```python
saved_query = DataWarehouseSavedQuery(
    name=endpoint.name,  # Just the endpoint name, no prefix
    team=self.team,
    origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
)
```

**Table Naming Convention:**
- Current (single version): Table name is `{endpoint.name}` (e.g., `user_metrics`)
- New (with versions): Table name is `{endpoint.name}_v{version}` (e.g., `user_metrics_v2`, `user_metrics_v3`)

**Changes Needed:**

1. **Endpoint materialization logic** (where saved query is created):
   - When creating saved query for a specific version, set name to include version suffix
   - For version N: `name = f"{endpoint.name}_v{version.version}"`
   - Example: If endpoint name is "user_metrics" and version is 2, saved query name is "user_metrics_v2"
   - **Do NOT modify DataWarehouseSavedQuery model or related files** - just change the name parameter

2. **Query execution** (`products/endpoints/backend/api.py` - `run` method):
   - When executing endpoint with specific version parameter:
     - If version is materialized, query from table named `{endpoint.name}_v{version}`
     - If version not materialized, execute query directly (existing behavior)
   - Table name selection logic:
     ```python
     if version and version.is_materialized:
         table_name = f"{endpoint.name}_v{version.version}"
         # Query from materialized table
     else:
         # Execute query directly
     ```

3. **Cleanup considerations**:
   - When unmaterializing a version, drop/delete the saved query (which drops the table)
   - Consider background job to clean up orphaned tables (future enhancement)

### 3. API Endpoint Updates

**Use existing endpoints, add version-specific parameters in request body:**

**Update endpoint** (`PATCH /api/environments/{team_id}/endpoints/{name}/`):
- Current behavior: Updates current version
- New: Accept optional `version` parameter in body
  - If provided, update that specific version's configuration
  - Fields that can be updated for old versions:
    - `is_materialized` (to materialize/unmaterialize)
    - `sync_frequency` (to change sync schedule)
  - Query cannot be changed for old versions (immutable)

**Get version** (`GET /api/environments/{team_id}/endpoints/{name}/versions/{version_number}/`):
- Already exists
- Ensure response includes: `is_materialized`, `sync_frequency`, `cache_age_seconds`, `last_materialized_at`

**List versions** (`GET /api/environments/{team_id}/endpoints/{name}/versions/`):
- Already exists
- Ensure response includes materialization fields for each version

**Run endpoint** (`POST /api/environments/{team_id}/endpoints/{name}/run/`):
- Already accepts `version` parameter
- Update to use versioned table name when querying materialized versions

### 4. Minimal Changes to Saved Query Service

- **Critical**: Do NOT modify DataWarehouseSavedQuery model or related saved query service files
- **Only change**: The `name` parameter when creating saved queries for endpoints
  - Pass versioned name: `name=f"{endpoint.name}_v{version.version}"`
- **Table creation**: Existing saved query creation logic handles table creation (no changes needed)
- **Table dropping**: Existing saved query deletion logic handles table dropping (no changes needed)
- **Goal**: Absolute minimal changes - just pass a different name parameter

---

## Frontend Changes Required

### 1. State Management

**endpointSceneLogic.tsx:**

Add state:
```typescript
viewingVersion: [
    null as number | null,
    {
        selectVersion: (version: number | null) => version,
    },
],
versions: [
    [] as EndpointVersionType[],
    {
        loadVersionsSuccess: (_, { versions }) => versions,
    },
],
```

Add actions:
```typescript
loadVersions: true,
loadVersionsSuccess: (versions: EndpointVersionType[]) => ({ versions }),
selectVersion: (version: number | null) => ({ version }),
returnToCurrentVersion: true,
updateVersionMaterialization: (version: number, data: { is_materialized: boolean, sync_frequency?: string }) => ({ version, data }),
```

Add listeners:
```typescript
loadVersions: async () => {
    const versions = await api.endpoint.listVersions(endpoint.endpoint_path)
    actions.loadVersionsSuccess(versions)
},
updateVersionMaterialization: async ({ version, data }) => {
    await api.endpoint.updateVersion(endpoint.endpoint_path, version, data)
    actions.loadVersions() // Refresh versions
},
```

Add selectors:
```typescript
isViewingOldVersion: [
    (s) => [s.viewingVersion],
    (viewingVersion): boolean => viewingVersion !== null,
],
currentEndpointData: [
    (s) => [s.endpoint, s.viewingVersion, s.versions],
    (endpoint, viewingVersion, versions): EndpointType | EndpointVersionType => {
        if (viewingVersion === null) return endpoint
        return versions.find(v => v.version === viewingVersion) || endpoint
    },
],
```

### 2. Component Updates

**EndpointConfiguration.tsx:**
- Add version history section below existing materialization controls
- Use LemonTable to display versions
- Add "View" buttons using LemonButton
- Add "Materialize" button that reveals inline sync frequency dropdown (hourly/daily/weekly)
  - User must select frequency before materialization begins (no default)
  - After selection, trigger materialization
- Add "Unmaterialize" button with confirmation dialog
- Load versions on mount: `useEffect(() => { actions.loadVersions() }, [])`
- Handle version selection: `onClick={() => actions.selectVersion(version.version)}`
- Handle materialization with inline frequency selection:
  ```typescript
  const handleMaterialize = (version: number, syncFrequency: string) => {
      actions.updateVersionMaterialization(version, {
          is_materialized: true,
          sync_frequency: syncFrequency // User-selected value (required)
      })
  }

  const handleUnmaterialize = (version: number) => {
      LemonDialog.open({
          title: `Remove materialized data for version v${version}?`,
          onConfirm: () => {
              actions.updateVersionMaterialization(version, {
                  is_materialized: false
              })
          }
      })
  }
  ```

**EndpointHeader.tsx:**
- Add read-only banner when `isViewingOldVersion === true`
- Use LemonBanner component (if exists) or simple div with warning styling
- Show "Return to current version" button
- Hide Save/Discard buttons when in read-only mode
- Disable description editing when in read-only mode

**EndpointQuery.tsx:**
- When `isViewingOldVersion === true`:
  - Pass `readOnly` prop to query editor
  - Hide "Edit in SQL Editor" button
  - Display query from `currentEndpointData.query` (which comes from selected version)

**EndpointOverview.tsx:**
- Update version display to show selected version:
  - If viewing current: `v{endpoint.current_version} ({endpoint.versions_count} total)`
  - If viewing old: `Viewing v{viewingVersion} (Current: v{endpoint.current_version})`

### 3. API Client Updates

**lib/api.ts:**

Update endpoint API client:
```typescript
endpoint: {
    // ... existing methods
    updateVersion: async (name: string, version: number, data: Partial<EndpointVersionType>) => {
        return await api.update(`api/environments/${getCurrentTeamId()}/endpoints/${name}/versions/${version}`, data)
    },
    // listVersions and getVersion already exist, ensure they're used
}
```

### 4. Type Updates

**types.ts:**

Update EndpointVersionType:
```typescript
export interface EndpointVersionType {
    id: string
    version: number
    query: HogQLQuery | InsightQueryNode
    created_at: string
    created_by: UserBasicType | null

    // New fields
    cache_age_seconds: number
    is_materialized: boolean
    sync_frequency?: 'hourly' | 'daily' | 'weekly'
    last_materialized_at?: string
    materialization_error?: string
}
```

---

## Implementation Approach

### Phase 1: Backend Foundation
1. Add configuration fields to EndpointVersion model (migration)
2. Update `create_new_version()` to snapshot configuration
3. Update versioned table naming in materialization service
4. Update query execution to select correct versioned table
5. Update existing API endpoints to handle version-specific materialization

### Phase 2: Frontend - Version Viewing
1. Add state management for version viewing
2. Add read-only banner to EndpointHeader
3. Disable editing in Query tab when viewing old version
4. Add "Return to current version" functionality

### Phase 3: Frontend - Version History UI
1. Add version history table to Configuration tab
2. Implement "View" buttons to switch versions
3. Load and display version list with materialization status

### Phase 4: Frontend - Materialization Controls
1. Add "Materialize"/"Unmaterialize" buttons to version history
2. Implement inline sync frequency selector (dropdown, no default value)
3. Implement unmaterialize confirmation dialog
4. Implement materialization toggle logic
5. Update status display after materialization changes

### Phase 5: Testing & Polish
1. Test version viewing with different query types (HogQL, Insights)
2. Test materialization for multiple versions
3. Test query execution uses correct versioned tables
4. Ensure read-only mode prevents all edits
5. Polish UI styling to match PostHog design system

---

## Edge Cases & Considerations

1. **Version 1 edge case**: If viewing v1 and it's the only version, "Return to current version" goes to v1 (which is current)

2. **Materialization in progress**: Show loading state while materialization is syncing

3. **Materialization errors**: Display error message in status column, allow retry

4. **Large number of versions**: Pagination in version history table (>15 versions)

5. **Permissions**: Ensure only users with edit permissions can materialize/unmaterialize versions

6. **Table cleanup**: When version is unmaterialized, ensure table is dropped properly

7. **Query execution fallback**: If materialized table doesn't exist, fall back to direct query execution

8. **Configuration changes**: If user is viewing old version and current version's config is updated, version table shows historical config (not current)

---

## Future Enhancements (Out of Scope)

- Version diffing/comparison view
- Auto-cleanup of old unmaterialized versions
- Materialization health metrics dashboard
- Version notes/changelog
- Rollback to previous version (make old version the current version)
- Version tagging/labeling
- Export version as new endpoint

---

## Design Decisions (Answered)

1. **Materialization sync frequency UI**:
   - ✅ Inline dropdown selector (not modal)
   - ✅ No default value - user MUST select frequency
   - ✅ Simple, not overcomplicated

2. **Configuration display in read-only mode**:
   - ✅ Show actual configuration values from that version (cache_age_seconds, sync_frequency)
   - ✅ Display as read-only fields

3. **Unmaterialize confirmation**:
   - ✅ Yes, show confirmation dialog: "Remove materialized data for version vX?"

4. **Version table location**:
   - ✅ Keep in Configuration tab (may move to dedicated tab later if needed)
