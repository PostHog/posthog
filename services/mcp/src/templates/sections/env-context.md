### Active environment

Call `project-get` without an ID to read the active project: its name, id, organization, timezone, person-on-events mode, test account filter default, and enabled products. Call it before you rely on one of these, for example the timezone for a date range. For the project's group types, run `execute-sql` on `system.group_type_mappings`.
