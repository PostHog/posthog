# Path resolution mode (`CYMBAL_MODE=path_resolution`)

gRPC service that maps the file paths of stack frames to paths in the release repository.
It is a run mode of the `cymbal` binary, selected with `CYMBAL_MODE=path_resolution`, and deployed as `cymbal-path-resolution`.
It speaks `cymbal.path_resolution.v1`.

It answers one question: for these frame paths and this commit, which files of the repository are they?
The frontend uses the answer to link a frame straight to the file at the release commit.

## Architecture

```text
Django release job ──writes──▶ object storage: {folder}/v1/{team_id}/{repo}/{commit}.zst
                                        │
                                        │ GET on a cache miss
                                        ▼
cymbal (processing) ──ResolvePaths──▶ cymbal-path-resolution
  one unary call per exception         │ file list in memory (LRU by bytes)?
  with its in-app frame paths          │   no: load it once, in the background
                                       │ match each path against the list
                                       ▼
                                     repo path per frame, or no path
```

The service keeps no state between requests other than the list cache.
It connects to object storage only: no Postgres, Kafka or Redis.

## Contract

The proto is [`proto/cymbal/path_resolution/v1/path_resolution.proto`](../../../../../proto/cymbal/path_resolution/v1/path_resolution.proto).

A `ResolvePathsRequest` holds a `team_id`, a repo slug (`github.com/acme/shop`), a 40-character lowercase commit and at most 100 paths of at most 1024 characters.
Anything else is rejected with `INVALID_ARGUMENT`.

The response has one `PathResult` per request path, in request order, and a `ListState`:

| `ListState` | Meaning |
| ----------- | ------- |
| `LIST_STATE_LOADED` | The file list was found. Each result has an outcome. |
| `LIST_STATE_MISSING` | No list is stored for this team, repo and commit. Every result is `OUTCOME_NO_MATCH`. |
| `LIST_STATE_ERROR` | Object storage failed or the list is unreadable. Every result is `OUTCOME_NO_MATCH`. |

| `Outcome` | Meaning | `repo_path` |
| --------- | ------- | ----------- |
| `OUTCOME_SURE` | Exactly one file matches. | set |
| `OUTCOME_SUPPORT` | Several files match, and the sure paths of the same request chose one. | set |
| `OUTCOME_TIE` | Several files match, and nothing decides. | empty |
| `OUTCOME_NO_MATCH` | No file matches. | empty |

`SURE` and `NO_MATCH` depend only on the path and the commit, so callers may cache them.
`SUPPORT` and `TIE` depend on the other paths of the request, so callers must not cache them.

## Matching

For each path, the service finds the longest end of the path that is also the end of a repository file.
It skips leading segments that are empty, `.` or `..`, so `webpack://acme-web/./src/index.tsx` and `../../src/index.tsx` match `apps/web/src/index.tsx`.
A file name alone matches only when exactly one file has that name.

When several files share the matching end (two services with `src/index.tsx`), the sure matches of the same request vote.
Only sure matches that removed the same prefix from their path count, because those frames ran from the same folder.
If one candidate gets the most votes, the outcome is `SUPPORT`; otherwise it is `TIE`.

