# Live debugger

## LiveDebuggerProgram (`system.live_debugger_programs`)

A hogtrace program installed in a project. Programs instrument production code
with probes; when a probe fires it emits a `$data_breakpoint_hit` event tagged
with the program's id in the `$program_id` property.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this program belongs to
`code` | text | NOT NULL | Full hogtrace program source code
`description` | text | NOT NULL | Human-readable description of what the program observes
`status` | varchar(16) | NOT NULL | `installed` (probes are live) or `uninstalled` (soft-deleted, retained for history)
`created_at` | timestamp with tz | NOT NULL | When the program was installed
`updated_at` | timestamp with tz | NOT NULL | When the program record was last modified (e.g. on uninstall)

### Key relationships

- Programs belong to a **Team** (`team_id`).
- Emitted events live in ClickHouse `events` and carry `properties.$program_id`
  (matching `system.live_debugger_programs.id`) and `properties.$probe_id`.
  Join via HogQL by filtering events on `JSONExtractString(properties, '$program_id') = <id>`.

### Important notes

- Uninstall is **soft** — rows are never deleted. Filter on `status = 'installed'`
  to see only active programs; both states stay queryable so historical events
  remain attributable to their program.
- The `code` column can be large; prefer projecting only `id`, `description`,
  `status`, and timestamps when listing programs.
