// Sidecar runtime config. The consumer (in the plugin-server) owns Kafka + S3; this service only scrubs
// bytes, so all it needs is a port and a concurrency ceiling.
export interface Config {
    port: number
    // Max concurrent scrubs before shedding load (503). sharp/ML work is CPU-bound and off-thread, so this
    // bounds memory and event-loop pressure; the consumer retries a shed request.
    maxConcurrency: number
}

export function loadConfig(): Config {
    return {
        port: Number(process.env.IMAGE_SCRUB_PORT ?? 9010),
        maxConcurrency: Number(process.env.IMAGE_SCRUB_CONCURRENCY ?? 8),
    }
}
