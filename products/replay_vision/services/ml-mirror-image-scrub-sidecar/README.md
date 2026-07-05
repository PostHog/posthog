# Replay Vision ML Mirror Image Scrub Sidecar

This package builds a small sidecar that is installed alongside the image scrubber kafka consumer at nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/ml-mirror-pipeline.ts

It is intentionally kept separate from the root pnpm workspace, as the ML deps are several hundred MB. I did not want to add this to every CI run, every dev's local machine's worktree, etc

It runs a simple http server, receives an image and replies with the scrubbed image. The interface is fully trusted as it only communicates with the kafka consumer in the same docker image.
