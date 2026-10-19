/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Check whether PostHog recently contacted these people or this company for research.
 *
 * Returns every research touch found across registered sources and detected sessions.
 * A warning is advice: anyone can still reach out.
 */
export const ResearchDeskContactCheckListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const researchDeskContactCheckListQueryDomainMax = 253

export const researchDeskContactCheckListQueryEmailsItemMax = 320

export const researchDeskContactCheckListQueryEmailsMax = 50

export const researchDeskContactCheckListQueryLookbackDaysDefault = 180
export const researchDeskContactCheckListQueryLookbackDaysMax = 730

export const researchDeskContactCheckListQueryWarnWithinDaysDefault = 60
export const researchDeskContactCheckListQueryWarnWithinDaysMin = 0
export const researchDeskContactCheckListQueryWarnWithinDaysMax = 730

export const ResearchDeskContactCheckListQueryParams = () => zod.object({
    domain: zod
        .string()
        .max(researchDeskContactCheckListQueryDomainMax)
        .optional()
        .describe("Company domain to check, such as 'example.com'. Matches anyone at that domain."),
    emails: zod
        .array(zod.string().max(researchDeskContactCheckListQueryEmailsItemMax))
        .max(researchDeskContactCheckListQueryEmailsMax)
        .optional()
        .describe('Emails to check. Repeat the parameter or pass a comma-separated list.'),
    lookback_days: zod
        .number()
        .min(1)
        .max(researchDeskContactCheckListQueryLookbackDaysMax)
        .default(researchDeskContactCheckListQueryLookbackDaysDefault)
        .describe('How far back to search, in days.'),
    warn_within_days: zod
        .number()
        .min(researchDeskContactCheckListQueryWarnWithinDaysMin)
        .max(researchDeskContactCheckListQueryWarnWithinDaysMax)
        .default(researchDeskContactCheckListQueryWarnWithinDaysDefault)
        .describe('Touches within this many days set recently_contacted.'),
})

/**
 * List customer research sessions, ordered by start time.
 */
export const ResearchDeskSessionsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ResearchDeskSessionsListQueryParams = () => zod.object({
    start_after: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only return sessions that start at or after this time (ISO 8601).'),
    start_before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only return sessions that start before this time (ISO 8601).'),
})

/**
 * List recruiting sources whose events count as research touches.
 */
export const ResearchDeskSourcesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Register a workflow, survey, cohort, or event as a recruiting source.
 */
export const ResearchDeskSourcesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const researchDeskSourcesCreateBodyExternalIdMax = 400

export const researchDeskSourcesCreateBodyLabelMax = 255

export const researchDeskSourcesCreateBodyOwnerEmailOneDefault = ``
export const researchDeskSourcesCreateBodyOwnerEmailTwoMax = 0

export const researchDeskSourcesCreateBodyProductAreaDefault = ``
export const researchDeskSourcesCreateBodyProductAreaMax = 128

export const ResearchDeskSourcesCreateBody = () => zod.object({
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
export const ResearchDeskSourcesPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const researchDeskSourcesPartialUpdateBodyLabelMax = 255

export const researchDeskSourcesPartialUpdateBodyOwnerEmailTwoMax = 0

export const researchDeskSourcesPartialUpdateBodyProductAreaMax = 128

export const ResearchDeskSourcesPartialUpdateBody = () => zod.object({
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
