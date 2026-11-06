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
 * Replaces the layout of the person's Analytics pane. It changes only the person who calls it, in this project. The pane shows the new layout the next time it loads. 400 lists every value that does not fit the layout schema. 404 when the person does not have the new navigation.
 * @summary Set the person's analytics sidebar
 */
export const todayAnalyticsSidebarUpdateBodyLayoutOneVersionDefault = 1
export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdMax = 32

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdRegExp = new RegExp('^[a-z0-9]+(?:-[a-z0-9]+)\*$')
export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemTitleOneMax = 60

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToTwoShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{8}$'
)

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToFourShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{8}$'
)
export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneMax = 60

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToTwoShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{8}$'
)

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToFourShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{8}$'
)
export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelMax = 60

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoVariantDefault = `outline`
export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeInsightRegExp = new RegExp(
    '^[A-Za-z0-9]{8}$'
)
export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelMax = 60

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsMax = 12

export const todayAnalyticsSidebarUpdateBodyLayoutOneSectionsMax = 10

export const TodayAnalyticsSidebarUpdateBody = /* @__PURE__ */ zod.object({
    layout: zod
        .object({
            version: zod.number().default(todayAnalyticsSidebarUpdateBodyLayoutOneVersionDefault),
            sections: zod
                .array(
                    zod.object({
                        id: zod
                            .string()
                            .min(1)
                            .max(todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdMax)
                            .regex(todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdRegExp)
                            .describe(
                                "Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept by this ID."
                            ),
                        title: zod
                            .union([
                                zod
                                    .string()
                                    .min(1)
                                    .max(todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemTitleOneMax),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'Heading of the section. A section with a heading can be closed. Without one, its items show at the top.'
                            ),
                        icon: zod
                            .union([
                                zod.enum([
                                    'list',
                                    'person',
                                    'people',
                                    'box',
                                    'bell',
                                    'notification',
                                    'posthog',
                                    'chart',
                                    'dashboard',
                                    'notebook',
                                    'sql',
                                    'star',
                                    'rocket',
                                    'target',
                                    'trending',
                                    'globe',
                                    'sparkle',
                                    'bolt',
                                    'flag',
                                    'warning',
                                ]),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Icon before the heading.'),
                        items: zod
                            .array(
                                zod.union([
                                    zod
                                        .object({
                                            type: zod.literal('link'),
                                            to: zod
                                                .union([
                                                    zod
                                                        .object({
                                                            kind: zod.literal('page'),
                                                            page: zod.enum([
                                                                'analytics_all',
                                                                'analytics_mine',
                                                                'collections',
                                                                'alerts',
                                                                'subscriptions',
                                                                'product_analytics',
                                                                'web_analytics',
                                                                'sql_editor',
                                                                'new_insight',
                                                            ]),
                                                        })
                                                        .describe('A PostHog page. It has its own label and icon.'),
                                                    zod.object({
                                                        kind: zod.literal('insight'),
                                                        short_id: zod
                                                            .string()
                                                            .regex(
                                                                todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToTwoShortIdRegExp
                                                            )
                                                            .describe(
                                                                "The insight's short ID, as in \/insights\/<short_id>."
                                                            ),
                                                    }),
                                                    zod.object({
                                                        kind: zod.literal('dashboard'),
                                                        id: zod.number().min(1).describe("The dashboard's numeric ID."),
                                                    }),
                                                    zod.object({
                                                        kind: zod.literal('notebook'),
                                                        short_id: zod
                                                            .string()
                                                            .regex(
                                                                todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToFourShortIdRegExp
                                                            )
                                                            .describe(
                                                                "The notebook's short ID, as in \/notebooks\/<short_id>."
                                                            ),
                                                    }),
                                                ])
                                                .describe(
                                                    'What the item opens. Only pages and objects of this project.'
                                                ),
                                            label: zod
                                                .union([
                                                    zod
                                                        .string()
                                                        .min(1)
                                                        .max(
                                                            todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneMax
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    "Text of the row. Leave it out for a page to use the page's name. Required otherwise."
                                                ),
                                            icon: zod
                                                .union([
                                                    zod.enum([
                                                        'list',
                                                        'person',
                                                        'people',
                                                        'box',
                                                        'bell',
                                                        'notification',
                                                        'posthog',
                                                        'chart',
                                                        'dashboard',
                                                        'notebook',
                                                        'sql',
                                                        'star',
                                                        'rocket',
                                                        'target',
                                                        'trending',
                                                        'globe',
                                                        'sparkle',
                                                        'bolt',
                                                        'flag',
                                                        'warning',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe('Icon of the row. A page has its own icon.'),
                                        })
                                        .describe('A row that opens a page or an object.'),
                                    zod
                                        .object({
                                            type: zod.literal('button'),
                                            to: zod
                                                .union([
                                                    zod
                                                        .object({
                                                            kind: zod.literal('page'),
                                                            page: zod.enum([
                                                                'analytics_all',
                                                                'analytics_mine',
                                                                'collections',
                                                                'alerts',
                                                                'subscriptions',
                                                                'product_analytics',
                                                                'web_analytics',
                                                                'sql_editor',
                                                                'new_insight',
                                                            ]),
                                                        })
                                                        .describe('A PostHog page. It has its own label and icon.'),
                                                    zod.object({
                                                        kind: zod.literal('insight'),
                                                        short_id: zod
                                                            .string()
                                                            .regex(
                                                                todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToTwoShortIdRegExp
                                                            )
                                                            .describe(
                                                                "The insight's short ID, as in \/insights\/<short_id>."
                                                            ),
                                                    }),
                                                    zod.object({
                                                        kind: zod.literal('dashboard'),
                                                        id: zod.number().min(1).describe("The dashboard's numeric ID."),
                                                    }),
                                                    zod.object({
                                                        kind: zod.literal('notebook'),
                                                        short_id: zod
                                                            .string()
                                                            .regex(
                                                                todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToFourShortIdRegExp
                                                            )
                                                            .describe(
                                                                "The notebook's short ID, as in \/notebooks\/<short_id>."
                                                            ),
                                                    }),
                                                ])
                                                .describe(
                                                    'What the item opens. Only pages and objects of this project.'
                                                ),
                                            label: zod
                                                .string()
                                                .min(1)
                                                .max(
                                                    todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelMax
                                                ),
                                            icon: zod
                                                .union([
                                                    zod.enum([
                                                        'list',
                                                        'person',
                                                        'people',
                                                        'box',
                                                        'bell',
                                                        'notification',
                                                        'posthog',
                                                        'chart',
                                                        'dashboard',
                                                        'notebook',
                                                        'sql',
                                                        'star',
                                                        'rocket',
                                                        'target',
                                                        'trending',
                                                        'globe',
                                                        'sparkle',
                                                        'bolt',
                                                        'flag',
                                                        'warning',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .optional(),
                                            variant: zod
                                                .enum(['default', 'primary', 'outline'])
                                                .default(
                                                    todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoVariantDefault
                                                ),
                                        })
                                        .describe(
                                            'A button that opens a page or an object. Use it for an action, such as a new insight.'
                                        ),
                                    zod
                                        .object({
                                            type: zod.literal('metric'),
                                            insight: zod
                                                .string()
                                                .regex(
                                                    todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeInsightRegExp
                                                )
                                                .describe('Short ID of a trends insight.'),
                                            label: zod
                                                .string()
                                                .min(1)
                                                .max(
                                                    todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelMax
                                                )
                                                .describe('Short name of the number, such as Signups.'),
                                        })
                                        .describe(
                                            'The latest value of a trends insight, with a sparkline of its first series. Opens the insight.'
                                        ),
                                    zod
                                        .object({
                                            type: zod.literal('list'),
                                            source: zod.enum(['pinned', 'recents', 'by_posthog']),
                                        })
                                        .describe('A list that PostHog fills, such as the items the person pinned.'),
                                ])
                            )
                            .min(1)
                            .max(todayAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsMax),
                    })
                )
                .min(1)
                .max(todayAnalyticsSidebarUpdateBodyLayoutOneSectionsMax),
        })
        .describe('The sections of the Analytics pane, from top to bottom. A section with no items to show is hidden.')
        .describe(
            "The sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. The layout replaces the whole sidebar, so send every section to keep."
        ),
})

/**
 * Asks the decision model which of several code excerpts shows what a finding describes. Returns null when it is unsure. 404 when the person may not use Jev.
 * @summary Pick the code excerpt a finding describes
 */
export const todayExcerptChoiceCreateBodyFindingMax = 6000

export const todayExcerptChoiceCreateBodyExcerptsItemMax = 2000

export const todayExcerptChoiceCreateBodyExcerptsMin = 2
export const todayExcerptChoiceCreateBodyExcerptsMax = 5

export const TodayExcerptChoiceCreateBody = /* @__PURE__ */ zod.object({
    finding: zod
        .string()
        .max(todayExcerptChoiceCreateBodyFindingMax)
        .describe('The finding the code excerpts should show.'),
    excerpts: zod
        .array(zod.string().max(todayExcerptChoiceCreateBodyExcerptsItemMax))
        .min(todayExcerptChoiceCreateBodyExcerptsMin)
        .max(todayExcerptChoiceCreateBodyExcerptsMax)
        .describe('Candidate code excerpts, best scored first.'),
})

/**
 * Replaces the numbers the person keeps at the start of the key numbers, in order. Repeated keys are dropped and only the first 4 are kept. The next highlights request computes the new numbers. 404 when the person does not have the new navigation.
 * @summary Set the numbers the person keeps
 */
export const todayPulsePinsUpdateBodyPinsItemKeyMax = 200

export const todayPulsePinsUpdateBodyPinsItemNameMax = 400

export const TodayPulsePinsUpdateBody = /* @__PURE__ */ zod.object({
    pins: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .max(todayPulsePinsUpdateBodyPinsItemKeyMax)
                    .describe(
                        'Key of the number to keep: a key metric setting such as signup_event, or insight:<short_id>.'
                    ),
                name: zod
                    .string()
                    .max(todayPulsePinsUpdateBodyPinsItemNameMax)
                    .describe('Name to show for the number until the highlights compute its value.'),
                dashboard_id: zod
                    .number()
                    .nullish()
                    .describe(
                        'For an insight pinned from a dashboard tile, the dashboard whose filters it keeps. Null otherwise.'
                    ),
            })
        )
        .describe(
            'Numbers the person keeps at the start of the key numbers, in order. Suggestions fill the free places. Only the first 4 distinct keys are kept. At most 20 entries.'
        ),
})
