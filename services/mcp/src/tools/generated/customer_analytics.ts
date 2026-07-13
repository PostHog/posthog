// AUTO-GENERATED from products/customer_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AccountRelationshipDefinitionsCreateBody,
    AccountRelationshipDefinitionsDestroyParams,
    AccountRelationshipDefinitionsListQueryParams,
    AccountRelationshipDefinitionsPartialUpdateBody,
    AccountRelationshipDefinitionsPartialUpdateParams,
    AccountRelationshipDefinitionsRetrieveParams,
    AccountsCreateBody,
    AccountsCustomPropertyValuesCreateBody,
    AccountsCustomPropertyValuesCreateParams,
    AccountsCustomPropertyValuesListParams,
    AccountsDestroyParams,
    AccountsListQueryParams,
    AccountsNotebooksCreateBody,
    AccountsNotebooksCreateParams,
    AccountsNotebooksDestroyParams,
    AccountsNotebooksListParams,
    AccountsNotebooksListQueryParams,
    AccountsNotebooksRetrieveParams,
    AccountsPartialUpdateBody,
    AccountsPartialUpdateParams,
    AccountsRelationshipsCreateBody,
    AccountsRelationshipsCreateParams,
    AccountsRelationshipsEndCreateParams,
    AccountsRelationshipsListParams,
    AccountsRelationshipsListQueryParams,
    AccountsRetrieveParams,
    CustomPropertyDefinitionsCreateBody,
    CustomPropertyDefinitionsDestroyParams,
    CustomPropertyDefinitionsListQueryParams,
    CustomPropertyDefinitionsPartialUpdateBody,
    CustomPropertyDefinitionsPartialUpdateParams,
    CustomPropertyDefinitionsRetrieveParams,
    GroupsTypesMetricsCreateBody,
    GroupsTypesMetricsCreateParams,
    GroupsTypesMetricsDestroyParams,
    GroupsTypesMetricsListParams,
    GroupsTypesMetricsListQueryParams,
    GroupsTypesMetricsPartialUpdateBody,
    GroupsTypesMetricsPartialUpdateParams,
    GroupsTypesMetricsRetrieveParams,
} from '@/generated/customer_analytics/api'
import { UsageMetricFiltersSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AccountRelationshipDefinitionsCreateSchema = AccountRelationshipDefinitionsCreateBody

const accountRelationshipDefinitionsCreate = (): ToolBase<
    typeof AccountRelationshipDefinitionsCreateSchema,
    Schemas.AccountRelationshipDefinition
> => ({
    name: 'account-relationship-definitions-create',
    schema: AccountRelationshipDefinitionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountRelationshipDefinitionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.is_single_holder !== undefined) {
            body['is_single_holder'] = params.is_single_holder
        }
        const result = await context.api.request<Schemas.AccountRelationshipDefinition>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/account_relationship_definitions/`,
            body,
        })
        return result
    },
})

const AccountRelationshipDefinitionsDestroySchema = AccountRelationshipDefinitionsDestroyParams.omit({
    project_id: true,
})

const accountRelationshipDefinitionsDestroy = (): ToolBase<
    typeof AccountRelationshipDefinitionsDestroySchema,
    unknown
> => ({
    name: 'account-relationship-definitions-destroy',
    schema: AccountRelationshipDefinitionsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof AccountRelationshipDefinitionsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/account_relationship_definitions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AccountRelationshipDefinitionsListSchema = AccountRelationshipDefinitionsListQueryParams

const accountRelationshipDefinitionsList = (): ToolBase<
    typeof AccountRelationshipDefinitionsListSchema,
    WithPostHogUrl<Schemas.PaginatedAccountRelationshipDefinitionList>
> => ({
    name: 'account-relationship-definitions-list',
    schema: AccountRelationshipDefinitionsListSchema,
    handler: async (context: Context, params: z.infer<typeof AccountRelationshipDefinitionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAccountRelationshipDefinitionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/account_relationship_definitions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const AccountRelationshipDefinitionsPartialUpdateSchema = AccountRelationshipDefinitionsPartialUpdateParams.omit({
    project_id: true,
}).extend(AccountRelationshipDefinitionsPartialUpdateBody.shape)

const accountRelationshipDefinitionsPartialUpdate = (): ToolBase<
    typeof AccountRelationshipDefinitionsPartialUpdateSchema,
    Schemas.AccountRelationshipDefinition
> => ({
    name: 'account-relationship-definitions-partial-update',
    schema: AccountRelationshipDefinitionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountRelationshipDefinitionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.is_single_holder !== undefined) {
            body['is_single_holder'] = params.is_single_holder
        }
        const result = await context.api.request<Schemas.AccountRelationshipDefinition>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/account_relationship_definitions/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const AccountRelationshipDefinitionsRetrieveSchema = AccountRelationshipDefinitionsRetrieveParams.omit({
    project_id: true,
})

const accountRelationshipDefinitionsRetrieve = (): ToolBase<
    typeof AccountRelationshipDefinitionsRetrieveSchema,
    Schemas.AccountRelationshipDefinition
> => ({
    name: 'account-relationship-definitions-retrieve',
    schema: AccountRelationshipDefinitionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AccountRelationshipDefinitionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AccountRelationshipDefinition>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/account_relationship_definitions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AccountsCreateSchema = AccountsCreateBody.extend({
    properties: AccountsCreateBody.shape['properties'].describe(
        'Typed account properties. `csm`, `account_executive`, `account_owner` are role assignments — each takes `{id, email}` of an existing user. `stripe_customer_id`, `hubspot_deal_id`, `billing_id`, `sfdc_id`, `zendesk_id` are optional string identifiers for the account in external systems. All fields are optional.'
    ),
    tags: AccountsCreateBody.shape['tags'].describe(
        'Tag names to attach to the account. Tags are created on demand if they do not already exist for the team.'
    ),
})

const accountsCreate = (): ToolBase<typeof AccountsCreateSchema, Schemas.Account> => ({
    name: 'accounts-create',
    schema: AccountsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.external_id !== undefined) {
            body['external_id'] = params.external_id
        }
        if (params.properties !== undefined) {
            body['properties'] = params.properties
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.Account>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/`,
            body,
        })
        return result
    },
})

