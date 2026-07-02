// AUTO-GENERATED from services/mcp/definitions/core.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    DesktopFileSystemCanvasPartialUpdateBody,
    DesktopFileSystemCanvasPartialUpdateParams,
    DesktopFileSystemCreateBody,
    DesktopFileSystemInstructionsPartialUpdateBody,
    DesktopFileSystemInstructionsPartialUpdateParams,
    DesktopFileSystemInstructionsRetrieveParams,
    DesktopFileSystemListQueryParams,
    DesktopFileSystemRetrieveParams,
    OrganizationsProjectsPartialUpdateBody,
    OrganizationsProjectsPartialUpdateParams,
    OrganizationsProjectsRetrieveParams,
    UsersPartialUpdateBody,
    UsersPartialUpdateParams,
    UsersRetrieveParams,
} from '@/generated/core/api'
import { castStringToInt } from '@/tools/cast-helpers'
import { omitResponseFields, pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DesktopFileSystemCanvasPartialUpdateSchema = DesktopFileSystemCanvasPartialUpdateParams.omit({ project_id: true })
    .extend(DesktopFileSystemCanvasPartialUpdateBody.shape)
    .extend({
        id: DesktopFileSystemCanvasPartialUpdateParams.shape['id'].describe(
            'ID of the canvas (desktop "dashboard" item) whose code to publish.'
        ),
        code: DesktopFileSystemCanvasPartialUpdateBody.shape['code']
            .unwrap()
            .describe('The complete single-file React source for the canvas. Replaces the current code wholesale.'),
        name: DesktopFileSystemCanvasPartialUpdateBody.shape['name'].describe(
            'Optional new display name for the canvas. When set, renames the canvas (the leaf of its path) in place. Omit to leave the name unchanged.'
        ),
    })

const desktopFileSystemCanvasPartialUpdate = (): ToolBase<
    typeof DesktopFileSystemCanvasPartialUpdateSchema,
    Schemas.FileSystem
> => ({
    name: 'desktop-file-system-canvas-partial-update',
    schema: DesktopFileSystemCanvasPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof DesktopFileSystemCanvasPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.code !== undefined) {
            body['code'] = params.code
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.FileSystem>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/desktop_file_system/${encodeURIComponent(String(params.id))}/canvas/`,
            body,
        })
        return result
    },
})

const DesktopFileSystemCreateSchema = DesktopFileSystemCreateBody.extend({
    path: DesktopFileSystemCreateBody.shape['path'].describe(
        'Slash-delimited location of the channel, e.g. "Marketing/Q1 Campaigns". Intermediate folders are created automatically.'
    ),
    type: DesktopFileSystemCreateBody.shape['type'].describe('Use "folder" to create a channel.'),
})

const desktopFileSystemCreate = (): ToolBase<typeof DesktopFileSystemCreateSchema, Schemas.FileSystem> => ({
    name: 'desktop-file-system-create',
    schema: DesktopFileSystemCreateSchema,
    handler: async (context: Context, params: z.infer<typeof DesktopFileSystemCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.ref !== undefined) {
            body['ref'] = params.ref
        }
        if (params.href !== undefined) {
            body['href'] = params.href
        }
        if (params.meta !== undefined) {
            body['meta'] = params.meta
        }
        if (params.shortcut !== undefined) {
            body['shortcut'] = params.shortcut
        }
        const result = await context.api.request<Schemas.FileSystem>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/desktop_file_system/`,
            body,
        })
        return result
    },
})

const DesktopFileSystemInstructionsPartialUpdateSchema = DesktopFileSystemInstructionsPartialUpdateParams.omit({
    project_id: true,
})
    .extend(DesktopFileSystemInstructionsPartialUpdateBody.shape)
    .extend({
        id: DesktopFileSystemInstructionsPartialUpdateParams.shape['id'].describe(
            'ID of the channel (desktop folder) whose instructions to update.'
        ),
        content: DesktopFileSystemInstructionsPartialUpdateBody.shape['content'].describe(
            "Full markdown instructions to publish. Pass an empty string to erase the channel's instructions while keeping the instruction set."
        ),
    })

const desktopFileSystemInstructionsPartialUpdate = (): ToolBase<
    typeof DesktopFileSystemInstructionsPartialUpdateSchema,
    Schemas.FolderInstructions
