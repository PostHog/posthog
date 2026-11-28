# AccuLynx v2 endpoint inventory

These paths are relative to `https://api.acculynx.com/api/v2`. Requests use an AccuLynx API key as a Bearer token.
The API reference does not name a separate auth scope for any of these endpoints.

| Table           | GET path                                            | Row grain                           | Pagination                            | Primary key                 | Sync and incremental candidates               |
| --------------- | --------------------------------------------------- | ----------------------------------- | ------------------------------------- | --------------------------- | --------------------------------------------- |
| `contact_types` | `/contacts/contact-types`                           | One contact type per company        | `pageStartIndex`, `pageSize`, `count` | `id`                        | Full refresh. No timestamp or change filter.  |
| `account_types` | `/company-settings/location-settings/account-types` | One active account type per company | Single response                       | `id`                        | Full refresh. No timestamp or change filter.  |
| `lead_history`  | `/leads/{leadId}/history`                           | One action on a current lead        | Single response per lead              | `lead_id`, `date`, `action` | Full refresh. No documented filter on `date`. |

All three endpoints return an object with an `items` array. The lead history endpoint does not return an action ID.
The source lists parents with `GET /jobs?milestones=lead` and adds the parent ID to each action as `lead_id`.
It turns lead history off by default because it makes one extra request per current lead.

Live requests without a key returned HTTP 401 for all three endpoints and the parent jobs list.
An account with test data is still required to verify successful responses, contact type offsets, and the lead filter.

API references: [contact types](https://apidocs.acculynx.com/reference/getcontacttypes),
[active account types](https://apidocs.acculynx.com/reference/getactiveaccounttypes),
[lead history](https://apidocs.acculynx.com/reference/getleadhistory), and
[jobs](https://apidocs.acculynx.com/reference/getjobs).
