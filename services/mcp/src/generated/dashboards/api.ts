/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 26 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const DashboardsCollaboratorsListParams = zod.object({
    dashboard_id: zod.number(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dashboardsCollaboratorsListResponseUserOneDistinctIdMax = 200

export const dashboardsCollaboratorsListResponseUserOneFirstNameMax = 150

export const dashboardsCollaboratorsListResponseUserOneLastNameMax = 150

export const dashboardsCollaboratorsListResponseUserOneEmailMax = 254

export const DashboardsCollaboratorsListResponseItem = zod.object({
    id: zod.string().optional(),
    dashboard_id: zod.number().optional(),
    user: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(dashboardsCollaboratorsListResponseUserOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dashboardsCollaboratorsListResponseUserOneFirstNameMax).optional(),
            last_name: zod.string().max(dashboardsCollaboratorsListResponseUserOneLastNameMax).optional(),
            email: zod.string().email().max(dashboardsCollaboratorsListResponseUserOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .optional(),
    level: zod
        .union([zod.literal(21), zod.literal(37)])
        .describe('* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'),
    added_at: zod.string().datetime({}).optional(),
    updated_at: zod.string().datetime({}).optional(),
    user_uuid: zod.string(),
})
export const DashboardsCollaboratorsListResponse = zod.array(DashboardsCollaboratorsListResponseItem)

export const DashboardsCollaboratorsCreateParams = zod.object({
    dashboard_id: zod.number(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsCollaboratorsCreateBody = zod.object({
    level: zod
        .union([zod.literal(21), zod.literal(37)])
        .describe('* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'),
    user_uuid: zod.string(),
})

export const DashboardsCollaboratorsDestroyParams = zod.object({
    dashboard_id: zod.number(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    user__uuid: zod.string(),
})

export const DashboardsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsListQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const dashboardsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const dashboardsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const dashboardsListResponseResultsItemCreatedByOneLastNameMax = 150

export const dashboardsListResponseResultsItemCreatedByOneEmailMax = 254

export const DashboardsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number().optional(),
                name: zod.string().nullish().describe('Name of the dashboard.'),
                description: zod.string().optional().describe('Description of the dashboard.'),
                pinned: zod.boolean().optional().describe('Whether the dashboard is pinned to the top of the list.'),
                created_at: zod.string().datetime({}).optional(),
                created_by: zod
                    .object({
                        id: zod.number().optional(),
                        uuid: zod.string().optional(),
                        distinct_id: zod
                            .string()
                            .max(dashboardsListResponseResultsItemCreatedByOneDistinctIdMax)
                            .nullish(),
                        first_name: zod
                            .string()
                            .max(dashboardsListResponseResultsItemCreatedByOneFirstNameMax)
                            .optional(),
                        last_name: zod
                            .string()
                            .max(dashboardsListResponseResultsItemCreatedByOneLastNameMax)
                            .optional(),
                        email: zod.string().email().max(dashboardsListResponseResultsItemCreatedByOneEmailMax),
                        is_email_verified: zod.boolean().nullish(),
                        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                        role_at_organization: zod
                            .union([
                                zod
                                    .enum([
                                        'engineering',
                                        'data',
                                        'product',
                                        'founder',
                                        'leadership',
                                        'marketing',
                                        'sales',
                                        'other',
                                    ])
                                    .describe(
                                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                    ),
                                zod.enum(['']),
                                zod.literal(null),
                            ])
                            .nullish(),
                    })
                    .optional(),
                last_accessed_at: zod.string().datetime({}).nullish(),
                last_viewed_at: zod.string().datetime({}).nullish(),
                is_shared: zod.boolean().optional(),
                deleted: zod.boolean().optional(),
                creation_mode: zod
                    .enum(['default', 'template', 'duplicate', 'unlisted'])
                    .describe(
                        '* `default` - Default\n* `template` - Template\n* `duplicate` - Duplicate\n* `unlisted` - Unlisted (product-embedded)'
                    )
                    .optional(),
                tags: zod.array(zod.unknown()).optional(),
                restriction_level: zod
                    .union([zod.literal(21), zod.literal(37)])
                    .describe(
                        '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
                    )
                    .optional()
                    .describe(
                        'Controls who can edit the dashboard.\n\n* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
                    ),
                effective_restriction_level: zod.union([zod.literal(21), zod.literal(37)]).optional(),
                effective_privilege_level: zod.union([zod.literal(21), zod.literal(37)]).optional(),
                user_access_level: zod
                    .string()
                    .nullish()
                    .describe('The effective access level the user has for this object'),
                access_control_version: zod.string().optional(),
                last_refresh: zod.string().datetime({}).nullish(),
                team_id: zod.number().optional(),
            })
            .describe('Serializer mixin that handles tags for objects.')
    ),
})

export const DashboardsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsCreateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsCreateBodyNameMax = 400

export const dashboardsCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateBody = zod
    .object({
        name: zod.string().max(dashboardsCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsSharingListParams = zod.object({
    dashboard_id: zod.number(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsSharingListResponseItem = zod.object({
    created_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullish(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.string().optional(),
})
export const DashboardsSharingListResponse = zod.array(DashboardsSharingListResponseItem)

/**
 * Create a new password for the sharing configuration.
 */
export const DashboardsSharingPasswordsCreateParams = zod.object({
    dashboard_id: zod.number(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsSharingPasswordsCreateBody = zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const DashboardsSharingPasswordsCreateResponse = zod.object({
    created_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullish(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.string().optional(),
})

/**
 * Delete a password from the sharing configuration.
 */
export const DashboardsSharingPasswordsDestroyParams = zod.object({
    dashboard_id: zod.number(),
    password_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsSharingRefreshCreateParams = zod.object({
    dashboard_id: zod.number(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsSharingRefreshCreateBody = zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const DashboardsSharingRefreshCreateResponse = zod.object({
    created_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullish(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.string().optional(),
})

export const DashboardsRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsRetrieveQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsRetrieveResponseNameMax = 400

export const dashboardsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const dashboardsRetrieveResponseCreatedByOneFirstNameMax = 150

export const dashboardsRetrieveResponseCreatedByOneLastNameMax = 150

export const dashboardsRetrieveResponseCreatedByOneEmailMax = 254

export const dashboardsRetrieveResponseDeleteInsightsDefault = false

export const DashboardsRetrieveResponse = zod
    .object({
        id: zod.number().optional(),
        name: zod.string().max(dashboardsRetrieveResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(dashboardsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(dashboardsRetrieveResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(dashboardsRetrieveResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(dashboardsRetrieveResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .optional(),
        last_viewed_at: zod.string().datetime({}).nullish(),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        variables: zod.record(zod.string(), zod.unknown()).nullish(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        team_id: zod.number().optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsRetrieveResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsUpdateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsUpdateBodyNameMax = 400

export const dashboardsUpdateBodyDeleteInsightsDefault = false

export const DashboardsUpdateBody = zod
    .object({
        name: zod.string().max(dashboardsUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsUpdateResponseNameMax = 400

export const dashboardsUpdateResponseCreatedByOneDistinctIdMax = 200

export const dashboardsUpdateResponseCreatedByOneFirstNameMax = 150

export const dashboardsUpdateResponseCreatedByOneLastNameMax = 150

export const dashboardsUpdateResponseCreatedByOneEmailMax = 254

export const dashboardsUpdateResponseDeleteInsightsDefault = false

export const DashboardsUpdateResponse = zod
    .object({
        id: zod.number().optional(),
        name: zod.string().max(dashboardsUpdateResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(dashboardsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(dashboardsUpdateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(dashboardsUpdateResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(dashboardsUpdateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .optional(),
        last_viewed_at: zod.string().datetime({}).nullish(),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        variables: zod.record(zod.string(), zod.unknown()).nullish(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        team_id: zod.number().optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsUpdateResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsPartialUpdateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsPartialUpdateBodyNameMax = 400

export const dashboardsPartialUpdateBodyDeleteInsightsDefault = false

export const DashboardsPartialUpdateBody = zod
    .object({
        name: zod.string().max(dashboardsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsPartialUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsPartialUpdateResponseNameMax = 400

export const dashboardsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const dashboardsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const dashboardsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const dashboardsPartialUpdateResponseCreatedByOneEmailMax = 254

export const dashboardsPartialUpdateResponseDeleteInsightsDefault = false

export const DashboardsPartialUpdateResponse = zod
    .object({
        id: zod.number().optional(),
        name: zod.string().max(dashboardsPartialUpdateResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(dashboardsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(dashboardsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(dashboardsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(dashboardsPartialUpdateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .optional(),
        last_viewed_at: zod.string().datetime({}).nullish(),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        variables: zod.record(zod.string(), zod.unknown()).nullish(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        team_id: zod.number().optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsPartialUpdateResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const DashboardsDestroyParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsDestroyQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

/**
 * Generate AI analysis comparing before/after dashboard refresh.
Expects cache_key in request body pointing to the stored 'before' state.
 */
export const DashboardsAnalyzeRefreshResultCreateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsAnalyzeRefreshResultCreateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsAnalyzeRefreshResultCreateBodyNameMax = 400

export const dashboardsAnalyzeRefreshResultCreateBodyDeleteInsightsDefault = false

export const DashboardsAnalyzeRefreshResultCreateBody = zod
    .object({
        name: zod.string().max(dashboardsAnalyzeRefreshResultCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsAnalyzeRefreshResultCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsMoveTilePartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsMoveTilePartialUpdateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsMoveTilePartialUpdateBodyNameMax = 400

export const dashboardsMoveTilePartialUpdateBodyDeleteInsightsDefault = false

export const DashboardsMoveTilePartialUpdateBody = zod
    .object({
        name: zod.string().max(dashboardsMoveTilePartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsMoveTilePartialUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsReorderTilesCreateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsReorderTilesCreateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsReorderTilesCreateBody = zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
})

export const dashboardsReorderTilesCreateResponseNameMax = 400

export const dashboardsReorderTilesCreateResponseCreatedByOneDistinctIdMax = 200

export const dashboardsReorderTilesCreateResponseCreatedByOneFirstNameMax = 150

export const dashboardsReorderTilesCreateResponseCreatedByOneLastNameMax = 150

export const dashboardsReorderTilesCreateResponseCreatedByOneEmailMax = 254

export const dashboardsReorderTilesCreateResponseDeleteInsightsDefault = false

export const DashboardsReorderTilesCreateResponse = zod
    .object({
        id: zod.number().optional(),
        name: zod.string().max(dashboardsReorderTilesCreateResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.string().datetime({}).optional(),
        created_by: zod
            .object({
                id: zod.number().optional(),
                uuid: zod.string().optional(),
                distinct_id: zod.string().max(dashboardsReorderTilesCreateResponseCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(dashboardsReorderTilesCreateResponseCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(dashboardsReorderTilesCreateResponseCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(dashboardsReorderTilesCreateResponseCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            })
            .optional(),
        last_viewed_at: zod.string().datetime({}).nullish(),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        variables: zod.record(zod.string(), zod.unknown()).nullish(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        team_id: zod.number().optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullish(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsReorderTilesCreateResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Snapshot the current dashboard state (from cache) for AI analysis.
Returns a cache_key representing the 'before' state, to be used with analyze_refresh_result.
 */
export const DashboardsSnapshotCreateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsSnapshotCreateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsSnapshotCreateBodyNameMax = 400

export const dashboardsSnapshotCreateBodyDeleteInsightsDefault = false

export const DashboardsSnapshotCreateBody = zod
    .object({
        name: zod.string().max(dashboardsSnapshotCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsSnapshotCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered.
 */
export const DashboardsStreamTilesRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this dashboard.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsStreamTilesRetrieveQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const DashboardsCreateFromTemplateJsonCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsCreateFromTemplateJsonCreateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsCreateFromTemplateJsonCreateBodyNameMax = 400

export const dashboardsCreateFromTemplateJsonCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateFromTemplateJsonCreateBody = zod
    .object({
        name: zod.string().max(dashboardsCreateFromTemplateJsonCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateFromTemplateJsonCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Creates an unlisted dashboard from template by tag.
Enforces uniqueness (one per tag per team).
Returns 409 if unlisted dashboard with this tag already exists.
 */
export const DashboardsCreateUnlistedDashboardCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DashboardsCreateUnlistedDashboardCreateQueryParams = zod.object({
    format: zod.enum(['json', 'txt']).optional(),
})

export const dashboardsCreateUnlistedDashboardCreateBodyNameMax = 400

export const dashboardsCreateUnlistedDashboardCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateUnlistedDashboardCreateBody = zod
    .object({
        name: zod.string().max(dashboardsCreateUnlistedDashboardCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateUnlistedDashboardCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DataColorThemesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataColorThemesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const dataColorThemesListResponseResultsItemNameMax = 100

export const dataColorThemesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const dataColorThemesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const dataColorThemesListResponseResultsItemCreatedByOneLastNameMax = 150

export const dataColorThemesListResponseResultsItemCreatedByOneEmailMax = 254

export const DataColorThemesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number().optional(),
            name: zod.string().max(dataColorThemesListResponseResultsItemNameMax),
            colors: zod.unknown().optional(),
            is_global: zod.string().optional(),
            created_at: zod.string().datetime({}).nullish(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(dataColorThemesListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(dataColorThemesListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(dataColorThemesListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.string().email().max(dataColorThemesListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
                .optional(),
        })
    ),
})

export const DataColorThemesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dataColorThemesCreateBodyNameMax = 100

export const DataColorThemesCreateBody = zod.object({
    name: zod.string().max(dataColorThemesCreateBodyNameMax),
    colors: zod.unknown().optional(),
})

export const DataColorThemesRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this data color theme.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dataColorThemesRetrieveResponseNameMax = 100

export const dataColorThemesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const dataColorThemesRetrieveResponseCreatedByOneFirstNameMax = 150

export const dataColorThemesRetrieveResponseCreatedByOneLastNameMax = 150

export const dataColorThemesRetrieveResponseCreatedByOneEmailMax = 254

export const DataColorThemesRetrieveResponse = zod.object({
    id: zod.number().optional(),
    name: zod.string().max(dataColorThemesRetrieveResponseNameMax),
    colors: zod.unknown().optional(),
    is_global: zod.string().optional(),
    created_at: zod.string().datetime({}).nullish(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(dataColorThemesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dataColorThemesRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dataColorThemesRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(dataColorThemesRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .optional(),
})

export const DataColorThemesUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this data color theme.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dataColorThemesUpdateBodyNameMax = 100

export const DataColorThemesUpdateBody = zod.object({
    name: zod.string().max(dataColorThemesUpdateBodyNameMax),
    colors: zod.unknown().optional(),
})

export const dataColorThemesUpdateResponseNameMax = 100

export const dataColorThemesUpdateResponseCreatedByOneDistinctIdMax = 200

export const dataColorThemesUpdateResponseCreatedByOneFirstNameMax = 150

export const dataColorThemesUpdateResponseCreatedByOneLastNameMax = 150

export const dataColorThemesUpdateResponseCreatedByOneEmailMax = 254

export const DataColorThemesUpdateResponse = zod.object({
    id: zod.number().optional(),
    name: zod.string().max(dataColorThemesUpdateResponseNameMax),
    colors: zod.unknown().optional(),
    is_global: zod.string().optional(),
    created_at: zod.string().datetime({}).nullish(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(dataColorThemesUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dataColorThemesUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dataColorThemesUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(dataColorThemesUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .optional(),
})

export const DataColorThemesPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this data color theme.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const dataColorThemesPartialUpdateBodyNameMax = 100

export const DataColorThemesPartialUpdateBody = zod.object({
    name: zod.string().max(dataColorThemesPartialUpdateBodyNameMax).optional(),
    colors: zod.unknown().optional(),
})

export const dataColorThemesPartialUpdateResponseNameMax = 100

export const dataColorThemesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const dataColorThemesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const dataColorThemesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const dataColorThemesPartialUpdateResponseCreatedByOneEmailMax = 254

export const DataColorThemesPartialUpdateResponse = zod.object({
    id: zod.number().optional(),
    name: zod.string().max(dataColorThemesPartialUpdateResponseNameMax),
    colors: zod.unknown().optional(),
    is_global: zod.string().optional(),
    created_at: zod.string().datetime({}).nullish(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(dataColorThemesPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dataColorThemesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dataColorThemesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(dataColorThemesPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .optional(),
})

export const DataColorThemesDestroyParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this data color theme.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
