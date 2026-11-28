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
 * Create a journey.
 */
export const userJourneysCreateBodyStepsItemOneUrlMax = 2048

export const userJourneysCreateBodyStepsItemOneUrlMatchingDefault = `exact`
export const userJourneysCreateBodyStepsItemTwoSelectorMax = 1024

export const userJourneysCreateBodyStepsItemTwoTextMax = 400

export const userJourneysCreateBodyStepsItemTwoHrefMax = 2048

export const userJourneysCreateBodyStepsItemTwoUrlMax = 2048

export const userJourneysCreateBodyStepsItemTwoUrlMatchingDefault = `exact`
export const userJourneysCreateBodyStepsMin = 2
export const userJourneysCreateBodyStepsMax = 20

export const userJourneysCreateBodyNameMax = 255

export const userJourneysCreateBodyConversionWindowMinutesMax = 1440

export const UserJourneysCreateBody = /* @__PURE__ */ zod.object({
    steps: zod
        .array(
            zod.union([
                zod.object({
                    type: zod.enum(['pageview']).describe('Marks the step as a pageview of a matching URL.'),
                    url: zod
                        .string()
                        .max(userJourneysCreateBodyStepsItemOneUrlMax)
                        .describe('URL, URL fragment or regular expression the page URL must match.'),
                    url_matching: zod
                        .enum(['exact', 'contains', 'regex'])
                        .describe('\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex')
                        .default(userJourneysCreateBodyStepsItemOneUrlMatchingDefault)
                        .describe(
                            'How `url` is compared with the page URL: `exact` matches the whole URL, `contains` matches a case-insensitive substring, and `regex` matches a regular expression.\n\n\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex'
                        ),
                }),
                zod.object({
                    type: zod
                        .enum(['element_click'])
                        .describe('Marks the step as an autocaptured click on a matching element.'),
                    selector: zod
                        .string()
                        .max(userJourneysCreateBodyStepsItemTwoSelectorMax)
                        .describe('CSS selector of the clicked element, for example `button.signup`.'),
                    text: zod
                        .string()
                        .max(userJourneysCreateBodyStepsItemTwoTextMax)
                        .nullish()
                        .describe('Exact text of the clicked element. Leave out to match any text.'),
                    href: zod
                        .string()
                        .max(userJourneysCreateBodyStepsItemTwoHrefMax)
                        .nullish()
                        .describe('Exact link target of the clicked element. Leave out to match any link.'),
                    url: zod
                        .string()
                        .max(userJourneysCreateBodyStepsItemTwoUrlMax)
                        .nullish()
                        .describe('URL of the page the click happens on. Leave out to match the click on any page.'),
                    url_matching: zod
                        .enum(['exact', 'contains', 'regex'])
                        .describe('\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex')
                        .default(userJourneysCreateBodyStepsItemTwoUrlMatchingDefault)
                        .describe(
                            'How `url` is compared with the page URL: `exact` matches the whole URL, `contains` matches a case-insensitive substring, and `regex` matches a regular expression.\n\n\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex'
                        ),
                }),
            ])
        )
        .min(userJourneysCreateBodyStepsMin)
        .max(userJourneysCreateBodyStepsMax)
        .describe(
            'Ordered steps a session must complete, from 2 to 20. Each step is a pageview or a click on an element.'
        ),
    name: zod.string().max(userJourneysCreateBodyNameMax).describe('Display name for the journey.'),
    description: zod.string().optional().describe('What the journey covers and why it matters.'),
    conversion_window_minutes: zod
        .number()
        .min(1)
        .max(userJourneysCreateBodyConversionWindowMinutesMax)
        .optional()
        .describe('Minutes a session has to go from the first step to the last, from 1 to 1440.'),
    source: zod
        .enum(['toolbar', 'manual'])
        .describe('\* `toolbar` - Toolbar\n\* `manual` - Manual')
        .optional()
        .describe(
            'Where the journey was defined: `toolbar` for the toolbar, `manual` for the app or the API.\n\n\* `toolbar` - Toolbar\n\* `manual` - Manual'
        ),
})

/**
 * Change some fields of a journey.
 */
export const userJourneysPartialUpdateBodyStepsItemOneUrlMax = 2048

