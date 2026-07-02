// Sidecar scrub metrics, served from the same HTTP server at /metrics (see server.ts). Shard/Kafka
// metrics live with the consumer in the plugin-server, not here.
import { Counter, Histogram, Registry } from 'prom-client'

export const register = new Registry()

const scrubbed = new Counter({
    name: 'ml_mirror_image_scrub_scrubbed_total',
    help: 'Images scrubbed',
    registers: [register],
})
const failed = new Counter({ name: 'ml_mirror_image_scrub_failed_total', help: 'Scrub errors', registers: [register] })
const rejected = new Counter({
    name: 'ml_mirror_image_scrub_rejected_total',
    help: 'Requests shed for concurrency (503)',
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
    incRejected: () => rejected.inc(),
    startTimer: (): (() => void) => duration.startTimer(),
}