const AccountsCustomPropertyValuesCreateSchema = AccountsCustomPropertyValuesCreateParams.omit({
    project_id: true,
}).extend(AccountsCustomPropertyValuesCreateBody.shape)

const accountsCustomPropertyValuesCreate = (): ToolBase<
    typeof AccountsCustomPropertyValuesCreateSchema,
    Schemas.CustomPropertyValue
> => ({
    name: 'accounts-custom-property-values-create',
    schema: AccountsCustomPropertyValuesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsCustomPropertyValuesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.definition !== undefined) {
            body['definition'] = params.definition
        }
        if (params.value !== undefined) {
            body['value'] = params.value
        }
        const result = await context.api.request<Schemas.CustomPropertyValue>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/custom_property_values/`,
            body,
        })
        return result
    },
})

const AccountsCustomPropertyValuesListSchema = AccountsCustomPropertyValuesListParams.omit({ project_id: true })

const accountsCustomPropertyValuesList = (): ToolBase<
    typeof AccountsCustomPropertyValuesListSchema,
    WithPostHogUrl<Schemas.CustomPropertyValue[]>
> => ({
    name: 'accounts-custom-property-values-list',
    schema: AccountsCustomPropertyValuesListSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsCustomPropertyValuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CustomPropertyValue[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/custom_property_values/`,
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const AccountsDestroySchema = AccountsDestroyParams.omit({ project_id: true })

const accountsDestroy = (): ToolBase<typeof AccountsDestroySchema, unknown> => ({
    name: 'accounts-destroy',
    schema: AccountsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof AccountsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AccountsListSchema = AccountsListQueryParams.extend({
    tags: AccountsListQueryParams.shape['tags'].describe(
        'JSON-encoded array of tag names to filter by, e.g. `["enterprise","priority"]`. Returns accounts that have any of the listed tags.'
    ),
})

const accountsList = (): ToolBase<typeof AccountsListSchema, WithPostHogUrl<Schemas.PaginatedAccountList>> => ({
    name: 'accounts-list',
    schema: AccountsListSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAccountList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/`,
            query: {
                account_executive: params.account_executive,
                account_owner: params.account_owner,
                all_roles_unassigned: params.all_roles_unassigned,
                csm: params.csm,
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                search: params.search,
                tags: params.tags,
            },
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const AccountsNotebooksCreateSchema = AccountsNotebooksCreateParams.omit({ project_id: true }).extend(
    AccountsNotebooksCreateBody.shape
)

const accountsNotebooksCreate = (): ToolBase<typeof AccountsNotebooksCreateSchema, Schemas.AccountNotebook> => ({
    name: 'accounts-notebooks-create',
    schema: AccountsNotebooksCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsNotebooksCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.text_content !== undefined) {
            body['text_content'] = params.text_content
        }
        const result = await context.api.request<Schemas.AccountNotebook>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/notebooks/`,
            body,
        })
        return result
    },
})

const AccountsNotebooksDestroySchema = AccountsNotebooksDestroyParams.omit({ project_id: true })