The matching is the same for every language.
Callers send the best path they have for a frame (see the caller's docs), and the service never guesses beyond the file list of that exact commit.
The code is in [`matching.rs`](./matching.rs), and its tests hold the reference vectors.

## File lists

Django writes one object per team, repo and commit when a release is created (`products/error_tracking/backend/logic/repo_paths/`).
The body is the sorted file paths of the commit, joined with `\n`, compressed with zstd.
An object never changes, so a loaded list stays valid until it is evicted for space.

- **Cache.** Lists are held in a moka cache weighed by their memory size, bounded by `CYMBAL_PATH_RESOLUTION_CACHE_BYTES`.
- **Missing lists.** A key with no object, or with an unreadable object, is remembered for `CYMBAL_PATH_RESOLUTION_MISSING_TTL_SECS`, so repeated requests do not reach object storage.
- **Loads.** A miss starts one load per key, shared by every concurrent request for that key. The load runs in its own task, so it finishes and fills the cache even when the request that started it passes its deadline.
- **Limits.** A list that decompresses past `CYMBAL_PATH_RESOLUTION_MAX_DECOMPRESSED_BYTES` is rejected.

The first request for a commit on a pod can pass the caller's deadline while the list loads.
That exception gets no path, and the next ones find the list in memory.

## Configuration

| Env var | Default | Purpose |
| ------- | ------- | ------- |
| `GRPC_ADDRESS` | `0.0.0.0:50062` | Bind address for the gRPC server. |
| `METRICS_PORT` | `9101` | HTTP port for `/_liveness`, `/_readiness` and `/metrics`. |
| `MAX_CONCURRENT_REQUESTS` | `256` | In-flight requests before the server answers `UNAVAILABLE`. `0` disables the cap. |
| `CYMBAL_PATH_RESOLUTION_SECRETS` | _empty_ | Comma-separated secrets, current first. Callers send one as `x-cymbal-path-resolution-secret`. Empty rejects every request. |
| `CYMBAL_REPO_PATHS_FOLDER` | `repo_paths` | Object storage folder of the lists. Must equal Django's `OBJECT_STORAGE_ERROR_TRACKING_REPO_PATHS_FOLDER`. |
| `CYMBAL_PATH_RESOLUTION_CACHE_BYTES` | `2147483648` | Memory budget for cached lists. |
| `CYMBAL_PATH_RESOLUTION_MISSING_TTL_SECS` | `120` | How long a missing or unreadable list is remembered. |
| `CYMBAL_PATH_RESOLUTION_MAX_DECOMPRESSED_BYTES` | `67108864` | Largest accepted list after decompression. |
| `CYMBAL_PATH_RESOLUTION_LOAD_TIMEOUT_SECS` | `30` | Limit for one object storage read. |
| `CYMBAL_PATH_RESOLUTION_DRAIN_SECS` | `10` | Time between failing readiness on shutdown and stopping the server. |
| `OBJECT_STORAGE_*` | cymbal defaults | Same object storage settings as the other cymbal modes. `OBJECT_STORAGE_BUCKET` must be the bucket Django writes to. |

The secret is dedicated to this seam, and it is not `INTERNAL_API_SECRET`, so a leak reaches this service only.

## Caller: processing mode

Processing cymbal calls the service from `RepoPathResolver`, which runs in the resolution stage right after the event release is known ([`stages/resolution/repo_paths`](../processing/stages/resolution/repo_paths)).
For each event with a release that has git metadata (`remote_url` and a full `commit_id`), it:

1. Picks the best path of each in-app frame, at most 100 per event:
   - the build path from native debug info (native, Apple and native Go);
   - else the raw `abs_path` (Python, Ruby and PHP), carried over from the raw frames of the same event;
   - else, for Java and Kotlin, a path built from the package (`com.acme.billing.InvoiceKt` gives `com/acme/billing/Invoice.kt`);
   - else the frame `source`.
2. Answers from its cache when every path has a cached `SURE` or `NO_MATCH` answer.
3. Otherwise sends all the paths in one request, routed by rendezvous hash, with one move to the next pod when a pod refuses the connection.
4. Writes `repo_path` on the frames that got `SURE` or `SUPPORT`, and caches `SURE` and `NO_MATCH` answers of a loaded list.

A timeout, an error, a missing list or an unavailable service leaves frames without a path. It never fails the batch.
The feature never changes `source` or any other field that fingerprints use.

| Env var | Default | Purpose |
| ------- | ------- | ------- |
| `CYMBAL_PATH_RESOLUTION_ENABLED` | `false` | Call the service and write `repo_path`. |
| `CYMBAL_PATH_RESOLUTION_HOST` | _empty_ | Headless service host. Empty turns the feature off. |
| `CYMBAL_PATH_RESOLUTION_PORT` | `50062` | gRPC port of the pods. |
| `CYMBAL_PATH_RESOLUTION_SECRET` | _empty_ | Sent as `x-cymbal-path-resolution-secret`. One of the service's `CYMBAL_PATH_RESOLUTION_SECRETS`. |
| `CYMBAL_PATH_RESOLUTION_DEADLINE_MS` | `200` | Limit per event, for the in-flight slot and the call together. |
| `CYMBAL_PATH_RESOLUTION_DNS_REFRESH_SECS` | `30` | How often the pod set is resolved again. |
| `CYMBAL_PATH_RESOLUTION_MAX_IN_FLIGHT` | `32` | Requests in flight per processing pod. |
| `CYMBAL_PATH_RESOLUTION_ANSWER_CACHE_ENTRIES` | `200000` | Size of the answer cache. |
| `CYMBAL_PATH_RESOLUTION_ANSWER_CACHE_TTL_SECS` | `600` | TTL of the answer cache. |

Caller metrics: `cymbal_repo_path_frames_total{outcome}` counts in-app frames by `sure`, `support`, `tie`, `no_match`, `no_list`, `no_release`, `invalid`, `cached`, `timeout` or `error`, and `cymbal_repo_path_request_seconds` times the calls.

## Deployment

1. Deploy `cymbal-path-resolution` pods behind a headless Kubernetes service, so callers can reach each pod by IP.
2. Size pod memory for `CYMBAL_PATH_RESOLUTION_CACHE_BYTES` plus overhead.
3. Check that `/_liveness` and `/_readiness` return `ok`.
4. Only then set `CYMBAL_PATH_RESOLUTION_HOST`, `CYMBAL_PATH_RESOLUTION_SECRET` and `CYMBAL_PATH_RESOLUTION_ENABLED=true` on processing cymbal.

Callers rendezvous-hash `team:{team_id}:repo:{repo}:commit:{commit}` over the pods, so each list stays warm on one pod.
Scaling the service to zero is safe: callers treat an unreachable service as "no path".

## Metrics

| Metric | Labels |
| ------ | ------ |
| `cymbal_path_resolution_requests_total` | `list_state` |
| `cymbal_path_resolution_paths_total` | `outcome` |
| `cymbal_path_resolution_list_cache_total` | `result`: `hit`, `miss` or `negative` |
| `cymbal_path_resolution_list_load_seconds` | `outcome` |
| `cymbal_path_resolution_cache_bytes` | |
| `cymbal_path_resolution_request_seconds` | |

## Local development

`bin/start-rust-service cymbal-path-resolution` starts the mode on `127.0.0.1:50062`, with metrics on port 9109 and the secret `posthog123`.
