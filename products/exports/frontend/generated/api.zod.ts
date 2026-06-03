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

export const ExportsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        export_format: zod
            .enum([
                'image/png',
                'application/pdf',
                'text/csv',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'video/webm',
                'video/mp4',
                'image/gif',
                'application/json',
            ])
            .describe(
                '\* `image\/png` - image\/png\n\* `application\/pdf` - application\/pdf\n\* `text\/csv` - text\/csv\n\* `application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet\n\* `video\/webm` - video\/webm\n\* `video\/mp4` - video\/mp4\n\* `image\/gif` - image\/gif\n\* `application\/json` - application\/json'
            ),
        export_context: zod.unknown().optional(),
    })
    .describe("Standard ExportedAsset serializer that doesn't return content.")