const accountsNotebooksDestroy = (): ToolBase<typeof AccountsNotebooksDestroySchema, unknown> => ({
    name: 'accounts-notebooks-destroy',
    schema: AccountsNotebooksDestroySchema,
    handler: async (context: Context, params: z.infer<typeof AccountsNotebooksDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/notebooks/${encodeURIComponent(String(params.short_id))}/`,
        })
        return result
    },
})

const AccountsNotebooksListSchema = AccountsNotebooksListParams.omit({ project_id: true }).extend(
    AccountsNotebooksListQueryParams.shape
)

const accountsNotebooksList = (): ToolBase<
    typeof AccountsNotebooksListSchema,
    WithPostHogUrl<Schemas.PaginatedAccountNotebookList>
> => ({
    name: 'accounts-notebooks-list',
    schema: AccountsNotebooksListSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsNotebooksListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAccountNotebookList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/notebooks/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const AccountsNotebooksRetrieveSchema = AccountsNotebooksRetrieveParams.omit({ project_id: true })

const accountsNotebooksRetrieve = (): ToolBase<typeof AccountsNotebooksRetrieveSchema, Schemas.AccountNotebook> => ({
    name: 'accounts-notebooks-retrieve',
    schema: AccountsNotebooksRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsNotebooksRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AccountNotebook>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/notebooks/${encodeURIComponent(String(params.short_id))}/`,
        })
        return result
    },
})

const AccountsPartialUpdateSchema = AccountsPartialUpdateParams.omit({ project_id: true })
    .extend(AccountsPartialUpdateBody.shape)
    .extend({
        properties: AccountsPartialUpdateBody.shape['properties'].describe(
            'Typed account properties. The server replaces the `properties` object as a whole, so include any existing values you want to preserve. Supported keys: `csm`, `account_executive`, `account_owner` (each `{id, email}` of an existing user), plus `stripe_customer_id`, `hubspot_deal_id`, `billing_id`, `sfdc_id`, `zendesk_id` (optional string identifiers for external systems).'
        ),
        tags: AccountsPartialUpdateBody.shape['tags'].describe(
            'Tag names to set on the account. Replaces the full existing tag set — pass the complete list, not a delta. Tags are created on demand if they do not already exist for the team.'
        ),
    })

const accountsPartialUpdate = (): ToolBase<typeof AccountsPartialUpdateSchema, Schemas.Account> => ({
    name: 'accounts-partial-update',
    schema: AccountsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.external_id !== undefined) {
            body['external_id'] = params.external_id
        }
        if (params.properties !== undefined) {
            body['properties'] = params.properties
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.Account>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const AccountsRelationshipsCreateSchema = AccountsRelationshipsCreateParams.omit({ project_id: true }).extend(
    AccountsRelationshipsCreateBody.shape
)

const accountsRelationshipsCreate = (): ToolBase<
    typeof AccountsRelationshipsCreateSchema,
    Schemas.AccountRelationship
> => ({
    name: 'accounts-relationships-create',
    schema: AccountsRelationshipsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsRelationshipsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.definition !== undefined) {
            body['definition'] = params.definition
        }
        if (params.user !== undefined) {
            body['user'] = params.user
        }
        const result = await context.api.request<Schemas.AccountRelationship>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/relationships/`,
            body,
        })
        return result
    },
})

const AccountsRelationshipsEndCreateSchema = AccountsRelationshipsEndCreateParams.omit({ project_id: true })

const accountsRelationshipsEndCreate = (): ToolBase<
    typeof AccountsRelationshipsEndCreateSchema,
    Schemas.AccountRelationship
> => ({
    name: 'accounts-relationships-end-create',
    schema: AccountsRelationshipsEndCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsRelationshipsEndCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AccountRelationship>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/relationships/${encodeURIComponent(String(params.id))}/end/`,
        })
        return result
    },
})

const AccountsRelationshipsListSchema = AccountsRelationshipsListParams.omit({ project_id: true }).extend(
    AccountsRelationshipsListQueryParams.shape
)

const accountsRelationshipsList = (): ToolBase<
    typeof AccountsRelationshipsListSchema,
    WithPostHogUrl<Schemas.AccountRelationship[]>
