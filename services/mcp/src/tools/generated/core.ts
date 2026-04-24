// AUTO-GENERATED from services/mcp/definitions/core.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    OrganizationsProjectsPartialUpdateBody,
    OrganizationsProjectsPartialUpdateParams,
    OrganizationsProjectsRetrieveParams,
    SubscriptionsCreateBody,
    SubscriptionsDeliveriesListParams,
    SubscriptionsDeliveriesListQueryParams,
    SubscriptionsDeliveriesRetrieveParams,
    SubscriptionsListQueryParams,
    SubscriptionsPartialUpdateBody,
    SubscriptionsPartialUpdateParams,
    SubscriptionsRetrieveParams,
    SubscriptionsTestDeliveryCreateParams,
    UsersPartialUpdateBody,
    UsersPartialUpdateParams,
    UsersRetrieveParams,
} from '@/generated/core/api'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ProjectGetSchema = OrganizationsProjectsRetrieveParams.omit({ organization_id: true }).extend({
    id: OrganizationsProjectsRetrieveParams.shape['id'].describe(
        "Project ID, or `@current` to fetch the caller's active project."
    ),
})

const projectGet = (): ToolBase<typeof ProjectGetSchema, Schemas.ProjectBackwardCompat> => ({
    name: 'project-get',
    schema: ProjectGetSchema,
    handler: async (context: Context, params: z.infer<typeof ProjectGetSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const result = await context.api.request<Schemas.ProjectBackwardCompat>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(params.id))}/`,
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
        id: OrganizationsProjectsPartialUpdateParams.shape['id'].describe(
            "Project ID, or `@current` to target the caller's active project."
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
        const result = await context.api.request<Schemas.ProjectBackwardCompat>({
            method: 'PATCH',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const SubscriptionsListSchema = SubscriptionsListQueryParams

const subscriptionsList = (): ToolBase<
    typeof SubscriptionsListSchema,
    WithPostHogUrl<Schemas.PaginatedSubscriptionList>
> => ({
    name: 'subscriptions-list',
    schema: SubscriptionsListSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSubscriptionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/`,
            query: {
                created_by: params.created_by,
                dashboard: params.dashboard,
                insight: params.insight,
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                resource_type: params.resource_type,
                search: params.search,
                target_type: params.target_type,
            },
        })
        return await withPostHogUrl(context, result, '/')
    },
})

const SubscriptionsCreateSchema = SubscriptionsCreateBody

const subscriptionsCreate = (): ToolBase<typeof SubscriptionsCreateSchema, Schemas.Subscription> => ({
    name: 'subscriptions-create',
    schema: SubscriptionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.dashboard !== undefined) {
            body['dashboard'] = params.dashboard
        }
        if (params.insight !== undefined) {
            body['insight'] = params.insight
        }
        if (params.dashboard_export_insights !== undefined) {
            body['dashboard_export_insights'] = params.dashboard_export_insights
        }
        if (params.target_type !== undefined) {
            body['target_type'] = params.target_type
        }
        if (params.target_value !== undefined) {
            body['target_value'] = params.target_value
        }
        if (params.frequency !== undefined) {
            body['frequency'] = params.frequency
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.byweekday !== undefined) {
            body['byweekday'] = params.byweekday
        }
        if (params.bysetpos !== undefined) {
            body['bysetpos'] = params.bysetpos
        }
        if (params.count !== undefined) {
            body['count'] = params.count
        }
        if (params.start_date !== undefined) {
            body['start_date'] = params.start_date
        }
        if (params.until_date !== undefined) {
            body['until_date'] = params.until_date
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.integration_id !== undefined) {
            body['integration_id'] = params.integration_id
        }
        if (params.invite_message !== undefined) {
            body['invite_message'] = params.invite_message
        }
        if (params.summary_enabled !== undefined) {
            body['summary_enabled'] = params.summary_enabled
        }
        if (params.summary_prompt_guide !== undefined) {
            body['summary_prompt_guide'] = params.summary_prompt_guide
        }
        const result = await context.api.request<Schemas.Subscription>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/`,
            body,
        })
        return result
    },
})

const SubscriptionsRetrieveSchema = SubscriptionsRetrieveParams.omit({ project_id: true })

const subscriptionsRetrieve = (): ToolBase<typeof SubscriptionsRetrieveSchema, Schemas.Subscription> => ({
    name: 'subscriptions-retrieve',
    schema: SubscriptionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Subscription>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SubscriptionsPartialUpdateSchema = SubscriptionsPartialUpdateParams.omit({ project_id: true }).extend(
    SubscriptionsPartialUpdateBody.shape
)

const subscriptionsPartialUpdate = (): ToolBase<typeof SubscriptionsPartialUpdateSchema, Schemas.Subscription> => ({
    name: 'subscriptions-partial-update',
    schema: SubscriptionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.dashboard !== undefined) {
            body['dashboard'] = params.dashboard
        }
        if (params.insight !== undefined) {
            body['insight'] = params.insight
        }
        if (params.dashboard_export_insights !== undefined) {
            body['dashboard_export_insights'] = params.dashboard_export_insights
        }
        if (params.target_type !== undefined) {
            body['target_type'] = params.target_type
        }
        if (params.target_value !== undefined) {
            body['target_value'] = params.target_value
        }
        if (params.frequency !== undefined) {
            body['frequency'] = params.frequency
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.byweekday !== undefined) {
            body['byweekday'] = params.byweekday
        }
        if (params.bysetpos !== undefined) {
            body['bysetpos'] = params.bysetpos
        }
        if (params.count !== undefined) {
            body['count'] = params.count
        }
        if (params.start_date !== undefined) {
            body['start_date'] = params.start_date
        }
        if (params.until_date !== undefined) {
            body['until_date'] = params.until_date
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.integration_id !== undefined) {
            body['integration_id'] = params.integration_id
        }
        if (params.invite_message !== undefined) {
            body['invite_message'] = params.invite_message
        }
        if (params.summary_enabled !== undefined) {
            body['summary_enabled'] = params.summary_enabled
        }
        if (params.summary_prompt_guide !== undefined) {
            body['summary_prompt_guide'] = params.summary_prompt_guide
        }
        const result = await context.api.request<Schemas.Subscription>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.id))}/`,
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
        const filtered = omitResponseFields(result, [
            'is_impersonated',
            'is_impersonated_until',
            'is_impersonated_read_only',
            'sensitive_session_expires_at',
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
        const result = await context.api.request<Schemas.User>({
            method: 'PATCH',
            path: `/api/users/${encodeURIComponent(String(params.uuid))}/`,
            body,
        })
        return result
    },
})

