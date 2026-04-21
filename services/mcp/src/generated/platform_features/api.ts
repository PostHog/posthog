/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 17 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ApprovalPoliciesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ApprovalPoliciesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ApprovalPoliciesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this approval policy.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ChangeRequestsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ChangeRequestsListQueryParams = /* @__PURE__ */ zod.object({
    action_key: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    requester: zod.number().optional(),
    resource_id: zod.string().optional(),
    resource_type: zod.string().optional(),
    state: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
})

export const ChangeRequestsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this change request.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const RetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this organization.'),
})

export const MembersListParams = /* @__PURE__ */ zod.object({
    organization_id: zod.string(),
})

export const MembersListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order: zod.string().optional().describe('Sort order. Defaults to `-joined_at`.'),
})

export const RolesListParams = /* @__PURE__ */ zod.object({
    organization_id: zod.string(),
})

export const RolesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const RolesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this role.'),
    organization_id: zod.string(),
})

export const RolesRoleMembershipsListParams = /* @__PURE__ */ zod.object({
    organization_id: zod.string(),
    role_id: zod.string(),
})

export const RolesRoleMembershipsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ActivityLogListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const activityLogListQueryPageSizeDefault = 100
export const activityLogListQueryPageSizeMax = 1000

export const ActivityLogListQueryParams = /* @__PURE__ */ zod.object({
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
            'ProjectSecretAPIKey',
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
            'Filter by a single activity scope, e.g. "FeatureFlag", "Insight", "Dashboard", "Experiment".\n\n* `Cohort` - Cohort\n* `FeatureFlag` - FeatureFlag\n* `Person` - Person\n* `Group` - Group\n* `Insight` - Insight\n* `Plugin` - Plugin\n* `PluginConfig` - PluginConfig\n* `HogFunction` - HogFunction\n* `HogFlow` - HogFlow\n* `DataManagement` - DataManagement\n* `EventDefinition` - EventDefinition\n* `PropertyDefinition` - PropertyDefinition\n* `Notebook` - Notebook\n* `Endpoint` - Endpoint\n* `EndpointVersion` - EndpointVersion\n* `Dashboard` - Dashboard\n* `Replay` - Replay\n* `Experiment` - Experiment\n* `ExperimentHoldout` - ExperimentHoldout\n* `ExperimentSavedMetric` - ExperimentSavedMetric\n* `Survey` - Survey\n* `EarlyAccessFeature` - EarlyAccessFeature\n* `SessionRecordingPlaylist` - SessionRecordingPlaylist\n* `Comment` - Comment\n* `Team` - Team\n* `Project` - Project\n* `ErrorTrackingIssue` - ErrorTrackingIssue\n* `DataWarehouseSavedQuery` - DataWarehouseSavedQuery\n* `Organization` - Organization\n* `OrganizationDomain` - OrganizationDomain\n* `OrganizationMembership` - OrganizationMembership\n* `Role` - Role\n* `UserGroup` - UserGroup\n* `BatchExport` - BatchExport\n* `BatchImport` - BatchImport\n* `Integration` - Integration\n* `Annotation` - Annotation\n* `Tag` - Tag\n* `TaggedItem` - TaggedItem\n* `Subscription` - Subscription\n* `PersonalAPIKey` - PersonalAPIKey\n* `ProjectSecretAPIKey` - ProjectSecretAPIKey\n* `User` - User\n* `Action` - Action\n* `AlertConfiguration` - AlertConfiguration\n* `Threshold` - Threshold\n* `AlertSubscription` - AlertSubscription\n* `ExternalDataSource` - ExternalDataSource\n* `ExternalDataSchema` - ExternalDataSchema\n* `LLMTrace` - LLMTrace\n* `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset\n* `CustomerProfileConfig` - CustomerProfileConfig\n* `Log` - Log\n* `LogsAlertConfiguration` - LogsAlertConfiguration\n* `ProductTour` - ProductTour\n* `Ticket` - Ticket'
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
                    'ProjectSecretAPIKey',
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
                    '* `Cohort` - Cohort\n* `FeatureFlag` - FeatureFlag\n* `Person` - Person\n* `Group` - Group\n* `Insight` - Insight\n* `Plugin` - Plugin\n* `PluginConfig` - PluginConfig\n* `HogFunction` - HogFunction\n* `HogFlow` - HogFlow\n* `DataManagement` - DataManagement\n* `EventDefinition` - EventDefinition\n* `PropertyDefinition` - PropertyDefinition\n* `Notebook` - Notebook\n* `Endpoint` - Endpoint\n* `EndpointVersion` - EndpointVersion\n* `Dashboard` - Dashboard\n* `Replay` - Replay\n* `Experiment` - Experiment\n* `ExperimentHoldout` - ExperimentHoldout\n* `ExperimentSavedMetric` - ExperimentSavedMetric\n* `Survey` - Survey\n* `EarlyAccessFeature` - EarlyAccessFeature\n* `SessionRecordingPlaylist` - SessionRecordingPlaylist\n* `Comment` - Comment\n* `Team` - Team\n* `Project` - Project\n* `ErrorTrackingIssue` - ErrorTrackingIssue\n* `DataWarehouseSavedQuery` - DataWarehouseSavedQuery\n* `Organization` - Organization\n* `OrganizationDomain` - OrganizationDomain\n* `OrganizationMembership` - OrganizationMembership\n* `Role` - Role\n* `UserGroup` - UserGroup\n* `BatchExport` - BatchExport\n* `BatchImport` - BatchImport\n* `Integration` - Integration\n* `Annotation` - Annotation\n* `Tag` - Tag\n* `TaggedItem` - TaggedItem\n* `Subscription` - Subscription\n* `PersonalAPIKey` - PersonalAPIKey\n* `ProjectSecretAPIKey` - ProjectSecretAPIKey\n* `User` - User\n* `Action` - Action\n* `AlertConfiguration` - AlertConfiguration\n* `Threshold` - Threshold\n* `AlertSubscription` - AlertSubscription\n* `ExternalDataSource` - ExternalDataSource\n* `ExternalDataSchema` - ExternalDataSchema\n* `LLMTrace` - LLMTrace\n* `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset\n* `CustomerProfileConfig` - CustomerProfileConfig\n* `Log` - Log\n* `LogsAlertConfiguration` - LogsAlertConfiguration\n* `ProductTour` - ProductTour\n* `Ticket` - Ticket'
                )
        )
        .optional()
        .describe(
            'Filter by multiple activity scopes, comma-separated. Values must be valid ActivityScope enum values. E.g. "FeatureFlag,Insight".'
        ),
    user: zod.string().optional().describe('Filter by user UUID who performed the action.'),
})

