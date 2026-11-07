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
 * Replaces the layout of the person's Analytics pane. It changes only the person who calls it, in this project. The pane shows the new layout the next time it loads. 400 lists every value that does not fit the layout schema. 404 when the person does not have UI customization enabled.
 * @summary Set the person's analytics sidebar
 */
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneVersionDefault = 1
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdMax = 32

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdRegExp = new RegExp(
    '^[a-z0-9]+(?:-[a-z0-9]+)\*$'
)
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemTitleOneMax = 60

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemTitleOneRegExp = new RegExp('^[^\\x00]\*$')
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToTwoShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToFourShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneMax = 60

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneRegExp = new RegExp(
    '^[^\\x00]\*$'
)
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToTwoShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToFourShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelMax = 60

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelRegExp = new RegExp(
    '^[^\\x00]\*$'
)
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoVariantDefault = `outline`
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeInsightRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelMax = 60

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelRegExp = new RegExp(
    '^[^\\x00]\*$'
)
export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsMax = 12

export const uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsMax = 10

export const UiCustomizationAnalyticsSidebarUpdateBody = /* @__PURE__ */ zod.object({
    layout: zod
        .object({
            version: zod.number().default(uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneVersionDefault),
            sections: zod
                .array(
                    zod.object({
                        id: zod
                            .string()
                            .min(1)
                            .max(uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdMax)
                            .regex(uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemIdRegExp)
                            .describe(
                                "Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept by this ID."
                            ),
                        title: zod
                            .union([
                                zod
                                    .string()
                                    .min(1)
                                    .max(uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemTitleOneMax)
                                    .regex(
                                        uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemTitleOneRegExp
                                    ),
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
                                                                uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToTwoShortIdRegExp
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
                                                                uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneToFourShortIdRegExp
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
                                                            uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneMax
                                                        )
                                                        .regex(
                                                            uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneRegExp
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
                                                                uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToTwoShortIdRegExp
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
                                                                uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoToFourShortIdRegExp
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
                                                    uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelMax
                                                )
                                                .regex(
                                                    uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelRegExp
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
                                                    uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemTwoVariantDefault
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
                                                    uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeInsightRegExp
                                                )
                                                .describe('Short ID of a trends insight.'),
                                            label: zod
                                                .string()
                                                .min(1)
                                                .max(
                                                    uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelMax
                                                )
                                                .regex(
                                                    uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelRegExp
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
                            .max(uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsItemItemsMax),
                    })
                )
                .min(1)
                .max(uiCustomizationAnalyticsSidebarUpdateBodyLayoutOneSectionsMax),
        })
        .describe('The sections of the Analytics pane, from top to bottom. A section with no items to show is hidden.')
        .describe(
            "The sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. The layout replaces the whole sidebar, so send every section to keep."
        ),
})
