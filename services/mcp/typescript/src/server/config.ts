export interface Config {
    port: number
    redisUrl: string | undefined
    internalApiUrlUs: string | undefined
    internalApiUrlEu: string | undefined
    inkeepApiKey: string | undefined
}

export function loadConfig(): Config {
    return {
        port: parseInt(process.env.PORT || '8080', 10),
        redisUrl: process.env.REDIS_URL,
        internalApiUrlUs: process.env.POSTHOG_API_INTERNAL_URL_US,
        internalApiUrlEu: process.env.POSTHOG_API_INTERNAL_URL_EU,
        inkeepApiKey: process.env.INKEEP_API_KEY,
    }
}
