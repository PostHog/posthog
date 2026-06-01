/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 19 enabled ops
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
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

export const MembersListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order: zod.string().optional().describe('Sort order. Defaults to `-joined_at`.'),
    search: zod
        .string()
        .optional()
        .describe(
            'Fuzzy match against member `first_name`, `last_name`, and `email` using Postgres trigram word similarity. Supports typos and prefix-as-you-type. Capped at 200 characters.'
        ),
})

export const RolesListParams = /* @__PURE__ */ zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

export const RolesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const RolesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this role.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

export const RolesRoleMembershipsListParams = /* @__PURE__ */ zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
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
            'LegalDocument',
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
            'LogsExclusionRule',
            'ProductTour',
            'Ticket',
        ])
        .optional()
        .describe(
            'Filter by a single activity scope, e.g. "FeatureFlag", "Insight", "Dashboard", "Experiment".\n\n* `Cohort` - Cohort\n* `FeatureFlag` - FeatureFlag\n* `Person` - Person\n* `Group` - Group\n* `Insight` - Insight\n* `Plugin` - Plugin\n* `PluginConfig` - PluginConfig\n* `HogFunction` - HogFunction\n* `HogFlow` - HogFlow\n* `DataManagement` - DataManagement\n* `EventDefinition` - EventDefinition\n* `PropertyDefinition` - PropertyDefinition\n* `Notebook` - Notebook\n* `Endpoint` - Endpoint\n* `EndpointVersion` - EndpointVersion\n* `Dashboard` - Dashboard\n* `Replay` - Replay\n* `Experiment` - Experiment\n* `ExperimentHoldout` - ExperimentHoldout\n* `ExperimentSavedMetric` - ExperimentSavedMetric\n* `Survey` - Survey\n* `EarlyAccessFeature` - EarlyAccessFeature\n* `SessionRecordingPlaylist` - SessionRecordingPlaylist\n* `Comment` - Comment\n* `Team` - Team\n* `Project` - Project\n* `ErrorTrackingIssue` - ErrorTrackingIssue\n* `DataWarehouseSavedQuery` - DataWarehouseSavedQuery\n* `LegalDocument` - LegalDocument\n* `Organization` - Organization\n* `OrganizationDomain` - OrganizationDomain\n* `OrganizationMembership` - OrganizationMembership\n* `Role` - Role\n* `UserGroup` - UserGroup\n* `BatchExport` - BatchExport\n* `BatchImport` - BatchImport\n* `Integration` - Integration\n* `Annotation` - Annotation\n* `Tag` - Tag\n* `TaggedItem` - TaggedItem\n* `Subscription` - Subscription\n* `PersonalAPIKey` - PersonalAPIKey\n* `ProjectSecretAPIKey` - ProjectSecretAPIKey\n* `User` - User\n* `Action` - Action\n* `AlertConfiguration` - AlertConfiguration\n* `Threshold` - Threshold\n* `AlertSubscription` - AlertSubscription\n* `ExternalDataSource` - ExternalDataSource\n* `ExternalDataSchema` - ExternalDataSchema\n* `LLMTrace` - LLMTrace\n* `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset\n* `CustomerProfileConfig` - CustomerProfileConfig\n* `Log` - Log\n* `LogsAlertConfiguration` - LogsAlertConfiguration\n* `LogsExclusionRule` - LogsExclusionRule\n* `ProductTour` - ProductTour\n* `Ticket` - Ticket'
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
                    'LegalDocument',
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
                    'LogsExclusionRule',
                    'ProductTour',
                    'Ticket',
                ])
                .describe(
                    '* `Cohort` - Cohort\n* `FeatureFlag` - FeatureFlag\n* `Person` - Person\n* `Group` - Group\n* `Insight` - Insight\n* `Plugin` - Plugin\n* `PluginConfig` - PluginConfig\n* `HogFunction` - HogFunction\n* `HogFlow` - HogFlow\n* `DataManagement` - DataManagement\n* `EventDefinition` - EventDefinition\n* `PropertyDefinition` - PropertyDefinition\n* `Notebook` - Notebook\n* `Endpoint` - Endpoint\n* `EndpointVersion` - EndpointVersion\n* `Dashboard` - Dashboard\n* `Replay` - Replay\n* `Experiment` - Experiment\n* `ExperimentHoldout` - ExperimentHoldout\n* `ExperimentSavedMetric` - ExperimentSavedMetric\n* `Survey` - Survey\n* `EarlyAccessFeature` - EarlyAccessFeature\n* `SessionRecordingPlaylist` - SessionRecordingPlaylist\n* `Comment` - Comment\n* `Team` - Team\n* `Project` - Project\n* `ErrorTrackingIssue` - ErrorTrackingIssue\n* `DataWarehouseSavedQuery` - DataWarehouseSavedQuery\n* `LegalDocument` - LegalDocument\n* `Organization` - Organization\n* `OrganizationDomain` - OrganizationDomain\n* `OrganizationMembership` - OrganizationMembership\n* `Role` - Role\n* `UserGroup` - UserGroup\n* `BatchExport` - BatchExport\n* `BatchImport` - BatchImport\n* `Integration` - Integration\n* `Annotation` - Annotation\n* `Tag` - Tag\n* `TaggedItem` - TaggedItem\n* `Subscription` - Subscription\n* `PersonalAPIKey` - PersonalAPIKey\n* `ProjectSecretAPIKey` - ProjectSecretAPIKey\n* `User` - User\n* `Action` - Action\n* `AlertConfiguration` - AlertConfiguration\n* `Threshold` - Threshold\n* `AlertSubscription` - AlertSubscription\n* `ExternalDataSource` - ExternalDataSource\n* `ExternalDataSchema` - ExternalDataSchema\n* `LLMTrace` - LLMTrace\n* `WebAnalyticsFilterPreset` - WebAnalyticsFilterPreset\n* `CustomerProfileConfig` - CustomerProfileConfig\n* `Log` - Log\n* `LogsAlertConfiguration` - LogsAlertConfiguration\n* `LogsExclusionRule` - LogsExclusionRule\n* `ProductTour` - ProductTour\n* `Ticket` - Ticket'
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
    completed: zod
        .enum(['any', 'open', 'completed'])
        .optional()
        .describe(
            "When kind=task, restrict to open (incomplete) or completed tasks. Ignored when kind is not 'task'. Defaults to 'any' (no filter).\n\n* `any` - any\n* `open` - open\n* `completed` - completed"
        ),
    cursor: zod.string().optional().describe('The pagination cursor value.'),
    item_id: zod.string().min(1).optional().describe('Filter by the ID of the resource being commented on.'),
    kind: zod
        .enum(['any', 'comment', 'task'])
        .optional()
        .describe(
            "Filter by comment kind. 'task' returns only items intentionally created as actionable. 'comment' excludes tasks. Defaults to 'any' (no filter).\n\n* `any` - any\n* `comment` - comment\n* `task` - task"
        ),
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

/**
 * Get the authenticated user's pinned sidebar tabs and configured homepage for the current team. Pass `@me` as the UUID.
 */
export const UserHomeSettingsRetrieveParams = /* @__PURE__ */ zod.object({
    uuid: zod.string(),
})

/**
 * Update the authenticated user's pinned sidebar tabs and/or homepage for the current team. Pass `@me` as the UUID. Send `tabs` to replace the pinned tab list, `homepage` to set the home destination (any PostHog URL — dashboard, insight, search results, scene). Either field may be omitted to leave it unchanged; sending `homepage: null` or `{}` clears the homepage.
 */
export const UserHomeSettingsPartialUpdateParams = /* @__PURE__ */ zod.object({
    uuid: zod.string(),
})

export const UserHomeSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    tabs: zod
        .array(
            zod.object({
                id: zod
                    .string()
                    .optional()
                    .describe('Stable identifier for the tab. Generated client-side; safe to omit on create.'),
                pathname: zod
                    .string()
                    .optional()
                    .describe(
                        'URL pathname the tab points at — for example `/project/123/dashboard/45` or `/project/123/insights`. Combined with `search` and `hash` to reconstruct the destination.'
                    ),
                search: zod
                    .string()
                    .optional()
                    .describe(
                        'Query string portion of the URL, including the leading `?`. Empty string when there is no query.'
                    ),
                hash: zod
                    .string()
                    .optional()
                    .describe(
                        'Fragment portion of the URL, including the leading `#`. Empty string when there is no fragment.'
                    ),
                title: zod
                    .string()
                    .optional()
                    .describe(
                        'Default tab title derived from the destination scene. Used when `customTitle` is not set.'
                    ),
                customTitle: zod
                    .string()
                    .nullish()
                    .describe('Optional user-provided title that overrides `title` in the navigation UI.'),
                iconType: zod
                    .string()
                    .optional()
                    .describe(
                        'Icon key shown next to the tab in the sidebar — for example `dashboard`, `insight`, `blank`.'
                    ),
                sceneId: zod
                    .string()
                    .nullish()
                    .describe(
                        'Scene identifier resolved from the pathname when known — used by the frontend for icon/title hints.'
                    ),
                sceneKey: zod
                    .string()
                    .nullish()
                    .describe(
                        'Scene key (logic key) for the destination, paired with `sceneParams` for deeper routing context.'
                    ),
                sceneParams: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Free-form scene parameters captured at pin time, used by the frontend to rehydrate the destination.'
                    ),
                pinned: zod
                    .boolean()
                    .optional()
                    .describe('Whether this entry is pinned. Always coerced to true on save — pass true or omit.'),
            })
        )
        .optional()
        .describe(
            'Ordered list of pinned navigation tabs shown in the sidebar for the authenticated user within the current team. Send the full list to replace the existing pins; omit to leave them unchanged.'
        ),
    homepage: zod
        .object({
            id: zod
                .string()
                .optional()
                .describe('Stable identifier for the tab. Generated client-side; safe to omit on create.'),
            pathname: zod
                .string()
                .optional()
                .describe(
                    'URL pathname the tab points at — for example `/project/123/dashboard/45` or `/project/123/insights`. Combined with `search` and `hash` to reconstruct the destination.'
                ),
            search: zod
                .string()
                .optional()
                .describe(
                    'Query string portion of the URL, including the leading `?`. Empty string when there is no query.'
                ),
            hash: zod
                .string()
                .optional()
                .describe(
                    'Fragment portion of the URL, including the leading `#`. Empty string when there is no fragment.'
                ),
            title: zod
                .string()
                .optional()
                .describe('Default tab title derived from the destination scene. Used when `customTitle` is not set.'),
            customTitle: zod
                .string()
                .nullish()
                .describe('Optional user-provided title that overrides `title` in the navigation UI.'),
            iconType: zod
                .string()
                .optional()
                .describe(
                    'Icon key shown next to the tab in the sidebar — for example `dashboard`, `insight`, `blank`.'
                ),
            sceneId: zod
                .string()
                .nullish()
                .describe(
                    'Scene identifier resolved from the pathname when known — used by the frontend for icon/title hints.'
                ),
            sceneKey: zod
                .string()
                .nullish()
                .describe(
                    'Scene key (logic key) for the destination, paired with `sceneParams` for deeper routing context.'
                ),
            sceneParams: zod
                .unknown()
                .optional()
                .describe(
                    'Free-form scene parameters captured at pin time, used by the frontend to rehydrate the destination.'
                ),
            pinned: zod
                .boolean()
                .optional()
                .describe('Whether this entry is pinned. Always coerced to true on save — pass true or omit.'),
        })
        .nullish()
        .describe(
            "Tab descriptor for the user's chosen home page — the destination opened when they click the PostHog logo or hit `/`. Set to a tab descriptor to pick a homepage, send `null` or `{}` to clear it and fall back to the project default."
        ),
})