export const AdvancedActivityLogsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const advancedActivityLogsListQueryActivitiesDefault = []
export const advancedActivityLogsListQueryClientsDefault = []
export const advancedActivityLogsListQueryItemIdsDefault = []
export const advancedActivityLogsListQueryPageSizeDefault = 100
export const advancedActivityLogsListQueryPageSizeMax = 1000

export const advancedActivityLogsListQueryScopesDefault = []
export const advancedActivityLogsListQueryUsersDefault = []

export const AdvancedActivityLogsListQueryParams = /* @__PURE__ */ zod.object({
    activities: zod.array(zod.string()).default(advancedActivityLogsListQueryActivitiesDefault),
    clients: zod.array(zod.string()).default(advancedActivityLogsListQueryClientsDefault),
    detail_filters: zod.string().optional(),
    end_date: zod.iso.datetime({}).optional(),
    hogql_filter: zod.string().optional(),
    is_system: zod.boolean().nullish(),
    item_ids: zod.array(zod.string()).default(advancedActivityLogsListQueryItemIdsDefault),
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
        .max(advancedActivityLogsListQueryPageSizeMax)
        .default(advancedActivityLogsListQueryPageSizeDefault)
        .describe('Number of results per page (default: 100, max: 1000). Only used with page-based pagination.'),
    scopes: zod.array(zod.string()).default(advancedActivityLogsListQueryScopesDefault),
    search_text: zod.string().optional(),
    start_date: zod.iso.datetime({}).optional(),
    users: zod.array(zod.string()).default(advancedActivityLogsListQueryUsersDefault),
    was_impersonated: zod.boolean().nullish(),
})

export const AdvancedActivityLogsAvailableFiltersRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CommentsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CommentsListQueryParams = /* @__PURE__ */ zod.object({
    cursor: zod.string().optional().describe('The pagination cursor value.'),
    item_id: zod.string().min(1).optional().describe('Filter by the ID of the resource being commented on.'),
    scope: zod
        .string()
        .min(1)
        .optional()
        .describe('Filter by resource type (e.g. Dashboard, FeatureFlag, Insight, Replay).'),
    search: zod.string().min(1).optional().describe('Full-text search within comment content.'),
    source_comment: zod.string().min(1).optional().describe('Filter replies to a specific parent comment.'),
})

export const CommentsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this comment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CommentsThreadRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this comment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CommentsCountRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
