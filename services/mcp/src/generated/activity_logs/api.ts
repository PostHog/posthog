/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ActivityLogListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const activityLogListQueryPageSizeDefault = 100
export const activityLogListQueryPageSizeMax = 1000

export const ActivityLogListQueryParams = zod.object({
    item_id: zod.string().min(1).optional().describe('Filter by the ID of the affected resource.'),
    page: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Page number for pagination. When provided, uses page-based pagination ordered by most recent first.'
        ),
    page_size: zod
        .number()
        .min(1)
        .max(activityLogListQueryPageSizeMax)
        .default(activityLogListQueryPageSizeDefault)
        .describe('Number of results per page (default: 100, max: 1000). Only used with page-based pagination.'),
    scope: zod
        .enum([
            'Cohort',
            'FeatureFlag',
            'Person',
            'Group',
            'Insight',
            'Plugin',
            'PluginConfig',
            'HogFunction',
            'HogFlow',
            'DataManagement',
            'EventDefinition',
            'PropertyDefinition',
            'Notebook',
            'Endpoint',
            'EndpointVersion',
            'Dashboard',
            'Replay',
            'Experiment',
            'ExperimentHoldout',
            'ExperimentSavedMetric',
            'Survey',
            'EarlyAccessFeature',
            'SessionRecordingPlaylist',
            'Comment',
            'Team',
            'Project',
            'ErrorTrackingIssue',
            'DataWarehouseSavedQuery',
            'Organization',
            'OrganizationDomain',
            'OrganizationMembership',
            'Role',
            'UserGroup',
            'BatchExport',
            'BatchImport',
            'Integration',
            'Annotation',
            'Tag',
            'TaggedItem',
            'Subscription',
            'PersonalAPIKey',
            'User',
            'Action',
            'AlertConfiguration',
            'Threshold',
            'AlertSubscription',
            'ExternalDataSource',
            'ExternalDataSchema',
            'LLMTrace',
            'WebAnalyticsFilterPreset',
            'CustomerProfileConfig',
            'Log',
            'LogsAlertConfiguration',
            'ProductTour',
            'Ticket',
        ])
        .optional()
        .describe(
            'Filter by a single activity scope, e.g. "FeatureFlag", "Insight", "Dashboard", "Experiment".\n\n* `Cohort` - Cohort\n* `FeatureFlag` - FeatureFlag\n* `Person` - Person\n* `Group` - Group\n* `Insight` - Insight\n* `Plugin` - Plugin\n* `PluginConfig` - PluginConfig\n* `HogFunction` - HogFunction\n* `HogFlow` - HogFlow\n* `DataManagement` - DataManagement\n* `EventDefinition` - EventDefinition\n* `PropertyDefinition` - PropertyDefinition\n* `Notebook` - Notebook\n* `Endpoint` - Endpoint\n* `EndpointVersion` - EndpointVersion\n* `Dashboard` - Dashboard\n* `Replay` - Replay\n* `Experiment` - Experiment\n* `ExperimentHoldout` - ExperimentHoldout\n* `ExperimentSavedMetric` - ExperimentSavedMetric\n* `Survey` - Survey\n* `EarlyAccessFeature` - EarlyAccessFeature\n* `SessionRecordingPlaylist` - SessionRecordingPlaylist\n* `Comment` - Comment\n* `Team` - Team\n* `Project` - Project\n* `ErrorTrackingIssue` - ErrorTrackingIssue\n* `DataWarehouseSavedQuery` - DataWarehouseSavedQuery\n* `Organization` - Organization\n* `OrganizationDomain` - OrganizationDomain\n* `OrganizationMembership` - OrganizationMembership\n* `Role` - Role\n* `UserGroup` - UserGroup\n* `BatchExport` - BatchExport\n* `BatchImport` - BatchImport\n* `Integration` - Integration\n* `Annotation` - Annotation\n* `Tag` - Tag\n* `TaggedItem` - TaggedItem\n* `Subscription` - Subscription\n* `PersonalAPIKey` - PersonalAPIKey\n* `User` - User\n* `Action` - Action\n* `AlertConfiguration` - AlertConfiguration\n* `Threshold` - Threshold\n* `AlertSubscription` - AlertSubscription\n* `ExternalDataSource` - ExternalDataSource\n* `ExternalDataSchema` - ExternalDataSchema\n* `LLMTrace` - LLMTrace\n* `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset\n* `CustomerProfileConfig` - CustomerProfileConfig\n* `Log` - Log\n* `LogsAlertConfiguration` - LogsAlertConfiguration\n* `ProductTour` - ProductTour\n* `Ticket` - Ticket'
        ),
    scopes: zod
        .array(
            zod
                .enum([
                    'Cohort',
                    'FeatureFlag',
                    'Person',
                    'Group',
                    'Insight',
                    'Plugin',
                    'PluginConfig',
                    'HogFunction',
                    'HogFlow',
                    'DataManagement',
                    'EventDefinition',
                    'PropertyDefinition',
                    'Notebook',
                    'Endpoint',
                    'EndpointVersion',
                    'Dashboard',
                    'Replay',
                    'Experiment',
                    'ExperimentHoldout',
                    'ExperimentSavedMetric',
                    'Survey',
                    'EarlyAccessFeature',
                    'SessionRecordingPlaylist',
                    'Comment',
                    'Team',
                    'Project',
                    'ErrorTrackingIssue',
                    'DataWarehouseSavedQuery',
                    'Organization',
                    'OrganizationDomain',
                    'OrganizationMembership',
                    'Role',
                    'UserGroup',
                    'BatchExport',
                    'BatchImport',
                    'Integration',
                    'Annotation',
                    'Tag',
                    'TaggedItem',
                    'Subscription',
                    'PersonalAPIKey',
                    'User',
                    'Action',
                    'AlertConfiguration',
                    'Threshold',
                    'AlertSubscription',
                    'ExternalDataSource',
                    'ExternalDataSchema',
                    'LLMTrace',
                    'WebAnalyticsFilterPreset',
                    'CustomerProfileConfig',
                    'Log',
                    'LogsAlertConfiguration',
                    'ProductTour',
                    'Ticket',
                ])
                .describe(
                    '* `Cohort` - Cohort\n* `FeatureFlag` - FeatureFlag\n* `Person` - Person\n* `Group` - Group\n* `Insight` - Insight\n* `Plugin` - Plugin\n* `PluginConfig` - PluginConfig\n* `HogFunction` - HogFunction\n* `HogFlow` - HogFlow\n* `DataManagement` - DataManagement\n* `EventDefinition` - EventDefinition\n* `PropertyDefinition` - PropertyDefinition\n* `Notebook` - Notebook\n* `Endpoint` - Endpoint\n* `EndpointVersion` - EndpointVersion\n* `Dashboard` - Dashboard\n* `Replay` - Replay\n* `Experiment` - Experiment\n* `ExperimentHoldout` - ExperimentHoldout\n* `ExperimentSavedMetric` - ExperimentSavedMetric\n* `Survey` - Survey\n* `EarlyAccessFeature` - EarlyAccessFeature\n* `SessionRecordingPlaylist` - SessionRecordingPlaylist\n* `Comment` - Comment\n* `Team` - Team\n* `Project` - Project\n* `ErrorTrackingIssue` - ErrorTrackingIssue\n* `DataWarehouseSavedQuery` - DataWarehouseSavedQuery\n* `Organization` - Organization\n* `OrganizationDomain` - OrganizationDomain\n* `OrganizationMembership` - OrganizationMembership\n* `Role` - Role\n* `UserGroup` - UserGroup\n* `BatchExport` - BatchExport\n* `BatchImport` - BatchImport\n* `Integration` - Integration\n* `Annotation` - Annotation\n* `Tag` - Tag\n* `TaggedItem` - TaggedItem\n* `Subscription` - Subscription\n* `PersonalAPIKey` - PersonalAPIKey\n* `User` - User\n* `Action` - Action\n* `AlertConfiguration` - AlertConfiguration\n* `Threshold` - Threshold\n* `AlertSubscription` - AlertSubscription\n* `ExternalDataSource` - ExternalDataSource\n* `ExternalDataSchema` - ExternalDataSchema\n* `LLMTrace` - LLMTrace\n* `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset\n* `CustomerProfileConfig` - CustomerProfileConfig\n* `Log` - Log\n* `LogsAlertConfiguration` - LogsAlertConfiguration\n* `ProductTour` - ProductTour\n* `Ticket` - Ticket'
                )
        )
        .optional()
        .describe(
            'Filter by multiple activity scopes, comma-separated. Values must be valid ActivityScope enum values. E.g. "FeatureFlag,Insight".'
        ),
    user: zod.string().optional().describe('Filter by user UUID who performed the action.'),
})

