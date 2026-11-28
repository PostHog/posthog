# Pipeliner v100 endpoint inventory

References: [Coevera REST OpenAPI specification](https://developers.coevera.com/openapi/coevera-rest.json) and [API application permissions](https://developers.coevera.com/get-started/permissions-and-scopes/).

## Access and sync

- All paths are relative to `/api/v100/rest/spaces/{space_id}`. Each endpoint lists records across one space without a parent ID.
- Requests use HTTP Basic with the space's API application credentials. The application needs read access to the requested entity. The REST specification does not list endpoint-specific permission mappings or OAuth scopes for these requests.
- Rows are in `data`. Request the next page with `after=page_info.end_cursor` when `page_info.has_next_page` is true and a cursor is present. An empty page also ends the sync.
- Each row has a UUID `id` as its primary key. Full refresh sorts by `created`, which also serves as the partition key.
- Incremental sync sorts by `modified` and sends `filter[modified]` with `filter-op[modified]=gte` on every page.

## Endpoints

| Table                                    | GET path                                       | One row per                               |
| ---------------------------------------- | ---------------------------------------------- | ----------------------------------------- |
| `account_types`                          | `/entities/AccountTypes`                       | Account type                              |
| `appointment_types`                      | `/entities/AppointmentTypes`                   | Appointment type                          |
| `contact_account_account_role_relations` | `/entities/ContactAccountAccountRoleRelations` | Role assignment on a contact-account link |
| `contact_account_relations`              | `/entities/ContactAccountRelations`            | Contact-account link                      |
| `contact_types`                          | `/entities/ContactTypes`                       | Contact type                              |
| `lead_types`                             | `/entities/LeadTypes`                          | Lead type                                 |
| `opportunity_types`                      | `/entities/OpportunityTypes`                   | Opportunity type                          |
| `quote_processes`                        | `/entities/QuoteProcesses`                     | Quote process                             |
| `quote_types`                            | `/entities/QuoteTypes`                         | Quote type                                |
| `quotes`                                 | `/entities/Quotes`                             | Quote                                     |
| `task_types`                             | `/entities/TaskTypes`                          | Task type                                 |
