/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 21 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const AccountsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AccountsListQueryParams = /* @__PURE__ */ zod.object({
    account_executive: zod
        .string()
        .optional()
        .describe("Filter by account executive. Use 'unassigned' or an integer user id."),
    account_owner: zod.string().optional().describe("Filter by account owner. Use 'unassigned' or an integer user id."),
    all_roles_unassigned: zod
        .boolean()
        .optional()
        .describe('When true, returns only accounts where CSM, account executive, and account owner are all unset.'),
    csm: zod
        .string()
        .optional()
        .describe("Filter by CSM. Use 'unassigned' for accounts with no CSM, or an integer user id."),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod.string().optional().describe("Sort order. Defaults to '-created_at'."),
    search: zod.string().optional().describe('Case-insensitive substring search across account name and external ID.'),
    tags: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded array of tag names to filter by, e.g. `["enterprise","priority"]`. Returns accounts that have any of the listed tags. Malformed values (not a JSON-encoded list of strings) return a 400.'
        ),
})

export const AccountsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const accountsCreateBodyNameMax = 400

export const accountsCreateBodyExternalIdMax = 400

export const AccountsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(accountsCreateBodyNameMax).describe('Human-readable name of the account.'),
        external_id: zod
            .string()
            .max(accountsCreateBodyExternalIdMax)
            .nullish()
            .describe(
                "Identifier linking this account to its source customer — the analytics group key (the customer's organization id), used to match billing and external records. Optional."
            ),
        properties: zod
            .object({
                csm: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_executive: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_owner: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export const AccountsCustomPropertyValuesListParams = /* @__PURE__ */ zod.object({
    account_id: zod.string().describe('UUID of the parent account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AccountsCustomPropertyValuesCreateParams = /* @__PURE__ */ zod.object({
    account_id: zod.string().describe('UUID of the parent account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AccountsCustomPropertyValuesCreateBody = /* @__PURE__ */ zod.object({
    definition: zod.string().describe('UUID of the custom property definition whose value to set for this account.'),
    value: zod
        .union([zod.string(), zod.number(), zod.boolean()])
        .describe(
            "Value to store, matching the definition's type: a number for number/currency/percent, a boolean for boolean, an ISO-8601 string for date/datetime, or text for text properties."
        ),
})

export const AccountsNotebooksListParams = /* @__PURE__ */ zod.object({
    account_id: zod.string().describe('UUID of the parent account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AccountsNotebooksListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod.string().optional().describe("Sort by creation date or author. Defaults to '-created_at'."),
    search: zod.string().optional().describe('Full-text search across notebook title and content.'),
})

export const AccountsNotebooksCreateParams = /* @__PURE__ */ zod.object({
    account_id: zod.string().describe('UUID of the parent account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const accountsNotebooksCreateBodyTitleMax = 256

export const AccountsNotebooksCreateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(accountsNotebooksCreateBodyTitleMax)
        .nullish()
        .describe('Human-readable title of the account notebook.'),
    content: zod.unknown().optional().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
})

export const AccountsNotebooksRetrieveParams = /* @__PURE__ */ zod.object({
    account_id: zod.string().describe('UUID of the parent account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

export const AccountsNotebooksDestroyParams = /* @__PURE__ */ zod.object({
    account_id: zod.string().describe('UUID of the parent account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

export const AccountsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AccountsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const accountsPartialUpdateBodyNameMax = 400

export const accountsPartialUpdateBodyExternalIdMax = 400

export const AccountsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(accountsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable name of the account.'),
        external_id: zod
            .string()
            .max(accountsPartialUpdateBodyExternalIdMax)
            .nullish()
            .describe(
                "Identifier linking this account to its source customer — the analytics group key (the customer's organization id), used to match billing and external records. Optional."
            ),
        properties: zod
            .object({
                csm: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_executive: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_owner: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export const AccountsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this account.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CustomPropertyDefinitionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CustomPropertyDefinitionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const CustomPropertyDefinitionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const customPropertyDefinitionsCreateBodyNameMax = 400

export const customPropertyDefinitionsCreateBodyIsBigNumberDefault = false

export const CustomPropertyDefinitionsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(customPropertyDefinitionsCreateBodyNameMax)
            .describe('Human-readable name of the custom property. Unique within the team.'),
        description: zod.string().nullish().describe('Optional description of what the property represents.'),
        display_type: zod
            .enum(['text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean'])
            .describe(
                '* `text` - text\n* `number` - number\n* `currency` - currency\n* `percent` - percent\n* `date` - date\n* `datetime` - datetime\n* `boolean` - boolean'
            )
            .describe(
                "How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', or 'boolean'.\n\n* `text` - text\n* `number` - number\n* `currency` - currency\n* `percent` - percent\n* `date` - date\n* `datetime` - datetime\n* `boolean` - boolean"
            ),
        is_big_number: zod
            .boolean()
            .default(customPropertyDefinitionsCreateBodyIsBigNumberDefault)
            .describe('Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.'),
    })
    .describe(
        "A team-scoped definition of a custom account property — the attribute side of the model.\n\nHolds only the property's shape (name, display type, big-number flag). Per-account values are\nstored separately, so this serializer never reads or writes account values."
    )

export const CustomPropertyDefinitionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CustomPropertyDefinitionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const customPropertyDefinitionsPartialUpdateBodyNameMax = 400

export const CustomPropertyDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(customPropertyDefinitionsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable name of the custom property. Unique within the team.'),
        description: zod.string().nullish().describe('Optional description of what the property represents.'),
        display_type: zod
            .enum(['text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean'])
            .describe(
                '* `text` - text\n* `number` - number\n* `currency` - currency\n* `percent` - percent\n* `date` - date\n* `datetime` - datetime\n* `boolean` - boolean'
            )
            .optional()
            .describe(
                "How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', or 'boolean'.\n\n* `text` - text\n* `number` - number\n* `currency` - currency\n* `percent` - percent\n* `date` - date\n* `datetime` - datetime\n* `boolean` - boolean"
            ),
        is_big_number: zod
            .boolean()
            .optional()
            .describe('Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.'),
    })
    .describe(
        "A team-scoped definition of a custom account property — the attribute side of the model.\n\nHolds only the property's shape (name, display type, big-number flag). Per-account values are\nstored separately, so this serializer never reads or writes account values."
    )

export const CustomPropertyDefinitionsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const groupsTypesMetricsListPathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsListPathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsListParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsListPathGroupTypeIndexMin)
        .max(groupsTypesMetricsListPathGroupTypeIndexMax),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const GroupsTypesMetricsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const groupsTypesMetricsCreatePathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsCreatePathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsCreateParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsCreatePathGroupTypeIndexMin)
        .max(groupsTypesMetricsCreatePathGroupTypeIndexMax),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const groupsTypesMetricsCreateBodyNameMax = 255

export const groupsTypesMetricsCreateBodyFormatDefault = `numeric`
export const groupsTypesMetricsCreateBodyIntervalDefault = 7
export const groupsTypesMetricsCreateBodyDisplayDefault = `number`
export const groupsTypesMetricsCreateBodyMathDefault = `count`
export const groupsTypesMetricsCreateBodyMathPropertyMax = 255

export const GroupsTypesMetricsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(groupsTypesMetricsCreateBodyNameMax)
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: zod
        .enum(['numeric', 'currency'])
        .describe('* `numeric` - numeric\n* `currency` - currency')
        .default(groupsTypesMetricsCreateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n* `numeric` - numeric\n* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsCreateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('* `number` - number\n* `sparkline` - sparkline')
        .default(groupsTypesMetricsCreateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n* `number` - number\n* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.\n\n**Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n**Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('* `count` - count\n* `sum` - sum')
        .default(groupsTypesMetricsCreateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n* `count` - count\n* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsCreateBodyMathPropertyMax)
        .nullish()
        .describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
})

export const groupsTypesMetricsRetrievePathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsRetrievePathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsRetrieveParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsRetrievePathGroupTypeIndexMin)
        .max(groupsTypesMetricsRetrievePathGroupTypeIndexMax),
    id: zod.string().describe('A UUID string identifying this group usage metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const groupsTypesMetricsPartialUpdatePathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsPartialUpdatePathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsPartialUpdateParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsPartialUpdatePathGroupTypeIndexMin)
        .max(groupsTypesMetricsPartialUpdatePathGroupTypeIndexMax),
    id: zod.string().describe('A UUID string identifying this group usage metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const groupsTypesMetricsPartialUpdateBodyNameMax = 255

export const groupsTypesMetricsPartialUpdateBodyMathPropertyMax = 255

export const GroupsTypesMetricsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(groupsTypesMetricsPartialUpdateBodyNameMax)
        .optional()
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: zod
        .enum(['numeric', 'currency'])
        .describe('* `numeric` - numeric\n* `currency` - currency')
        .optional()
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n* `numeric` - numeric\n* `currency` - currency'
        ),
    interval: zod
        .number()
        .optional()
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('* `number` - number\n* `sparkline` - sparkline')
        .optional()
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n* `number` - number\n* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.\n\n**Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n**Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('* `count` - count\n* `sum` - sum')
        .optional()
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n* `count` - count\n* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsPartialUpdateBodyMathPropertyMax)
        .nullish()
        .describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
})

export const groupsTypesMetricsDestroyPathGroupTypeIndexMin = -2147483648
export const groupsTypesMetricsDestroyPathGroupTypeIndexMax = 2147483647

export const GroupsTypesMetricsDestroyParams = /* @__PURE__ */ zod.object({
    group_type_index: zod
        .number()
        .min(groupsTypesMetricsDestroyPathGroupTypeIndexMin)
        .max(groupsTypesMetricsDestroyPathGroupTypeIndexMax),
    id: zod.string().describe('A UUID string identifying this group usage metric.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
