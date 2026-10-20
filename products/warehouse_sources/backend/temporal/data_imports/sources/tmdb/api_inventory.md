# TMDB (The Movie Database) — API inventory

REST/JSON v3 API. Base URL `https://api.themoviedb.org/3`.

## Auth

`api_key` query parameter (v3 API key). A v4 Bearer "API Read Access Token" also works on these
endpoints, but the connector ships only the simpler `api_key` query-param path. The key is sent in
the query string, so the tracked session is created with `redact_values=(api_key,)`.

## Pagination

Page-number pagination: `?page=N`. The list/trending responses carry `page`, `results`,
`total_pages`, `total_results`. ~20 results per page. Server caps paging at **500 pages**
(`MAX_PAGES`), so the paginator stops at `min(total_pages, 500)`.

## Incremental

None of the v3 list endpoints expose a server-side updated-after filter, so **every endpoint is full
refresh only** (`supports_incremental=False`). The `/movie|tv|person/changes` endpoints could feed an
ID-based incremental flow, but they are 14-day-windowed and require per-ID detail fetches — out of
scope for this connector.

## Endpoints

| Schema                 | Path                     | Shape               | Primary key |
| ---------------------- | ------------------------ | ------------------- | ----------- |
| movie_popular          | /movie/popular           | paginated `results` | id          |
| movie_top_rated        | /movie/top_rated         | paginated `results` | id          |
| movie_now_playing      | /movie/now_playing       | paginated `results` | id          |
| movie_upcoming         | /movie/upcoming          | paginated `results` | id          |
| tv_popular             | /tv/popular              | paginated `results` | id          |
| tv_top_rated           | /tv/top_rated            | paginated `results` | id          |
| tv_on_the_air          | /tv/on_the_air           | paginated `results` | id          |
| tv_airing_today        | /tv/airing_today         | paginated `results` | id          |
| person_popular         | /person/popular          | paginated `results` | id          |
| trending_movies        | /trending/movie/day      | paginated `results` | id          |
| trending_tv            | /trending/tv/day         | paginated `results` | id          |
| trending_people        | /trending/person/day     | paginated `results` | id          |
| movie_genres           | /genre/movie/list        | single, `genres`    | id          |
| tv_genres              | /genre/tv/list           | single, `genres`    | id          |
| languages              | /configuration/languages | single, bare list   | iso_639_1   |
| countries              | /configuration/countries | single, bare list   | iso_3166_1  |
| discover_movies        | /discover/movie          | paginated `results` | id          |
| discover_tv            | /discover/tv             | paginated `results` | id          |
| movie_watch_providers  | /watch/providers/movie   | single, `results`   | provider_id |
| tv_watch_providers     | /watch/providers/tv      | single, `results`   | provider_id |
| watch_provider_regions | /watch/providers/regions | single, `results`   | iso_3166_1  |

Both discover tables send `sort_by=vote_count.desc` and `include_adult=false`. Vote counts change
slowly, so the same 10,000 titles (the 500-page cap) stay in the table from one sync to the next.

## Per-title endpoints (fan-out)

These endpoints run once for each row of their parent. They start disabled because each sync makes
one request per discover title (up to 10,000), plus one per season for `tv_episodes`. A 404 for one
title (removed after the listing) is skipped.

| Schema               | Path                                   | Parent          | Row                      | Primary key          |
| -------------------- | -------------------------------------- | --------------- | ------------------------ | -------------------- |
| movie_credits        | /movie/{movie_id}/credits              | discover_movies | one per cast/crew credit | movie_id, credit_id  |
| tv_aggregate_credits | /tv/{series_id}/aggregate_credits      | discover_tv     | one per role or job      | series_id, credit_id |
| tv_seasons           | /tv/{series_id} (`seasons`)            | discover_tv     | one per season           | series_id, id        |
| tv_episodes          | /tv/{series_id}/season/{season_number} | tv_seasons      | one per episode          | show_id, id          |

`tv_seasons` reads the season list from the series details, because that is one request per show
instead of one per season. `tv_episodes` is a two-level fan-out (discover → series details →
season), which the shared framework cannot checkpoint, so a retry restarts it. The single-level
fan-outs resume by parent path.

## Rate limiting

The documented 40 req / 10s limit was disabled in 2019; an undocumented ~50 req/s ceiling deters bulk
scraping and can block abusive IPs. We stay well under it with a small inter-request delay
(`THROTTLE_SECONDS`) plus tenacity backoff on 429 / 5xx.

## Verification note

Endpoint shapes here are taken from the current public TMDB v3 docs. They were **not** curl-verified
against the live API during implementation because a valid TMDB API key was not available in the
environment (unauthenticated requests return `401 {"status_code":7}`). Parsing is kept conservative
(`_extract_rows` degrades to an empty list on unexpected payload shapes rather than raising).