> => ({
    name: 'accounts-relationships-list',
    schema: AccountsRelationshipsListSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsRelationshipsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AccountRelationship[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.account_id))}/relationships/`,
            query: {
                include_history: params.include_history,
            },
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const AccountsRetrieveSchema = AccountsRetrieveParams.omit({ project_id: true })

const accountsRetrieve = (): ToolBase<typeof AccountsRetrieveSchema, Schemas.Account> => ({
    name: 'accounts-retrieve',
    schema: AccountsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AccountsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Account>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/accounts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const CustomPropertyDefinitionsCreateSchema = CustomPropertyDefinitionsCreateBody

const customPropertyDefinitionsCreate = (): ToolBase<
    typeof CustomPropertyDefinitionsCreateSchema,
    Schemas.CustomPropertyDefinition
> => ({
    name: 'custom-property-definitions-create',
    schema: CustomPropertyDefinitionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CustomPropertyDefinitionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.display_type !== undefined) {
            body['display_type'] = params.display_type
        }
        if (params.is_big_number !== undefined) {
            body['is_big_number'] = params.is_big_number
        }
        if (params.options !== undefined) {
            body['options'] = params.options
        }
        const result = await context.api.request<Schemas.CustomPropertyDefinition>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/custom_property_definitions/`,
            body,
        })
        return result
    },
})

const CustomPropertyDefinitionsDestroySchema = CustomPropertyDefinitionsDestroyParams.omit({ project_id: true })

