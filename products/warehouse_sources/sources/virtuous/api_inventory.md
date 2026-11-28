# Virtuous API inventory

Reference: [Virtuous CRM+ API collection](https://docs.virtuoussoftware.com/api/collections/19331481/UVeAuTw4?segregateAuth=true&versionTag=latest).
Use a bearer API key. Its permission group must allow reads for each resource below.
Virtuous documents permission groups, not endpoint-specific token scopes.

| Table                     | Route                                   | Required read access      | One row per       | Primary key       | Sync mode    |
| ------------------------- | --------------------------------------- | ------------------------- | ----------------- | ----------------- | ------------ |
| `communications`          | `GET /api/Communication/ByCampaign/:id` | Campaigns, communications | Communication     | `communicationId` | Full refresh |
| `volunteers`              | `GET /api/Volunteer/Search`             | Volunteers                | Volunteer sign-up | `id`              | Full refresh |
| `volunteer_opportunities` | `POST /api/VolunteerOpportunity/Query`  | Volunteer opportunities   | Opportunity       | `id`              | Incremental  |

- These routes return rows in `list` and a count in `total`. The source sends `skip` and `take` as query parameters. The reference omits those parameters for the opportunity query.
- Communications reads campaigns through `POST /api/Campaign/Query` and requests each campaign's communications. The by-campaign route supports sorting by `Id`. It returns `communicationId`, which also identifies a communication in `GET /api/Communication/:communicationId`.
- Opportunity query options list `Last Modified Date` with `OnOrAfter`. The source uses `modifiedDateTimeUtc` as its watermark. The communications and volunteer routes do not document a modified-date filter.
- Authenticated verification is pending. Check the page boundaries and ordering for all three routes. For opportunities, compare an unfiltered page with a query that uses a future modified date.
