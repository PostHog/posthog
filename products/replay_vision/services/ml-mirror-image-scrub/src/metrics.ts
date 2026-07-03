// Sidecar scrub metrics, served from the same HTTP server at /metrics (see server.ts). Shard/Kafka
// metrics live with the consumer in the plugin-server, not here.
import { Counter, Histogram, Registry } from 'prom-client'

export const register = new Registry()

const scrubbed = new Counter({
    name: 'ml_mirror_image_scrub_scrubbed_total',
    help: 'Images scrubbed',
    registers: [register],
})
const failed = new Counter({
    name: 'ml_mirror_image_scrub_failed_total',
    help: 'Transient scrub errors (500) — the consumer retries these',
    registers: [register],
})
const undecodable = new Counter({
    name: 'ml_mirror_image_scrub_undecodable_total',
    help: 'Inputs sharp could not decode (422) — permanently skipped, never retried',
    registers: [register],
})
const rejected = new Counter({
    name: 'ml_mirror_image_scrub_rejected_total',
    help: 'Requests shed for concurrency (503)',
    registers: [register],
})
const aborted = new Counter({
    name: 'ml_mirror_image_scrub_aborted_total',
    help: 'Requests where the consumer hung up before we responded',
    registers: [register],
})
const duration = new Histogram({
    name: 'ml_mirror_image_scrub_duration_seconds',
    help: 'Scrub wall time',
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
    registers: [register],
})

export const ScrubMetrics = {
    incScrubbed: () => scrubbed.inc(),
    incFailed: () => failed.inc(),
    incUndecodable: () => undecodable.inc(),
    incRejected: () => rejected.inc(),
    incAborted: () => aborted.inc(),
    startTimer: (): (() => void) => duration.startTimer(),
}
