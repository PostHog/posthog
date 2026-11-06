/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * The layout of the Analytics pane in the new navigation: the person's own layout, or the default when they have not saved one. Read it before you change it, so you keep the sections the person wants. 404 when the person does not have the new navigation.
 * @summary Get the person's analytics sidebar
 */
export const TodayAnalyticsSidebarRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Replaces the layout of the person's Analytics pane. It changes only the person who calls it, in this project. The pane shows the new layout the next time it loads. 400 lists every value that does not fit the layout schema. 404 when the person does not have the new navigation.
 * @summary Set the person's analytics sidebar
 */
export const TodayAnalyticsSidebarUpdateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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

export const TodayAnalyticsSidebarUpdateBody = () => zod.strictObject({
    layout: zod
        .strictObject({
            version: zod.number().default(todayAnalyticsSidebarUpdateBodyLayoutOneVersionDefault),
            sections: zod
                .array(
                    zod.strictObject({
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
                                        .strictObject({
                                            type: zod.literal('link'),
                                            to: zod
                                                .union([
                                                    zod
                                                        .strictObject({
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
                                                    zod.strictObject({
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
                                                    zod.strictObject({
                                                        kind: zod.literal('dashboard'),
                                                        id: zod.number().min(1).describe("The dashboard's numeric ID."),
                                                    }),
                                                    zod.strictObject({
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
                                        .strictObject({
                                            type: zod.literal('button'),
                                            to: zod
                                                .union([
                                                    zod
                                                        .strictObject({
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
                                                    zod.strictObject({
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
                                                    zod.strictObject({
                                                        kind: zod.literal('dashboard'),
                                                        id: zod.number().min(1).describe("The dashboard's numeric ID."),
                                                    }),
                                                    zod.strictObject({
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
                                        .strictObject({
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
                                        .strictObject({
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
        .describe(
            "The sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. The layout replaces the whole sidebar, so send every section to keep."
        ),
})

/**
 * Removes the person's own layout, so the Analytics pane shows the default again. Returns the default layout. 404 when the person does not have the new navigation.
 * @summary Reset the person's analytics sidebar
 */
export const TodayAnalyticsSidebarDestroyParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
