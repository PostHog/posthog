/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const DocsSearchRequestApi = zod.object({
    query: zod
        .string()
        .describe(
            'Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question.'
        ),
})

export type DocsSearchRequestApi = zod.input<typeof DocsSearchRequestApi>
export type DocsSearchRequestApiOutput = zod.output<typeof DocsSearchRequestApi>

export const DocsSearchResponseApi = zod.object({
    content: zod
        .string()
        .describe(
            'Markdown-formatted documentation results. Each block has a title, URL and excerpt; an empty result set returns guidance to navigate to https:\/\/posthog.com\/docs.'
        ),
})

export type DocsSearchResponseApi = zod.input<typeof DocsSearchResponseApi>
export type DocsSearchResponseApiOutput = zod.output<typeof DocsSearchResponseApi>
