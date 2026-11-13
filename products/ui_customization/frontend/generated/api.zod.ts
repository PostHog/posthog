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
 * Replaces the person's layout for the selected context in this project. The context defines its allowed layout schema and limits. Unknown contexts and people without UI customization enabled receive 404.
 * @summary Set the person's UI customization
 */
export const uiCustomizationUpdateBodyLayoutOneVersionDefault = 1
export const uiCustomizationUpdateBodyLayoutOneSectionsItemIdMax = 32

export const uiCustomizationUpdateBodyLayoutOneSectionsItemIdRegExp = new RegExp('^[a-z0-9]+(?:-[a-z0-9]+)\*$')
export const uiCustomizationUpdateBodyLayoutOneSectionsItemTitleOneMax = 60

export const uiCustomizationUpdateBodyLayoutOneSectionsItemTitleOneRegExp = new RegExp('^[^\\x00]\*$')
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneToTwoShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)

export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneToFourShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneMax = 60

export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneRegExp = new RegExp('^[^\\x00]\*$')
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoToTwoShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)

export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoToFourShortIdRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelMax = 60

export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelRegExp = new RegExp('^[^\\x00]\*$')
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoVariantDefault = `outline`
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemThreeInsightRegExp = new RegExp(
    '^[A-Za-z0-9]{1,12}$'
)
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelMax = 60

export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelRegExp = new RegExp('^[^\\x00]\*$')
export const uiCustomizationUpdateBodyLayoutOneSectionsItemItemsMax = 12

export const uiCustomizationUpdateBodyLayoutOneSectionsMax = 10

export const UiCustomizationUpdateBody = /* @__PURE__ */ zod.object({
    layout: zod
        .object({
            version: zod.number().default(uiCustomizationUpdateBodyLayoutOneVersionDefault),
            sections: zod
                .array(
                    zod.object({
                        id: zod
                            .string()
                            .min(1)
                            .max(uiCustomizationUpdateBodyLayoutOneSectionsItemIdMax)
                            .regex(uiCustomizationUpdateBodyLayoutOneSectionsItemIdRegExp)
                            .describe(
                                "Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept by this ID, so keep the ID of an existing section when you move or rename it."
                            ),
                        title: zod
                            .union([
                                zod
                                    .string()
                                    .min(1)
                                    .max(uiCustomizationUpdateBodyLayoutOneSectionsItemTitleOneMax)
                                    .regex(uiCustomizationUpdateBodyLayoutOneSectionsItemTitleOneRegExp),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'Heading of the section. A section with a heading can be closed. A section without one shows its items in its place in the layout, with no heading.'
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
                                                                'dashboards',
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
                                                                uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneToTwoShortIdRegExp
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
                                                                uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneToFourShortIdRegExp
                                                            )
                                                            .describe(
                                                                "The notebook's short ID, as in \/notebooks\/<short_id>."
                                                            ),
                                                    }),
                                                ])
                                                .describe(
                                                    'What the item opens. Only pages, and insights, dashboards and notebooks that exist in this project.'
                                                ),
                                            label: zod
                                                .union([
                                                    zod
                                                        .string()
                                                        .min(1)
                                                        .max(
                                                            uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneMax
                                                        )
                                                        .regex(
                                                            uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemOneLabelOneRegExp
                                                        ),
                                                    zod.null(),
                                                ])
                                                .optional(),
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
                                        })
                                        .describe(
                                            "A link to an Analytics page or a project object. Object links require a label. A page link shows the page's own label and icon unless you set them."
                                        ),
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
                                                                'dashboards',
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
                                                                uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoToTwoShortIdRegExp
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
                                                                uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoToFourShortIdRegExp
                                                            )
                                                            .describe(
                                                                "The notebook's short ID, as in \/notebooks\/<short_id>."
                                                            ),
                                                    }),
                                                ])
                                                .describe(
                                                    'What the item opens. Only pages, and insights, dashboards and notebooks that exist in this project.'
                                                ),
                                            label: zod
                                                .string()
                                                .min(1)
                                                .max(uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelMax)
                                                .regex(
                                                    uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoLabelRegExp
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
                                                    uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemTwoVariantDefault
                                                ),
                                        })
                                        .describe('A button that opens an Analytics page or a project object.'),
                                    zod
                                        .object({
                                            type: zod.literal('metric'),
                                            insight: zod
                                                .string()
                                                .regex(
                                                    uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemThreeInsightRegExp
                                                )
                                                .describe(
                                                    'Short ID of a trends insight, one whose query source kind is TrendsQuery. Link to other insights.'
                                                ),
                                            label: zod
                                                .string()
                                                .min(1)
                                                .max(
                                                    uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelMax
                                                )
                                                .regex(
                                                    uiCustomizationUpdateBodyLayoutOneSectionsItemItemsItemThreeLabelRegExp
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
                                        .describe('A list of pinned, recent, or built-in Analytics items.'),
                                ])
                            )
                            .min(1)
                            .max(uiCustomizationUpdateBodyLayoutOneSectionsItemItemsMax),
                    })
                )
                .min(1)
                .max(uiCustomizationUpdateBodyLayoutOneSectionsMax)
                .describe(
                    'Use at most 30 items across all sections, including at most 4 metrics. Each built-in list counts as one item. Section IDs must be unique. Each list source can appear only once in the layout.'
                ),
        })
        .describe("The Analytics context's fragment. A section with no items to show is hidden.")
        .describe(
            "The layout for the selected context. For analytics_sidebar, the sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. The layout replaces the whole fragment, so send every section to keep."
        ),
})
