export interface Config {
    port: number
    // Concurrent scrubs allowed before the server sheds load with 503.
    maxConcurrency: number
    // Reject bodies larger than this (413) so the service owns its own memory bound, not the caller's Kafka
    // limits. Default is above the ~10 MiB Kafka message ceiling; anything bigger is anomalous, skip it.
    maxBodyBytes: number
}

export function loadConfig(): Config {
    return {
        port: Number(process.env.IMAGE_SCRUB_PORT ?? 9010),
        maxConcurrency: Number(process.env.IMAGE_SCRUB_CONCURRENCY ?? 8),
        maxBodyBytes: Number(process.env.IMAGE_SCRUB_MAX_BODY_BYTES ?? 20 * 1024 * 1024),
    }
}
