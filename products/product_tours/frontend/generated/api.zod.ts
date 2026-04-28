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

export const productToursCreateBodyNameMax = 400

export const productToursCreateBodyCreationContextDefault = `app`

export const ProductToursCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursCreateBodyNameMax),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursCreateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

export const productToursUpdateBodyNameMax = 400

export const ProductToursUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursUpdateBodyNameMax),
        description: zod.string().optional(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
    })
    .describe('Read-only serializer for ProductTour.')

export const productToursPartialUpdateBodyNameMax = 400

export const productToursPartialUpdateBodyCreationContextDefault = `app`

export const ProductToursPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursPartialUpdateBodyNameMax).optional(),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursPartialUpdateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

/**
 * Save draft content (server-side merge). No side effects triggered.
 */
export const productToursDraftPartialUpdateBodyNameMax = 400

export const productToursDraftPartialUpdateBodyCreationContextDefault = `app`

export const ProductToursDraftPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursDraftPartialUpdateBodyNameMax).optional(),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursDraftPartialUpdateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

/**
 * Generate tour step content using AI.
 */
export const productToursGenerateCreateBodyTitleDefault = ``
export const productToursGenerateCreateBodyGoalDefault = ``

export const ProductToursGenerateCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().default(productToursGenerateCreateBodyTitleDefault),
    goal: zod.string().default(productToursGenerateCreateBodyGoalDefault),
    steps: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
})

/**
 * Commit draft to live tour. Runs full validation and triggers side effects.

Accepts an optional body payload. If provided, merges it into the draft
before publishing so the caller can save + publish in a single request.
 */
export const productToursPublishDraftCreateBodyNameMax = 400

export const productToursPublishDraftCreateBodyCreationContextDefault = `app`

export const ProductToursPublishDraftCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursPublishDraftCreateBodyNameMax),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursPublishDraftCreateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')
