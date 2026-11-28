# Umami endpoint inventory

Paths are relative to `/v1` on Umami Cloud or `/api` on a self-hosted instance.
All four tables use the websites visible to the credentials, including team websites.
Use `x-umami-api-key` on Cloud and a bearer token on self-hosted instances.
The credentials must have read access to each website. These routes do not require additional scopes.

| Table                | GET path                                                                                                                           | Rows and primary key                                                               | Pagination                                                                                  | Incremental sync                                                   |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `event_properties`   | [`/websites/{websiteId}/event-data`](https://docs.umami.is/docs/api-reference/get-event-data)                                      | One row per event with an `eventProperties` array. Key: `(websiteId, eventId)`.    | `page` and `pageSize` page distinct events within an inclusive `startAt` and `endAt` range. | Full refresh. A timestamp cutoff can miss events that arrive late. |
| `goals`              | [`/websites/{websiteId}/goals`](https://docs.umami.is/docs/api-reference/get-website-goals)                                        | One row per saved goal. Key: `(websiteId, id)`.                                    | `page` and `pageSize`.                                                                      | Full refresh. No timestamp filter.                                 |
| `session_properties` | [`/websites/{websiteId}/sessions/{sessionId}/properties`](https://docs.umami.is/docs/api-reference/get-website-session-properties) | One row per session with a nonempty property array. Key: `(websiteId, sessionId)`. | Page through `/sessions` in daily windows. The child route returns one array per session.   | Full refresh. The child route has no timestamp filter.             |
| `funnels`            | [`/websites/{websiteId}/funnels`](https://docs.umami.is/docs/api-reference/get-website-funnels)                                    | One row per saved funnel. Key: `(websiteId, id)`.                                  | `page` and `pageSize`.                                                                      | Full refresh. No timestamp filter.                                 |

Event and session properties accept up to 1,000 nonempty pages per website per 24-hour window. Goals and funnels have the same limit per website.
Session properties make one request per distinct session in each attempt. A retry can request a session again.
The `sessions` route reports the last activity in the requested window. This time does not track property updates.
The event date filter and ordering were checked against the published API and server code, without an authenticated live test.
Self-hosted `event_properties` requires version 3.1 or later. Self-hosted `goals` and `funnels` require version 3.4 or later.
