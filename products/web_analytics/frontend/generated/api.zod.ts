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

export const savedCreateBodyNameMax = 400

export const savedCreateBodyUrlMax = 2000

export const savedCreateBodyDataUrlMax = 2000

export const SavedCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedCreateBodyNameMax).nullish(),
    url: zod.url().max(savedCreateBodyUrlMax),
    data_url: zod.url().max(savedCreateBodyDataUrlMax).nullish().describe('URL for fetching heatmap data'),
    target_widths: zod.unknown().optional(),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .optional()
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording'),
    deleted: zod.boolean().optional(),
})

export const savedPartialUpdateBodyNameMax = 400

export const savedPartialUpdateBodyUrlMax = 2000

export const savedPartialUpdateBodyDataUrlMax = 2000

export const SavedPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedPartialUpdateBodyNameMax).nullish(),
    url: zod.url().max(savedPartialUpdateBodyUrlMax).optional(),
    data_url: zod.url().max(savedPartialUpdateBodyDataUrlMax).nullish().describe('URL for fetching heatmap data'),
    target_widths: zod.unknown().optional(),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .optional()
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording'),
    deleted: zod.boolean().optional(),
})

export const savedRegenerateCreateBodyNameMax = 400

export const savedRegenerateCreateBodyUrlMax = 2000

export const savedRegenerateCreateBodyDataUrlMax = 2000

export const SavedRegenerateCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(savedRegenerateCreateBodyNameMax).nullish(),
    url: zod.url().max(savedRegenerateCreateBodyUrlMax),
    data_url: zod.url().max(savedRegenerateCreateBodyDataUrlMax).nullish().describe('URL for fetching heatmap data'),
    target_widths: zod.unknown().optional(),
    type: zod
        .enum(['screenshot', 'iframe', 'recording'])
        .optional()
        .describe('\* `screenshot` - Screenshot\n\* `iframe` - Iframe\n\* `recording` - Recording'),
    deleted: zod.boolean().optional(),
})

export const webAnalyticsFilterPresetsCreateBodyNameMax = 400

export const WebAnalyticsFilterPresetsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsCreateBodyNameMax),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})

export const webAnalyticsFilterPresetsUpdateBodyNameMax = 400

export const WebAnalyticsFilterPresetsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsUpdateBodyNameMax),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})

export const webAnalyticsFilterPresetsPartialUpdateBodyNameMax = 400

export const WebAnalyticsFilterPresetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(webAnalyticsFilterPresetsPartialUpdateBodyNameMax).optional(),
    description: zod.string().optional(),
    pinned: zod.boolean().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.unknown().optional(),
})
