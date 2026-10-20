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

/**
 * Register a workflow, survey, cohort, or event as a recruiting source.
 */
export const researchDeskSourcesCreateBodyExternalIdMax = 400

export const researchDeskSourcesCreateBodyLabelMax = 255

export const researchDeskSourcesCreateBodyOwnerEmailOneDefault = ``
export const researchDeskSourcesCreateBodyOwnerEmailTwoMax = 0

export const researchDeskSourcesCreateBodyProductAreaDefault = ``
export const researchDeskSourcesCreateBodyProductAreaMax = 128

export const ResearchDeskSourcesCreateBody = /* @__PURE__ */ zod.object({
    kind: zod
        .enum(['workflow', 'survey', 'cohort', 'event'])
        .describe('\* `workflow` - Workflow\n\* `survey` - Survey\n\* `cohort` - Cohort\n\* `event` - Event')
        .describe(
            'What the source is: a workflow, survey, cohort, or event name.\n\n\* `workflow` - Workflow\n\* `survey` - Survey\n\* `cohort` - Cohort\n\* `event` - Event'
        ),
    external_id: zod
        .string()
        .max(researchDeskSourcesCreateBodyExternalIdMax)
        .describe('Workflow ID, survey ID, cohort ID, or event name, depending on kind.'),
    label: zod.string().max(researchDeskSourcesCreateBodyLabelMax).describe('Human-readable name for the source.'),
    owner_email: zod
        .union([
            zod.email().default(researchDeskSourcesCreateBodyOwnerEmailOneDefault),
            zod.string().max(researchDeskSourcesCreateBodyOwnerEmailTwoMax),
        ])
        .optional()
        .describe('Email of the employee who runs this outreach.'),
    product_area: zod
        .string()
        .max(researchDeskSourcesCreateBodyProductAreaMax)
        .default(researchDeskSourcesCreateBodyProductAreaDefault)
        .describe('Product area the outreach is about.'),
})

/**
 * Update a source's label, owner, product area, or active state.
 */
export const researchDeskSourcesPartialUpdateBodyLabelMax = 255

export const researchDeskSourcesPartialUpdateBodyOwnerEmailTwoMax = 0

export const researchDeskSourcesPartialUpdateBodyProductAreaMax = 128

export const ResearchDeskSourcesPartialUpdateBody = /* @__PURE__ */ zod.object({
    label: zod
        .string()
        .max(researchDeskSourcesPartialUpdateBodyLabelMax)
        .optional()
        .describe('Human-readable name for the source.'),
    owner_email: zod
        .union([zod.email(), zod.string().max(researchDeskSourcesPartialUpdateBodyOwnerEmailTwoMax)])
        .optional()
        .describe('Email of the employee who runs this outreach.'),
    product_area: zod
        .string()
        .max(researchDeskSourcesPartialUpdateBodyProductAreaMax)
        .optional()
        .describe('Product area the outreach is about.'),
    active: zod.boolean().optional().describe('Set to false to stop counting this source.'),
})
