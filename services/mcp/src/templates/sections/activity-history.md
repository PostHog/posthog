### Activity history

Use `advanced-activity-logs-list` for configuration history. Read its schema once before the first history check, then pass `start_date`, `end_date`, relevant `scopes`/`item_ids`, `page_size: 10`, and only needed `fields`. Request `detail.changes` only for a specific candidate. A non-null `next` means incomplete history; narrow the window or paginate with `page` within the investigation budget before ruling out an edit.

To audit a scout run, bracket its start and completion times and filter `clients: ["scout:<skill_name>"]` using the scout's actual skill name from its config. Include `Notebook` alongside the resource types covered by its write grant. Inspect actors, items, and timestamps: the tag identifies the scout, not an individual run, so overlapping runs can share it. If the tag is unknown, omit the client filter and treat attribution as uncertain.

Access controls and the plan's retention window still apply. If access is denied, stop using this reader for the run and record the limitation. Other advertised, authorized history readers, including per-object readers, remain usable. Missing history does not prove that no configuration change occurred.