export const activityLogListResponseUserDistinctIdMax = 200

export const activityLogListResponseUserFirstNameMax = 150

export const activityLogListResponseUserLastNameMax = 150

export const activityLogListResponseUserEmailMax = 254

export const activityLogListResponseActivityMax = 79

export const activityLogListResponseItemIdMax = 72

export const activityLogListResponseScopeMax = 79

export const ActivityLogListResponseItem = zod.object({
    id: zod.string(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(activityLogListResponseUserDistinctIdMax).nullish(),
        first_name: zod.string().max(activityLogListResponseUserFirstNameMax).optional(),
        last_name: zod.string().max(activityLogListResponseUserLastNameMax).optional(),
        email: zod.string().email().max(activityLogListResponseUserEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    unread: zod.boolean().describe("is the date of this log item newer than the user's bookmark"),
    organization_id: zod.string().nullish(),
    was_impersonated: zod.boolean().nullish(),
    is_system: zod.boolean().nullish(),
    activity: zod.string().max(activityLogListResponseActivityMax),
    item_id: zod.string().max(activityLogListResponseItemIdMax).nullish(),
    scope: zod.string().max(activityLogListResponseScopeMax),
    detail: zod.unknown().nullish(),
    created_at: zod.string().datetime({}).optional(),
})
export const ActivityLogListResponse = zod.array(ActivityLogListResponseItem)
