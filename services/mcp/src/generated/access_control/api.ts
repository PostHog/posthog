/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Object rules that apply to everyone in the project without a rule of their own on that object.
 */
export const organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultObjectsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlDefaultObjectsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Property rules that apply to everyone in the project without a rule of their own on that property.
 */
export const organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultPropertiesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlDefaultPropertiesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Set or clear the rule everyone in the project gets for a scope, unless a member or role rule of their own applies. The scope is the project (`resource: project`), a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const organizationsProjectsAccessControlDefaultRulesUpdatePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultRulesUpdatePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultRulesUpdateParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultRulesUpdatePathIdMin)
        .max(organizationsProjectsAccessControlDefaultRulesUpdatePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlDefaultRulesUpdateBody = () => zod
    .object({
        resource: zod
            .enum([
                'account',
                'action',
                'activity_log',
                'ai_observability_clusters',
                'customer_analytics',
                'customer_journey',
                'customer_task',
                'dashboard',
                'dashboard_template',
                'data_catalog',
                'dataset',
                'early_access_feature',
                'endpoint',
                'error_tracking',
                'evaluation',
                'experiment',
                'experiment_holdout',
                'experiment_saved_metric',
                'export',
                'external_data_source',
                'feature_flag',
                'heatmap',
                'hog_flow',
                'insight',
                'llm_analytics',
                'llm_playground',
                'llm_prompt',
                'llm_provider_key',
                'llm_skill',
                'logs',
                'marketing_analytics',
                'mcp_analytics',
                'metrics',
                'notebook',
                'project',
                'property_definition',
                'replay_scanner',
                'revenue_analytics',
                'session_recording',
                'session_recording_playlist',
                'sharing_configuration',
                'stamphog',
                'survey',
                'tagger',
                'ticket',
                'toolbar',
                'tracing',
                'vision_alert',
                'warehouse_objects',
                'warehouse_table',
                'warehouse_view',
                'web_analytics',
            ])
            .describe(
                '\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            )
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.\n\n\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
    })
    .describe('A rule for everyone in the project without a member or role rule of their own.')

/**
 * The project's default access. Returns the level that applies to the project and to each resource type when a member or a role has no rule of their own. Also lists the resource types that accept rules on single objects, with the levels such a rule can set.
 */
export const organizationsProjectsAccessControlDefaultsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlDefaultsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlDefaultsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlDefaultsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlDefaultsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Object rules configured for a member: the single objects, for example a dashboard or a notebook, the member is granted or denied, regardless of the resource-level rules.
 */
export const organizationsProjectsAccessControlMemberObjectsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlMemberObjectsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMemberObjectsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMemberObjectsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlMemberObjectsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMemberObjectsRetrieveQueryParams = () => zod.object({
    member_id: zod
        .string()
        .describe('The organization membership id, as `organization_membership_id` in the members endpoint.'),
})

/**
 * Property rules configured for a member: the person and event properties the member can read, read and write, or not see.
 */
export const organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlMemberPropertiesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMemberPropertiesRetrieveQueryParams = () => zod.object({
    member_id: zod
        .string()
        .describe('The organization membership id, as `organization_membership_id` in the members endpoint.'),
})

/**
 * Set or clear one member's rule for a scope. A member rule applies to that person only and takes precedence over their role rules and the default. The scope is the project, a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const organizationsProjectsAccessControlMemberRulesUpdatePathIdMin = -2147483648
export const organizationsProjectsAccessControlMemberRulesUpdatePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMemberRulesUpdateParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMemberRulesUpdatePathIdMin)
        .max(organizationsProjectsAccessControlMemberRulesUpdatePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMemberRulesUpdateBody = () => zod
    .object({
        resource: zod
            .enum([
                'account',
                'action',
                'activity_log',
                'ai_observability_clusters',
                'customer_analytics',
                'customer_journey',
                'customer_task',
                'dashboard',
                'dashboard_template',
                'data_catalog',
                'dataset',
                'early_access_feature',
                'endpoint',
                'error_tracking',
                'evaluation',
                'experiment',
                'experiment_holdout',
                'experiment_saved_metric',
                'export',
                'external_data_source',
                'feature_flag',
                'heatmap',
                'hog_flow',
                'insight',
                'llm_analytics',
                'llm_playground',
                'llm_prompt',
                'llm_provider_key',
                'llm_skill',
                'logs',
                'marketing_analytics',
                'mcp_analytics',
                'metrics',
                'notebook',
                'project',
                'property_definition',
                'replay_scanner',
                'revenue_analytics',
                'session_recording',
                'session_recording_playlist',
                'sharing_configuration',
                'stamphog',
                'survey',
                'tagger',
                'ticket',
                'toolbar',
                'tracing',
                'vision_alert',
                'warehouse_objects',
                'warehouse_table',
                'warehouse_view',
                'web_analytics',
            ])
            .describe(
                '\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            )
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.\n\n\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
        member_id: zod
            .string()
            .describe('The organization membership id, as `organization_membership_id` in the members endpoint.'),
    })
    .describe('A rule for one organization member.')

/**
 * Every organization member's access in this project. For the project and for each resource type, the response gives the member's own rule and the level that is enforced. It also says where the enforced level comes from: the member's rule, a role's rule, the project default, or full access as an organization admin. Pass `member_id` for one member.
 */
export const organizationsProjectsAccessControlMembersRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlMembersRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlMembersRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlMembersRetrievePathIdMin)
        .max(organizationsProjectsAccessControlMembersRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlMembersRetrieveQueryParams = () => zod.object({
    member_id: zod.string().optional().describe('Narrow the list to one organization membership id.'),
})

/**
 * Object rules configured for a role: the single objects the role's members are granted or denied, regardless of the resource-level rules.
 */
export const organizationsProjectsAccessControlRoleObjectsRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlRoleObjectsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRoleObjectsRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRoleObjectsRetrievePathIdMin)
        .max(organizationsProjectsAccessControlRoleObjectsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRoleObjectsRetrieveQueryParams = () => zod.object({
    role_id: zod.string().describe('The role id, as `role_id` in the roles endpoint.'),
})

/**
 * Property rules configured for a role: the person and event properties the role's members can read, read and write, or not see.
 */
export const organizationsProjectsAccessControlRolePropertiesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlRolePropertiesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRolePropertiesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRolePropertiesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlRolePropertiesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRolePropertiesRetrieveQueryParams = () => zod.object({
    role_id: zod.string().describe('The role id, as `role_id` in the roles endpoint.'),
})

/**
 * Set or clear one role's rule for a scope. A role rule applies to every member of the role and takes precedence over the default. Requires the role-based access feature. The scope is the project, a whole resource type, one object, or one property definition. A null `access_level` removes the rule.
 */
export const organizationsProjectsAccessControlRoleRulesUpdatePathIdMin = -2147483648
export const organizationsProjectsAccessControlRoleRulesUpdatePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRoleRulesUpdateParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRoleRulesUpdatePathIdMin)
        .max(organizationsProjectsAccessControlRoleRulesUpdatePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRoleRulesUpdateBody = () => zod
    .object({
        resource: zod
            .enum([
                'account',
                'action',
                'activity_log',
                'ai_observability_clusters',
                'customer_analytics',
                'customer_journey',
                'customer_task',
                'dashboard',
                'dashboard_template',
                'data_catalog',
                'dataset',
                'early_access_feature',
                'endpoint',
                'error_tracking',
                'evaluation',
                'experiment',
                'experiment_holdout',
                'experiment_saved_metric',
                'export',
                'external_data_source',
                'feature_flag',
                'heatmap',
                'hog_flow',
                'insight',
                'llm_analytics',
                'llm_playground',
                'llm_prompt',
                'llm_provider_key',
                'llm_skill',
                'logs',
                'marketing_analytics',
                'mcp_analytics',
                'metrics',
                'notebook',
                'project',
                'property_definition',
                'replay_scanner',
                'revenue_analytics',
                'session_recording',
                'session_recording_playlist',
                'sharing_configuration',
                'stamphog',
                'survey',
                'tagger',
                'ticket',
                'toolbar',
                'tracing',
                'vision_alert',
                'warehouse_objects',
                'warehouse_table',
                'warehouse_view',
                'web_analytics',
            ])
            .describe(
                '\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            )
            .describe(
                'The scope of the rule: `project` for the project itself, a resource type such as `dashboard` for the whole resource type or for one object of it, or `property_definition` for one person or event property.\n\n\* `account` - account\n\* `action` - action\n\* `activity_log` - activity_log\n\* `ai_observability_clusters` - ai_observability_clusters\n\* `customer_analytics` - customer_analytics\n\* `customer_journey` - customer_journey\n\* `customer_task` - customer_task\n\* `dashboard` - dashboard\n\* `dashboard_template` - dashboard_template\n\* `data_catalog` - data_catalog\n\* `dataset` - dataset\n\* `early_access_feature` - early_access_feature\n\* `endpoint` - endpoint\n\* `error_tracking` - error_tracking\n\* `evaluation` - evaluation\n\* `experiment` - experiment\n\* `experiment_holdout` - experiment_holdout\n\* `experiment_saved_metric` - experiment_saved_metric\n\* `export` - export\n\* `external_data_source` - external_data_source\n\* `feature_flag` - feature_flag\n\* `heatmap` - heatmap\n\* `hog_flow` - hog_flow\n\* `insight` - insight\n\* `llm_analytics` - llm_analytics\n\* `llm_playground` - llm_playground\n\* `llm_prompt` - llm_prompt\n\* `llm_provider_key` - llm_provider_key\n\* `llm_skill` - llm_skill\n\* `logs` - logs\n\* `marketing_analytics` - marketing_analytics\n\* `mcp_analytics` - mcp_analytics\n\* `metrics` - metrics\n\* `notebook` - notebook\n\* `project` - project\n\* `property_definition` - property_definition\n\* `replay_scanner` - replay_scanner\n\* `revenue_analytics` - revenue_analytics\n\* `session_recording` - session_recording\n\* `session_recording_playlist` - session_recording_playlist\n\* `sharing_configuration` - sharing_configuration\n\* `stamphog` - stamphog\n\* `survey` - survey\n\* `tagger` - tagger\n\* `ticket` - ticket\n\* `toolbar` - toolbar\n\* `tracing` - tracing\n\* `vision_alert` - vision_alert\n\* `warehouse_objects` - warehouse_objects\n\* `warehouse_table` - warehouse_table\n\* `warehouse_view` - warehouse_view\n\* `web_analytics` - web_analytics'
            ),
        resource_id: zod
            .string()
            .nullish()
            .describe(
                "The object the rule applies to: an object's primary key, or a property definition id when `resource` is `property_definition`. Omit it for a rule on the whole resource type or on the project."
            ),
        access_level: zod
            .string()
            .nullable()
            .describe(
                'The level to set. `member` or `admin` for the project, `none`, `viewer`, `editor` or `manager` for a resource type or an object, `none`, `read` or `read_write` for a property. Null removes the rule, so the subject falls back to the level it inherits.'
            ),
        role_id: zod.string().describe('The role id, as `role_id` in the roles endpoint.'),
    })
    .describe('A rule for every member of one role.')

/**
 * Every role's resolved access to this project and to each resource type in it: the role's own rule, the level that is enforced, and the rule the enforced level comes from. Pass `role_id` for one role.
 */
export const organizationsProjectsAccessControlRolesRetrievePathIdMin = -2147483648
export const organizationsProjectsAccessControlRolesRetrievePathIdMax = 2147483647

export const OrganizationsProjectsAccessControlRolesRetrieveParams = () => zod.object({
    id: zod
        .number()
        .min(organizationsProjectsAccessControlRolesRetrievePathIdMin)
        .max(organizationsProjectsAccessControlRolesRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationsProjectsAccessControlRolesRetrieveQueryParams = () => zod.object({
    role_id: zod.string().optional().describe('Narrow the list to one role.'),
})