const SubscriptionsTestDeliveryCreateSchema = SubscriptionsTestDeliveryCreateParams.omit({ project_id: true })

const subscriptionsTestDeliveryCreate = (): ToolBase<typeof SubscriptionsTestDeliveryCreateSchema, unknown> => ({
    name: 'subscriptions-test-delivery-create',
    schema: SubscriptionsTestDeliveryCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsTestDeliveryCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.id))}/test-delivery/`,
        })
        return result
    },
})

const SubscriptionsDeliveriesListSchema = SubscriptionsDeliveriesListParams.omit({ project_id: true }).extend(
    SubscriptionsDeliveriesListQueryParams.shape
)

const subscriptionsDeliveriesList = (): ToolBase<
    typeof SubscriptionsDeliveriesListSchema,
    WithPostHogUrl<Schemas.PaginatedSubscriptionDeliveryList>
> => ({
    name: 'subscriptions-deliveries-list',
    schema: SubscriptionsDeliveriesListSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsDeliveriesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSubscriptionDeliveryList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.subscription_id))}/deliveries/`,
            query: {
                cursor: params.cursor,
                status: params.status,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, ['content_snapshot', 'recipient_results', 'error'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/')
    },
})

const SubscriptionsDeliveriesRetrieveSchema = SubscriptionsDeliveriesRetrieveParams.omit({ project_id: true })

const subscriptionsDeliveriesRetrieve = (): ToolBase<
    typeof SubscriptionsDeliveriesRetrieveSchema,
    Schemas.SubscriptionDelivery
> => ({
    name: 'subscriptions-deliveries-retrieve',
    schema: SubscriptionsDeliveriesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsDeliveriesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SubscriptionDelivery>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.subscription_id))}/deliveries/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, ['content_snapshot', 'recipient_results', 'error']) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'project-get': projectGet,
    'project-settings-update': projectSettingsUpdate,
    'subscriptions-list': subscriptionsList,
    'subscriptions-create': subscriptionsCreate,
    'subscriptions-retrieve': subscriptionsRetrieve,
    'subscriptions-partial-update': subscriptionsPartialUpdate,
    'user-get': userGet,
    'user-settings-update': userSettingsUpdate,
    'subscriptions-test-delivery-create': subscriptionsTestDeliveryCreate,
    'subscriptions-deliveries-list': subscriptionsDeliveriesList,
    'subscriptions-deliveries-retrieve': subscriptionsDeliveriesRetrieve,
}
