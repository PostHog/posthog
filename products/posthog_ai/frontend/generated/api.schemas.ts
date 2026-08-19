/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `pending` - Pending
 * * `completed` - Completed
 * * `skipped` - Skipped
 */
export type ScrapingStatusEnumApi = (typeof ScrapingStatusEnumApi)[keyof typeof ScrapingStatusEnumApi]

export const ScrapingStatusEnumApi = {
    Pending: 'pending',
    Completed: 'completed',
    Skipped: 'skipped',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export interface MaxCoreMemoryApi {
    readonly id: string
    /** @maxLength 10000 */
    text: string
    scraping_status?: ScrapingStatusEnumApi | BlankEnumApi | null
}

export interface PaginatedMaxCoreMemoryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MaxCoreMemoryApi[]
}

export interface PatchedMaxCoreMemoryApi {
    readonly id?: string
    /** @maxLength 10000 */
    text?: string
    scraping_status?: ScrapingStatusEnumApi | BlankEnumApi | null
}

export interface SynthesizeApi {
    /**
     * The text the assistant should speak aloud.
     * @maxLength 2000
     */
    text: string
}

export interface HandsFreeTokenApi {
    /** Single-use token for ElevenLabs realtime transcription. */
    token: string
}

export interface DocsSearchRequestApi {
    /** Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question. */
    query: string
}

export interface DocsSearchResponseApi {
    /** Markdown-formatted documentation results. Each block has a title, URL and excerpt; an empty result set returns guidance to navigate to https://posthog.com/docs. */
    content: string
}

export type CoreMemoryListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type McpToolsCreate200 = { [key: string]: unknown }
