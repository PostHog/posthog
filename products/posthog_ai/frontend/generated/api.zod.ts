/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const coreMemoryCreateBodyTextMax = 10000

export const CoreMemoryCreateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(coreMemoryCreateBodyTextMax),
    scraping_status: zod
        .union([
            zod
                .enum(['pending', 'completed', 'skipped'])
                .describe('\* `pending` - Pending\n\* `completed` - Completed\n\* `skipped` - Skipped'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
})

export const coreMemoryUpdateBodyTextMax = 10000

export const CoreMemoryUpdateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(coreMemoryUpdateBodyTextMax),
    scraping_status: zod
        .union([
            zod
                .enum(['pending', 'completed', 'skipped'])
                .describe('\* `pending` - Pending\n\* `completed` - Completed\n\* `skipped` - Skipped'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
})

export const coreMemoryPartialUpdateBodyTextMax = 10000

export const CoreMemoryPartialUpdateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(coreMemoryPartialUpdateBodyTextMax).optional(),
    scraping_status: zod
        .union([
            zod
                .enum(['pending', 'completed', 'skipped'])
                .describe('\* `pending` - Pending\n\* `completed` - Completed\n\* `skipped` - Skipped'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
})

/**
 * Proxy text-to-speech to ElevenLabs, streaming mp3 audio back to the browser.
 *
 * The viewset has no per-action `parser_classes` other than this one because the
 * token endpoint takes no body. Putting JSONParser here keeps the rest of the
 * viewset parser-free.
 */
export const maxHandsFreeSynthesizeCreateBodyTextMax = 2000

export const MaxHandsFreeSynthesizeCreateBody = /* @__PURE__ */ zod.object({
    text: zod
        .string()
        .max(maxHandsFreeSynthesizeCreateBodyTextMax)
        .describe('The text the assistant should speak aloud.'),
})

/**
 * Run a hybrid (semantic + full-text) RAG search over the PostHog documentation via Inkeep. Returns a markdown body with title, URL, and excerpt for each match for the agent to cite back to the user.
 * @summary Search PostHog documentation
 */
export const DocsSearchBody = /* @__PURE__ */ zod.object({
    query: zod
        .string()
        .describe(
            'Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question.'
        ),
})