export const userJourneysPartialUpdateBodyStepsItemOneUrlMatchingDefault = `exact`
export const userJourneysPartialUpdateBodyStepsItemTwoSelectorMax = 1024

export const userJourneysPartialUpdateBodyStepsItemTwoTextMax = 400

export const userJourneysPartialUpdateBodyStepsItemTwoHrefMax = 2048

export const userJourneysPartialUpdateBodyStepsItemTwoUrlMax = 2048

export const userJourneysPartialUpdateBodyStepsItemTwoUrlMatchingDefault = `exact`
export const userJourneysPartialUpdateBodyStepsMin = 2
export const userJourneysPartialUpdateBodyStepsMax = 20

export const userJourneysPartialUpdateBodyNameMax = 255

export const userJourneysPartialUpdateBodyConversionWindowMinutesMax = 1440

export const UserJourneysPartialUpdateBody = /* @__PURE__ */ zod.object({
    steps: zod
        .array(
            zod.union([
                zod.object({
                    type: zod.enum(['pageview']).describe('Marks the step as a pageview of a matching URL.'),
                    url: zod
                        .string()
                        .max(userJourneysPartialUpdateBodyStepsItemOneUrlMax)
                        .describe('URL, URL fragment or regular expression the page URL must match.'),
                    url_matching: zod
                        .enum(['exact', 'contains', 'regex'])
                        .describe('\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex')
                        .default(userJourneysPartialUpdateBodyStepsItemOneUrlMatchingDefault)
                        .describe(
                            'How `url` is compared with the page URL: `exact` matches the whole URL, `contains` matches a case-insensitive substring, and `regex` matches a regular expression.\n\n\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex'
                        ),
                }),
                zod.object({
                    type: zod
                        .enum(['element_click'])
                        .describe('Marks the step as an autocaptured click on a matching element.'),
                    selector: zod
                        .string()
                        .max(userJourneysPartialUpdateBodyStepsItemTwoSelectorMax)
                        .describe('CSS selector of the clicked element, for example `button.signup`.'),
                    text: zod
                        .string()
                        .max(userJourneysPartialUpdateBodyStepsItemTwoTextMax)
                        .nullish()
                        .describe('Exact text of the clicked element. Leave out to match any text.'),
                    href: zod
                        .string()
                        .max(userJourneysPartialUpdateBodyStepsItemTwoHrefMax)
                        .nullish()
                        .describe('Exact link target of the clicked element. Leave out to match any link.'),
                    url: zod
                        .string()
                        .max(userJourneysPartialUpdateBodyStepsItemTwoUrlMax)
                        .nullish()
                        .describe('URL of the page the click happens on. Leave out to match the click on any page.'),
                    url_matching: zod
                        .enum(['exact', 'contains', 'regex'])
                        .describe('\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex')
                        .default(userJourneysPartialUpdateBodyStepsItemTwoUrlMatchingDefault)
                        .describe(
                            'How `url` is compared with the page URL: `exact` matches the whole URL, `contains` matches a case-insensitive substring, and `regex` matches a regular expression.\n\n\* `exact` - Exact\n\* `contains` - Contains\n\* `regex` - Regex'
                        ),
                }),
            ])
        )
        .min(userJourneysPartialUpdateBodyStepsMin)
        .max(userJourneysPartialUpdateBodyStepsMax)
        .optional()
        .describe(
            'Ordered steps a session must complete, from 2 to 20. Each step is a pageview or a click on an element.'
        ),
    name: zod.string().max(userJourneysPartialUpdateBodyNameMax).optional().describe('Display name for the journey.'),
    description: zod.string().optional().describe('What the journey covers and why it matters.'),
    conversion_window_minutes: zod
        .number()
        .min(1)
        .max(userJourneysPartialUpdateBodyConversionWindowMinutesMax)
        .optional()
        .describe('Minutes a session has to go from the first step to the last, from 1 to 1440.'),
    source: zod
        .enum(['toolbar', 'manual'])
        .describe('\* `toolbar` - Toolbar\n\* `manual` - Manual')
        .optional()
        .describe(
            'Where the journey was defined: `toolbar` for the toolbar, `manual` for the app or the API.\n\n\* `toolbar` - Toolbar\n\* `manual` - Manual'
        ),
})
