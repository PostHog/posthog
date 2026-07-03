export interface Config {
    port: number
    // Concurrent scrubs allowed before the server sheds load with 503.
    maxConcurrency: number
}

export function loadConfig(): Config {
    return {
        port: Number(process.env.IMAGE_SCRUB_PORT ?? 9010),
        maxConcurrency: Number(process.env.IMAGE_SCRUB_CONCURRENCY ?? 8),
    }
}