const customPropertyDefinitionsDestroy = (): ToolBase<typeof CustomPropertyDefinitionsDestroySchema, unknown> => ({
    name: 'custom-property-definitions-destroy',
    schema: CustomPropertyDefinitionsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof CustomPropertyDefinitionsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/custom_property_definitions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const CustomPropertyDefinitionsListSchema = CustomPropertyDefinitionsListQueryParams

const customPropertyDefinitionsList = (): ToolBase<
    typeof CustomPropertyDefinitionsListSchema,
    WithPostHogUrl<Schemas.PaginatedCustomPropertyDefinitionList>
> => ({
    name: 'custom-property-definitions-list',
    schema: CustomPropertyDefinitionsListSchema,
    handler: async (context: Context, params: z.infer<typeof CustomPropertyDefinitionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCustomPropertyDefinitionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/custom_property_definitions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const CustomPropertyDefinitionsPartialUpdateSchema = CustomPropertyDefinitionsPartialUpdateParams.omit({
    project_id: true,
}).extend(CustomPropertyDefinitionsPartialUpdateBody.shape)

const customPropertyDefinitionsPartialUpdate = (): ToolBase<
    typeof CustomPropertyDefinitionsPartialUpdateSchema,
    Schemas.CustomPropertyDefinition
> => ({
    name: 'custom-property-definitions-partial-update',
    schema: CustomPropertyDefinitionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CustomPropertyDefinitionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.display_type !== undefined) {
            body['display_type'] = params.display_type
        }
        if (params.is_big_number !== undefined) {
            body['is_big_number'] = params.is_big_number
        }
        if (params.options !== undefined) {
            body['options'] = params.options
        }
        const result = await context.api.request<Schemas.CustomPropertyDefinition>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/custom_property_definitions/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const CustomPropertyDefinitionsRetrieveSchema = CustomPropertyDefinitionsRetrieveParams.omit({ project_id: true })

const customPropertyDefinitionsRetrieve = (): ToolBase<
    typeof CustomPropertyDefinitionsRetrieveSchema,
    Schemas.CustomPropertyDefinition
> => ({
    name: 'custom-property-definitions-retrieve',
    schema: CustomPropertyDefinitionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CustomPropertyDefinitionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CustomPropertyDefinition>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/custom_property_definitions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const UsageMetricsCreateSchema = GroupsTypesMetricsCreateParams.omit({ project_id: true })
    .extend(GroupsTypesMetricsCreateBody.shape)
    .extend({
        group_type_index: GroupsTypesMetricsCreateParams.shape['group_type_index'].describe(
            'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
        ),
        filters: UsageMetricFiltersSchema,
        math_property: GroupsTypesMetricsCreateBody.shape['math_property'].describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
    })

const usageMetricsCreate = (): ToolBase<typeof UsageMetricsCreateSchema, Schemas.GroupUsageMetric> => ({
    name: 'usage-metrics-create',
    schema: UsageMetricsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.format !== undefined) {
            body['format'] = params.format
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.display !== undefined) {
            body['display'] = params.display
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.math !== undefined) {
            body['math'] = params.math
        }
        if (params.math_property !== undefined) {
            body['math_property'] = params.math_property
        }
        const result = await context.api.request<Schemas.GroupUsageMetric>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/`,
            body,
        })
        return result
    },
})

const UsageMetricsDestroySchema = GroupsTypesMetricsDestroyParams.omit({ project_id: true }).extend({
    group_type_index: GroupsTypesMetricsDestroyParams.shape['group_type_index'].describe(
        'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
    ),
})

const usageMetricsDestroy = (): ToolBase<typeof UsageMetricsDestroySchema, unknown> => ({
    name: 'usage-metrics-destroy',
    schema: UsageMetricsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const UsageMetricsListSchema = GroupsTypesMetricsListParams.omit({ project_id: true })
    .extend(GroupsTypesMetricsListQueryParams.shape)
    .extend({
        group_type_index: GroupsTypesMetricsListParams.shape['group_type_index'].describe(
            'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
        ),
    })

const usageMetricsList = (): ToolBase<
    typeof UsageMetricsListSchema,
    WithPostHogUrl<Schemas.PaginatedGroupUsageMetricList>
> => ({
    name: 'usage-metrics-list',
    schema: UsageMetricsListSchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedGroupUsageMetricList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/customer-analytics')
    },
})

const UsageMetricsPartialUpdateSchema = GroupsTypesMetricsPartialUpdateParams.omit({ project_id: true })
    .extend(GroupsTypesMetricsPartialUpdateBody.shape)
    .extend({
        group_type_index: GroupsTypesMetricsPartialUpdateParams.shape['group_type_index'].describe(
            'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
        ),
        filters: UsageMetricFiltersSchema.optional(),
        math_property: GroupsTypesMetricsPartialUpdateBody.shape['math_property'].describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
    })

const usageMetricsPartialUpdate = (): ToolBase<typeof UsageMetricsPartialUpdateSchema, Schemas.GroupUsageMetric> => ({
    name: 'usage-metrics-partial-update',
    schema: UsageMetricsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.format !== undefined) {
            body['format'] = params.format
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.display !== undefined) {
            body['display'] = params.display
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.math !== undefined) {
            body['math'] = params.math
        }
        if (params.math_property !== undefined) {
            body['math_property'] = params.math_property
        }
        const result = await context.api.request<Schemas.GroupUsageMetric>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UsageMetricsRetrieveSchema = GroupsTypesMetricsRetrieveParams.omit({ project_id: true }).extend({
    group_type_index: GroupsTypesMetricsRetrieveParams.shape['group_type_index'].describe(
        'Legacy URL parameter retained for backward compatibility. Pass `0`. The stored value does not scope the metric — usage metrics apply to both groups and persons regardless of this value.'
    ),
})

const usageMetricsRetrieve = (): ToolBase<typeof UsageMetricsRetrieveSchema, Schemas.GroupUsageMetric> => ({
    name: 'usage-metrics-retrieve',
    schema: UsageMetricsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof UsageMetricsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GroupUsageMetric>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/groups_types/${encodeURIComponent(String(params.group_type_index))}/metrics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'account-relationship-definitions-create': accountRelationshipDefinitionsCreate,
    'account-relationship-definitions-destroy': accountRelationshipDefinitionsDestroy,
    'account-relationship-definitions-list': accountRelationshipDefinitionsList,
    'account-relationship-definitions-partial-update': accountRelationshipDefinitionsPartialUpdate,
    'account-relationship-definitions-retrieve': accountRelationshipDefinitionsRetrieve,
    'accounts-create': accountsCreate,
    'accounts-custom-property-values-create': accountsCustomPropertyValuesCreate,
    'accounts-custom-property-values-list': accountsCustomPropertyValuesList,
    'accounts-destroy': accountsDestroy,
    'accounts-list': accountsList,
    'accounts-notebooks-create': accountsNotebooksCreate,
    'accounts-notebooks-destroy': accountsNotebooksDestroy,
    'accounts-notebooks-list': accountsNotebooksList,
    'accounts-notebooks-retrieve': accountsNotebooksRetrieve,
    'accounts-partial-update': accountsPartialUpdate,
    'accounts-relationships-create': accountsRelationshipsCreate,
    'accounts-relationships-end-create': accountsRelationshipsEndCreate,
    'accounts-relationships-list': accountsRelationshipsList,
    'accounts-retrieve': accountsRetrieve,
    'custom-property-definitions-create': customPropertyDefinitionsCreate,
    'custom-property-definitions-destroy': customPropertyDefinitionsDestroy,
    'custom-property-definitions-list': customPropertyDefinitionsList,
    'custom-property-definitions-partial-update': customPropertyDefinitionsPartialUpdate,
    'custom-property-definitions-retrieve': customPropertyDefinitionsRetrieve,
    'usage-metrics-create': usageMetricsCreate,
    'usage-metrics-destroy': usageMetricsDestroy,
    'usage-metrics-list': usageMetricsList,
    'usage-metrics-partial-update': usageMetricsPartialUpdate,
    'usage-metrics-retrieve': usageMetricsRetrieve,
}