> => ({
    name: 'desktop-file-system-instructions-partial-update',
    schema: DesktopFileSystemInstructionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof DesktopFileSystemInstructionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.FolderInstructions>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/desktop_file_system/${encodeURIComponent(String(params.id))}/instructions/`,
            body,
        })
        return result
    },
})

const DesktopFileSystemInstructionsRetrieveSchema = DesktopFileSystemInstructionsRetrieveParams.omit({
    project_id: true,
}).extend({
    id: DesktopFileSystemInstructionsRetrieveParams.shape['id'].describe(
        'ID of the channel (desktop folder) whose instructions to fetch.'
    ),
})

const desktopFileSystemInstructionsRetrieve = (): ToolBase<
    typeof DesktopFileSystemInstructionsRetrieveSchema,
    Schemas.FolderInstructions
> => ({
    name: 'desktop-file-system-instructions-retrieve',
    schema: DesktopFileSystemInstructionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof DesktopFileSystemInstructionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FolderInstructions>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/desktop_file_system/${encodeURIComponent(String(params.id))}/instructions/`,
        })
        return result
    },
})

const DesktopFileSystemListSchema = DesktopFileSystemListQueryParams

const desktopFileSystemList = (): ToolBase<typeof DesktopFileSystemListSchema, Schemas.PaginatedFileSystemList> => ({
    name: 'desktop-file-system-list',
    schema: DesktopFileSystemListSchema,
    handler: async (context: Context, params: z.infer<typeof DesktopFileSystemListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedFileSystemList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/desktop_file_system/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const DesktopFileSystemRetrieveSchema = DesktopFileSystemRetrieveParams.omit({ project_id: true })

const desktopFileSystemRetrieve = (): ToolBase<typeof DesktopFileSystemRetrieveSchema, Schemas.FileSystem> => ({
    name: 'desktop-file-system-retrieve',
    schema: DesktopFileSystemRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof DesktopFileSystemRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FileSystem>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/desktop_file_system/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ProjectGetSchema = OrganizationsProjectsRetrieveParams.omit({ organization_id: true }).extend({
    id: z
        .preprocess(
            castStringToInt,
            OrganizationsProjectsRetrieveParams.shape['id']
                .describe("Project ID. If omitted, returns the caller's active project.")
                .optional()
        )
        .optional(),
})

const projectGet = (): ToolBase<typeof ProjectGetSchema, Schemas.ProjectBackwardCompat> => ({
    name: 'project-get',
    schema: ProjectGetSchema,
    handler: async (context: Context, params: z.infer<typeof ProjectGetSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const id = params.id ?? (await context.stateManager.getProjectId())
        if (!id) {
            throw new Error('id is required. Provide it explicitly or set an active project first.')
        }
        const result = await context.api.request<Schemas.ProjectBackwardCompat>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/`,
        })
        const filtered = omitResponseFields(result, [
            'secret_api_token',
            'secret_api_token_backup',
            'live_events_token',
            'default_modifiers',
        ]) as typeof result
        return filtered
    },
})

const ProjectSettingsUpdateSchema = OrganizationsProjectsPartialUpdateParams.omit({ organization_id: true })
    .extend(OrganizationsProjectsPartialUpdateBody.shape)
    .extend({
        id: z.preprocess(
            castStringToInt,
            OrganizationsProjectsPartialUpdateParams.shape['id'].describe(
                "Project ID, or `@current` to target the caller's active project."
            )
        ),
    })

const projectSettingsUpdate = (): ToolBase<typeof ProjectSettingsUpdateSchema, Schemas.ProjectBackwardCompat> => ({
    name: 'project-settings-update',
    schema: ProjectSettingsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ProjectSettingsUpdateSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.product_description !== undefined) {
            body['product_description'] = params.product_description
        }
        if (params.app_urls !== undefined) {
            body['app_urls'] = params.app_urls
        }
        if (params.anonymize_ips !== undefined) {
            body['anonymize_ips'] = params.anonymize_ips
        }
        if (params.completed_snippet_onboarding !== undefined) {
            body['completed_snippet_onboarding'] = params.completed_snippet_onboarding
        }
        if (params.test_account_filters !== undefined) {
            body['test_account_filters'] = params.test_account_filters
        }
        if (params.test_account_filters_default_checked !== undefined) {
            body['test_account_filters_default_checked'] = params.test_account_filters_default_checked
        }
        if (params.path_cleaning_filters !== undefined) {
            body['path_cleaning_filters'] = params.path_cleaning_filters
        }
        if (params.is_demo !== undefined) {
            body['is_demo'] = params.is_demo
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.data_attributes !== undefined) {
            body['data_attributes'] = params.data_attributes
        }
        if (params.person_display_name_properties !== undefined) {
            body['person_display_name_properties'] = params.person_display_name_properties
        }
        if (params.correlation_config !== undefined) {
            body['correlation_config'] = params.correlation_config
        }
        if (params.autocapture_opt_out !== undefined) {
            body['autocapture_opt_out'] = params.autocapture_opt_out
        }
        if (params.autocapture_exceptions_opt_in !== undefined) {
            body['autocapture_exceptions_opt_in'] = params.autocapture_exceptions_opt_in
        }
        if (params.autocapture_web_vitals_opt_in !== undefined) {
            body['autocapture_web_vitals_opt_in'] = params.autocapture_web_vitals_opt_in
        }
        if (params.autocapture_web_vitals_allowed_metrics !== undefined) {
            body['autocapture_web_vitals_allowed_metrics'] = params.autocapture_web_vitals_allowed_metrics
        }
        if (params.autocapture_exceptions_errors_to_ignore !== undefined) {
            body['autocapture_exceptions_errors_to_ignore'] = params.autocapture_exceptions_errors_to_ignore
        }
        if (params.capture_console_log_opt_in !== undefined) {
            body['capture_console_log_opt_in'] = params.capture_console_log_opt_in
        }
        if (params.capture_performance_opt_in !== undefined) {
            body['capture_performance_opt_in'] = params.capture_performance_opt_in
        }
        if (params.session_recording_opt_in !== undefined) {
            body['session_recording_opt_in'] = params.session_recording_opt_in
        }
        if (params.session_recording_sample_rate !== undefined) {
            body['session_recording_sample_rate'] = params.session_recording_sample_rate
        }
        if (params.session_recording_minimum_duration_milliseconds !== undefined) {
            body['session_recording_minimum_duration_milliseconds'] =
                params.session_recording_minimum_duration_milliseconds
        }
        if (params.session_recording_linked_flag !== undefined) {
            body['session_recording_linked_flag'] = params.session_recording_linked_flag
        }
        if (params.session_recording_network_payload_capture_config !== undefined) {
            body['session_recording_network_payload_capture_config'] =
                params.session_recording_network_payload_capture_config
        }
        if (params.session_recording_masking_config !== undefined) {
            body['session_recording_masking_config'] = params.session_recording_masking_config
        }
        if (params.session_recording_url_trigger_config !== undefined) {
            body['session_recording_url_trigger_config'] = params.session_recording_url_trigger_config
        }
        if (params.session_recording_url_blocklist_config !== undefined) {
            body['session_recording_url_blocklist_config'] = params.session_recording_url_blocklist_config
        }
        if (params.session_recording_event_trigger_config !== undefined) {
            body['session_recording_event_trigger_config'] = params.session_recording_event_trigger_config
        }
        if (params.session_recording_trigger_match_type_config !== undefined) {
            body['session_recording_trigger_match_type_config'] = params.session_recording_trigger_match_type_config
        }
        if (params.session_recording_trigger_groups !== undefined) {
            body['session_recording_trigger_groups'] = params.session_recording_trigger_groups
        }
        if (params.session_recording_retention_period !== undefined) {
            body['session_recording_retention_period'] = params.session_recording_retention_period
        }
        if (params.session_replay_config !== undefined) {
            body['session_replay_config'] = params.session_replay_config
        }
        if (params.survey_config !== undefined) {
            body['survey_config'] = params.survey_config
        }
        if (params.access_control !== undefined) {
            body['access_control'] = params.access_control
        }
        if (params.week_start_day !== undefined) {
            body['week_start_day'] = params.week_start_day
        }
        if (params.primary_dashboard !== undefined) {
            body['primary_dashboard'] = params.primary_dashboard
        }
        if (params.live_events_columns !== undefined) {
            body['live_events_columns'] = params.live_events_columns
        }
        if (params.recording_domains !== undefined) {
            body['recording_domains'] = params.recording_domains
        }
        if (params.inject_web_apps !== undefined) {
            body['inject_web_apps'] = params.inject_web_apps
        }
        if (params.extra_settings !== undefined) {
            body['extra_settings'] = params.extra_settings
        }
        if (params.modifiers !== undefined) {
            body['modifiers'] = params.modifiers
        }
        if (params.has_completed_onboarding_for !== undefined) {
            body['has_completed_onboarding_for'] = params.has_completed_onboarding_for
        }
        if (params.surveys_opt_in !== undefined) {
            body['surveys_opt_in'] = params.surveys_opt_in
        }
        if (params.heatmaps_opt_in !== undefined) {
            body['heatmaps_opt_in'] = params.heatmaps_opt_in
        }
        if (params.flags_persistence_default !== undefined) {
            body['flags_persistence_default'] = params.flags_persistence_default
        }
        if (params.receive_org_level_activity_logs !== undefined) {
            body['receive_org_level_activity_logs'] = params.receive_org_level_activity_logs
        }
        if (params.business_model !== undefined) {
            body['business_model'] = params.business_model
        }
        if (params.conversations_enabled !== undefined) {
            body['conversations_enabled'] = params.conversations_enabled
        }
        if (params.conversations_settings !== undefined) {
            body['conversations_settings'] = params.conversations_settings
        }
        if (params.logs_settings !== undefined) {
            body['logs_settings'] = params.logs_settings
        }
        if (params.proactive_tasks_enabled !== undefined) {
            body['proactive_tasks_enabled'] = params.proactive_tasks_enabled
        }
        if (params.revenue_analytics_config !== undefined) {
            body['revenue_analytics_config'] = params.revenue_analytics_config
        }
        if (params.marketing_analytics_config !== undefined) {
            body['marketing_analytics_config'] = params.marketing_analytics_config
        }
        if (params.customer_analytics_config !== undefined) {
            body['customer_analytics_config'] = params.customer_analytics_config
        }
        if (params.workflows_config !== undefined) {
            body['workflows_config'] = params.workflows_config
        }
        if (params.base_currency !== undefined) {
            body['base_currency'] = params.base_currency
        }
        if (params.capture_dead_clicks !== undefined) {
            body['capture_dead_clicks'] = params.capture_dead_clicks
        }
        if (params.cookieless_server_hash_mode !== undefined) {
            body['cookieless_server_hash_mode'] = params.cookieless_server_hash_mode
        }
        if (params.human_friendly_comparison_periods !== undefined) {
            body['human_friendly_comparison_periods'] = params.human_friendly_comparison_periods
        }
        if (params.feature_flag_confirmation_enabled !== undefined) {
            body['feature_flag_confirmation_enabled'] = params.feature_flag_confirmation_enabled
        }
        if (params.feature_flag_confirmation_message !== undefined) {
            body['feature_flag_confirmation_message'] = params.feature_flag_confirmation_message
        }
        if (params.default_evaluation_contexts_enabled !== undefined) {
            body['default_evaluation_contexts_enabled'] = params.default_evaluation_contexts_enabled
        }
        if (params.require_evaluation_contexts !== undefined) {
            body['require_evaluation_contexts'] = params.require_evaluation_contexts
        }
        if (params.default_data_theme !== undefined) {
            body['default_data_theme'] = params.default_data_theme
        }
        if (params.onboarding_tasks !== undefined) {
            body['onboarding_tasks'] = params.onboarding_tasks
        }
        if (params.web_analytics_pre_aggregated_tables_enabled !== undefined) {
            body['web_analytics_pre_aggregated_tables_enabled'] = params.web_analytics_pre_aggregated_tables_enabled
        }
        const result = await context.api.request<Schemas.ProjectBackwardCompat>({
            method: 'PATCH',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UserGetSchema = UsersRetrieveParams.extend({
    uuid: UsersRetrieveParams.shape['uuid'].describe('User UUID, or `@me` to target the authenticated user.'),
})

const userGet = (): ToolBase<typeof UserGetSchema, Schemas.User> => ({
    name: 'user-get',
    schema: UserGetSchema,
    handler: async (context: Context, params: z.infer<typeof UserGetSchema>) => {
        const result = await context.api.request<Schemas.User>({
            method: 'GET',
            path: `/api/users/${encodeURIComponent(String(params.uuid))}/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'uuid',
            'distinct_id',
            'email',
            'pending_email',
            'is_email_verified',
            'first_name',
            'last_name',
            'date_joined',
            'is_staff',
            'has_password',
            'is_2fa_enabled',
            'has_social_auth',
            'has_sso_enforcement',
            'passkeys_enabled_for_2fa',
            'allow_impersonation',
            'notification_settings',
            'anonymize_data',
            'toolbar_mode',
            'events_column_config',
            'theme_mode',
            'hedgehog_config',
            'allow_sidebar_suggestions',
            'shortcut_position',
            'role_at_organization',
            'hide_mcp_hints',
            'scene_personalisation',
            'pending_invites',
            'organization.id',
            'organization.name',
            'team.id',
            'team.name',
            'organizations.*.id',
            'organizations.*.name',
        ]) as typeof result
        return filtered
    },
})

const UserSettingsUpdateSchema = UsersPartialUpdateParams.extend(UsersPartialUpdateBody.shape).extend({
    uuid: UsersPartialUpdateParams.shape['uuid'].describe('User UUID, or `@me` to target the authenticated user.'),
})

const userSettingsUpdate = (): ToolBase<typeof UserSettingsUpdateSchema, Schemas.User> => ({
    name: 'user-settings-update',
    schema: UserSettingsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof UserSettingsUpdateSchema>) => {
        const body: Record<string, unknown> = {}
        if (params.first_name !== undefined) {
            body['first_name'] = params.first_name
        }
        if (params.last_name !== undefined) {
            body['last_name'] = params.last_name
        }
        if (params.email !== undefined) {
            body['email'] = params.email
        }
        if (params.notification_settings !== undefined) {
            body['notification_settings'] = params.notification_settings
        }
        if (params.anonymize_data !== undefined) {
            body['anonymize_data'] = params.anonymize_data
        }
        if (params.allow_impersonation !== undefined) {
            body['allow_impersonation'] = params.allow_impersonation
        }
        if (params.toolbar_mode !== undefined) {
            body['toolbar_mode'] = params.toolbar_mode
        }
        if (params.set_current_organization !== undefined) {
            body['set_current_organization'] = params.set_current_organization
        }
        if (params.set_current_team !== undefined) {
            body['set_current_team'] = params.set_current_team
        }
        if (params.password !== undefined) {
            body['password'] = params.password
        }
        if (params.current_password !== undefined) {
            body['current_password'] = params.current_password
        }
        if (params.events_column_config !== undefined) {
            body['events_column_config'] = params.events_column_config
        }
        if (params.has_seen_product_intro_for !== undefined) {
            body['has_seen_product_intro_for'] = params.has_seen_product_intro_for
        }
        if (params.theme_mode !== undefined) {
            body['theme_mode'] = params.theme_mode
        }
        if (params.hedgehog_config !== undefined) {
            body['hedgehog_config'] = params.hedgehog_config
        }
        if (params.allow_sidebar_suggestions !== undefined) {
            body['allow_sidebar_suggestions'] = params.allow_sidebar_suggestions
        }
        if (params.shortcut_position !== undefined) {
            body['shortcut_position'] = params.shortcut_position
        }
        if (params.role_at_organization !== undefined) {
            body['role_at_organization'] = params.role_at_organization
        }
        if (params.passkeys_enabled_for_2fa !== undefined) {
            body['passkeys_enabled_for_2fa'] = params.passkeys_enabled_for_2fa
        }
        if (params.hide_mcp_hints !== undefined) {
            body['hide_mcp_hints'] = params.hide_mcp_hints
        }
        const result = await context.api.request<Schemas.User>({
            method: 'PATCH',
            path: `/api/users/${encodeURIComponent(String(params.uuid))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'desktop-file-system-canvas-partial-update': desktopFileSystemCanvasPartialUpdate,
    'desktop-file-system-create': desktopFileSystemCreate,
    'desktop-file-system-instructions-partial-update': desktopFileSystemInstructionsPartialUpdate,
    'desktop-file-system-instructions-retrieve': desktopFileSystemInstructionsRetrieve,
    'desktop-file-system-list': desktopFileSystemList,
    'desktop-file-system-retrieve': desktopFileSystemRetrieve,
    'project-get': projectGet,
    'project-settings-update': projectSettingsUpdate,
    'user-get': userGet,
    'user-settings-update': userSettingsUpdate,
}
