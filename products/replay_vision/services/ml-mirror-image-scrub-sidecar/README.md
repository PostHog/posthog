# Replay Vision ML Mirror Image Scrub Sidecar

This package builds a small sidecar that is installed alongside the image scrubber kafka consumer at `nodejs/src/servers/ingestion-session-replay-ml-image-scrub-server.ts`

It is intentionally kept separate from the root pnpm workspace, as the ML deps are several hundred MB. I did not want to add this to every CI run, every dev's local machine's worktree, etc

It runs a simple http server, receives an image and replies with the scrubbed image. The interface is fully trusted as it only communicates with the kafka consumer in the same pod. It binds loopback only, so it must run as a sidecar container sharing the consumer's network namespace, not as its own service.

## HTTP contract

`POST /scrub` with the raw image bytes returns the scrubbed bytes (200). The status split is load-bearing and both sides must change together: the consumer permanently skips 413 (too large) and 422 (undecodable), and retries then replays 500 (transient) and 503 (busy). See `scrub-client.ts` for the consumer half.
