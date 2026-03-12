/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 28 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsListParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
})

export const EnvironmentsHogFunctionsListQueryParams = zod.object({
    created_at: zod.string().datetime({}).optional(),
    created_by: zod.number().optional(),
    enabled: zod.boolean().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
    type: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    updated_at: zod.string().datetime({}).optional(),
})

export const environmentsHogFunctionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const environmentsHogFunctionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const environmentsHogFunctionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const environmentsHogFunctionsListResponseResultsItemCreatedByOneEmailMax = 254

export const environmentsHogFunctionsListResponseResultsItemTemplateOneNameMax = 400

export const environmentsHogFunctionsListResponseResultsItemTemplateOneCodeLanguageMax = 20

export const environmentsHogFunctionsListResponseResultsItemTemplateOneTypeMax = 50

export const environmentsHogFunctionsListResponseResultsItemTemplateOneStatusMax = 20

export const EnvironmentsHogFunctionsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().optional(),
            type: zod.string().nullish(),
            name: zod.string().nullish(),
            description: zod.string().optional(),
            created_at: zod.string().datetime({}).optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(environmentsHogFunctionsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(environmentsHogFunctionsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(environmentsHogFunctionsListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod
                        .string()
                        .email()
                        .max(environmentsHogFunctionsListResponseResultsItemCreatedByOneEmailMax),
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
            updated_at: zod.string().datetime({}).optional(),
            enabled: zod.boolean().optional(),
            hog: zod.string().optional(),
            filters: zod.unknown().nullish(),
            icon_url: zod.string().nullish(),
            template: zod
                .object({
                    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                    name: zod
                        .string()
                        .max(environmentsHogFunctionsListResponseResultsItemTemplateOneNameMax)
                        .describe('Display name of the template.'),
                    description: zod.string().nullish().describe('What this template does.'),
                    code: zod.string().describe('Source code of the template.'),
                    code_language: zod
                        .string()
                        .max(environmentsHogFunctionsListResponseResultsItemTemplateOneCodeLanguageMax)
                        .optional()
                        .describe("Programming language: 'hog' or 'javascript'."),
                    inputs_schema: zod
                        .unknown()
                        .describe('Schema defining configurable inputs for functions created from this template.'),
                    type: zod
                        .string()
                        .max(environmentsHogFunctionsListResponseResultsItemTemplateOneTypeMax)
                        .describe('Function type this template creates.'),
                    status: zod
                        .string()
                        .max(environmentsHogFunctionsListResponseResultsItemTemplateOneStatusMax)
                        .optional()
                        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                    free: zod.boolean().optional().describe('Whether available on free plans.'),
                    icon_url: zod.string().nullish().describe("URL for the template's icon."),
                    filters: zod.unknown().nullish().describe('Default event filters.'),
                    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                    mapping_templates: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Name of this mapping template.'),
                                include_by_default: zod
                                    .boolean()
                                    .nullish()
                                    .describe('Whether this mapping is enabled by default.'),
                                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                                inputs_schema: zod
                                    .unknown()
                                    .nullish()
                                    .describe('Additional input schema fields specific to this mapping.'),
                            })
                        )
                        .nullish()
                        .describe('Pre-defined mapping configurations for destination templates.'),
                })
                .optional(),
            status: zod
                .object({
                    state: zod
                        .union([
                            zod.literal(0),
                            zod.literal(1),
                            zod.literal(2),
                            zod.literal(3),
                            zod.literal(11),
                            zod.literal(12),
                        ])
                        .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
                    tokens: zod.number(),
                })
                .nullish(),
            execution_order: zod.number().nullish(),
        })
    ),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsCreateParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
})

export const environmentsHogFunctionsCreateBodyNameMax = 400

export const environmentsHogFunctionsCreateBodyInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsCreateBodyInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsCreateBodyInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsCreateBodyFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsCreateBodyMaskingOneTtlMin = 60
export const environmentsHogFunctionsCreateBodyMaskingOneTtlMax = 86400

export const environmentsHogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsCreateBodyMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsCreateBodyTemplateIdMax = 400

export const environmentsHogFunctionsCreateBodyExecutionOrderMin = 0
export const environmentsHogFunctionsCreateBodyExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsCreateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsCreateBodyNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(environmentsHogFunctionsCreateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(environmentsHogFunctionsCreateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(environmentsHogFunctionsCreateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsCreateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsCreateBodyMaskingOneTtlMin)
                .max(environmentsHogFunctionsCreateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(environmentsHogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(environmentsHogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(environmentsHogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(environmentsHogFunctionsCreateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsCreateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsCreateBodyExecutionOrderMin)
        .max(environmentsHogFunctionsCreateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsRetrieveParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

export const environmentsHogFunctionsRetrieveResponseNameMax = 400

export const environmentsHogFunctionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const environmentsHogFunctionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const environmentsHogFunctionsRetrieveResponseCreatedByOneLastNameMax = 150

export const environmentsHogFunctionsRetrieveResponseCreatedByOneEmailMax = 254

export const environmentsHogFunctionsRetrieveResponseInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsRetrieveResponseInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsRetrieveResponseInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsRetrieveResponseFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsRetrieveResponseMaskingOneTtlMin = 60
export const environmentsHogFunctionsRetrieveResponseMaskingOneTtlMax = 86400

export const environmentsHogFunctionsRetrieveResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsRetrieveResponseMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsRetrieveResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsRetrieveResponseMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsRetrieveResponseTemplateOneNameMax = 400

export const environmentsHogFunctionsRetrieveResponseTemplateOneCodeLanguageMax = 20

export const environmentsHogFunctionsRetrieveResponseTemplateOneTypeMax = 50

export const environmentsHogFunctionsRetrieveResponseTemplateOneStatusMax = 20

export const environmentsHogFunctionsRetrieveResponseTemplateIdMax = 400

export const environmentsHogFunctionsRetrieveResponseExecutionOrderMin = 0
export const environmentsHogFunctionsRetrieveResponseExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsRetrieveResponse = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsRetrieveResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(environmentsHogFunctionsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(environmentsHogFunctionsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(environmentsHogFunctionsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(environmentsHogFunctionsRetrieveResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod
                    .boolean()
                    .default(environmentsHogFunctionsRetrieveResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(environmentsHogFunctionsRetrieveResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(environmentsHogFunctionsRetrieveResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsRetrieveResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsRetrieveResponseMaskingOneTtlMin)
                .max(environmentsHogFunctionsRetrieveResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsRetrieveResponseMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsRetrieveResponseMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsRetrieveResponseMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(environmentsHogFunctionsRetrieveResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(environmentsHogFunctionsRetrieveResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(environmentsHogFunctionsRetrieveResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(environmentsHogFunctionsRetrieveResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(environmentsHogFunctionsRetrieveResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsRetrieveResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsRetrieveResponseExecutionOrderMin)
        .max(environmentsHogFunctionsRetrieveResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsUpdateParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

export const environmentsHogFunctionsUpdateBodyNameMax = 400

export const environmentsHogFunctionsUpdateBodyInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsUpdateBodyInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsUpdateBodyInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsUpdateBodyFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsUpdateBodyMaskingOneTtlMin = 60
export const environmentsHogFunctionsUpdateBodyMaskingOneTtlMax = 86400

export const environmentsHogFunctionsUpdateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsUpdateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsUpdateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsUpdateBodyMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsUpdateBodyTemplateIdMax = 400

export const environmentsHogFunctionsUpdateBodyExecutionOrderMin = 0
export const environmentsHogFunctionsUpdateBodyExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsUpdateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsUpdateBodyNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(environmentsHogFunctionsUpdateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(environmentsHogFunctionsUpdateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(environmentsHogFunctionsUpdateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsUpdateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsUpdateBodyMaskingOneTtlMin)
                .max(environmentsHogFunctionsUpdateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(environmentsHogFunctionsUpdateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(environmentsHogFunctionsUpdateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(environmentsHogFunctionsUpdateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(environmentsHogFunctionsUpdateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsUpdateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsUpdateBodyExecutionOrderMin)
        .max(environmentsHogFunctionsUpdateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const environmentsHogFunctionsUpdateResponseNameMax = 400

export const environmentsHogFunctionsUpdateResponseCreatedByOneDistinctIdMax = 200

export const environmentsHogFunctionsUpdateResponseCreatedByOneFirstNameMax = 150

export const environmentsHogFunctionsUpdateResponseCreatedByOneLastNameMax = 150

export const environmentsHogFunctionsUpdateResponseCreatedByOneEmailMax = 254

export const environmentsHogFunctionsUpdateResponseInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsUpdateResponseInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsUpdateResponseInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsUpdateResponseFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsUpdateResponseMaskingOneTtlMin = 60
export const environmentsHogFunctionsUpdateResponseMaskingOneTtlMax = 86400

export const environmentsHogFunctionsUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsUpdateResponseTemplateOneNameMax = 400

export const environmentsHogFunctionsUpdateResponseTemplateOneCodeLanguageMax = 20

export const environmentsHogFunctionsUpdateResponseTemplateOneTypeMax = 50

export const environmentsHogFunctionsUpdateResponseTemplateOneStatusMax = 20

export const environmentsHogFunctionsUpdateResponseTemplateIdMax = 400

export const environmentsHogFunctionsUpdateResponseExecutionOrderMin = 0
export const environmentsHogFunctionsUpdateResponseExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsUpdateResponse = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsUpdateResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(environmentsHogFunctionsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(environmentsHogFunctionsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(environmentsHogFunctionsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(environmentsHogFunctionsUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(environmentsHogFunctionsUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(environmentsHogFunctionsUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(environmentsHogFunctionsUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsUpdateResponseMaskingOneTtlMin)
                .max(environmentsHogFunctionsUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsUpdateResponseMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsUpdateResponseMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsUpdateResponseMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(environmentsHogFunctionsUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(environmentsHogFunctionsUpdateResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(environmentsHogFunctionsUpdateResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(environmentsHogFunctionsUpdateResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(environmentsHogFunctionsUpdateResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsUpdateResponseExecutionOrderMin)
        .max(environmentsHogFunctionsUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsPartialUpdateParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

export const environmentsHogFunctionsPartialUpdateBodyNameMax = 400

export const environmentsHogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsPartialUpdateBodyFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsPartialUpdateBodyMaskingOneTtlMin = 60
export const environmentsHogFunctionsPartialUpdateBodyMaskingOneTtlMax = 86400

export const environmentsHogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsPartialUpdateBodyTemplateIdMax = 400

export const environmentsHogFunctionsPartialUpdateBodyExecutionOrderMin = 0
export const environmentsHogFunctionsPartialUpdateBodyExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsPartialUpdateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsPartialUpdateBodyNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod
                    .boolean()
                    .default(environmentsHogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(environmentsHogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(environmentsHogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsPartialUpdateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsPartialUpdateBodyMaskingOneTtlMin)
                .max(environmentsHogFunctionsPartialUpdateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(environmentsHogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsPartialUpdateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsPartialUpdateBodyExecutionOrderMin)
        .max(environmentsHogFunctionsPartialUpdateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const environmentsHogFunctionsPartialUpdateResponseNameMax = 400

export const environmentsHogFunctionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const environmentsHogFunctionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const environmentsHogFunctionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const environmentsHogFunctionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const environmentsHogFunctionsPartialUpdateResponseInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsPartialUpdateResponseInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsPartialUpdateResponseInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsPartialUpdateResponseFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsPartialUpdateResponseMaskingOneTtlMin = 60
export const environmentsHogFunctionsPartialUpdateResponseMaskingOneTtlMax = 86400

export const environmentsHogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsPartialUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsPartialUpdateResponseTemplateOneNameMax = 400

export const environmentsHogFunctionsPartialUpdateResponseTemplateOneCodeLanguageMax = 20

export const environmentsHogFunctionsPartialUpdateResponseTemplateOneTypeMax = 50

export const environmentsHogFunctionsPartialUpdateResponseTemplateOneStatusMax = 20

export const environmentsHogFunctionsPartialUpdateResponseTemplateIdMax = 400

export const environmentsHogFunctionsPartialUpdateResponseExecutionOrderMin = 0
export const environmentsHogFunctionsPartialUpdateResponseExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsPartialUpdateResponse = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsPartialUpdateResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod
                .string()
                .max(environmentsHogFunctionsPartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(environmentsHogFunctionsPartialUpdateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(environmentsHogFunctionsPartialUpdateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.string().email().max(environmentsHogFunctionsPartialUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod
                    .boolean()
                    .default(environmentsHogFunctionsPartialUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod
                    .boolean()
                    .default(environmentsHogFunctionsPartialUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod
                    .boolean()
                    .default(environmentsHogFunctionsPartialUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsPartialUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsPartialUpdateResponseMaskingOneTtlMin)
                .max(environmentsHogFunctionsPartialUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(environmentsHogFunctionsPartialUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(environmentsHogFunctionsPartialUpdateResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(environmentsHogFunctionsPartialUpdateResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(environmentsHogFunctionsPartialUpdateResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(environmentsHogFunctionsPartialUpdateResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsPartialUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsPartialUpdateResponseExecutionOrderMin)
        .max(environmentsHogFunctionsPartialUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 * @deprecated
 */
export const EnvironmentsHogFunctionsDestroyParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsEnableBackfillsCreateParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

export const environmentsHogFunctionsEnableBackfillsCreateBodyNameMax = 400

export const environmentsHogFunctionsEnableBackfillsCreateBodyInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsEnableBackfillsCreateBodyInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsEnableBackfillsCreateBodyInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsEnableBackfillsCreateBodyFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMin = 60
export const environmentsHogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMax = 86400

export const environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsEnableBackfillsCreateBodyTemplateIdMax = 400

export const environmentsHogFunctionsEnableBackfillsCreateBodyExecutionOrderMin = 0
export const environmentsHogFunctionsEnableBackfillsCreateBodyExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsEnableBackfillsCreateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsEnableBackfillsCreateBodyNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod
                    .boolean()
                    .default(environmentsHogFunctionsEnableBackfillsCreateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod
                    .boolean()
                    .default(environmentsHogFunctionsEnableBackfillsCreateBodyInputsSchemaItemSecretDefault),
                hidden: zod
                    .boolean()
                    .default(environmentsHogFunctionsEnableBackfillsCreateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsEnableBackfillsCreateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMin)
                .max(environmentsHogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(environmentsHogFunctionsEnableBackfillsCreateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsEnableBackfillsCreateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsEnableBackfillsCreateBodyExecutionOrderMin)
        .max(environmentsHogFunctionsEnableBackfillsCreateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsInvocationsCreateParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneNameMax = 400

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax = 200

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax = 150

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax = 150

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax = 254

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMin = 60
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMax = 86400

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneNameMax = 400

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneCodeLanguageMax = 20

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneTypeMax = 50

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneStatusMax = 20

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateIdMax = 400

export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMin = 0
export const environmentsHogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMax = 32767

export const environmentsHogFunctionsInvocationsCreateBodyMockAsyncFunctionsDefault = true

export const EnvironmentsHogFunctionsInvocationsCreateBody = zod.object({
    configuration: zod
        .object({
            id: zod.string().optional(),
            type: zod
                .union([
                    zod
                        .enum([
                            'destination',
                            'site_destination',
                            'internal_destination',
                            'source_webhook',
                            'warehouse_source_webhook',
                            'site_app',
                            'transformation',
                        ])
                        .describe(
                            '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                        ),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            name: zod
                .string()
                .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneNameMax)
                .nullish()
                .describe('Display name for the function.'),
            description: zod.string().optional().describe('Human-readable description of what this function does.'),
            created_at: zod.string().datetime({}).optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax)
                        .optional(),
                    email: zod
                        .string()
                        .email()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax),
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
            updated_at: zod.string().datetime({}).optional(),
            enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
            hog: zod
                .string()
                .optional()
                .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
            inputs_schema: zod
                .array(
                    zod.object({
                        type: zod
                            .enum([
                                'string',
                                'number',
                                'boolean',
                                'dictionary',
                                'choice',
                                'json',
                                'integration',
                                'integration_field',
                                'email',
                                'native_email',
                                'posthog_assignee',
                                'posthog_ticket_tags',
                            ])
                            .describe(
                                '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                            ),
                        key: zod.string(),
                        label: zod.string().optional(),
                        choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        required: zod
                            .boolean()
                            .default(
                                environmentsHogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemRequiredDefault
                            ),
                        default: zod.unknown().optional(),
                        secret: zod
                            .boolean()
                            .default(
                                environmentsHogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemSecretDefault
                            ),
                        hidden: zod
                            .boolean()
                            .default(
                                environmentsHogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemHiddenDefault
                            ),
                        description: zod.string().optional(),
                        templating: zod
                            .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                            .optional()
                            .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                    })
                )
                .optional()
                .describe('Schema defining the configurable input parameters for this function.'),
            inputs: zod
                .record(
                    zod.string(),
                    zod.object({
                        value: zod.unknown().optional(),
                        templating: zod
                            .enum(['hog', 'liquid'])
                            .optional()
                            .describe('* `hog` - hog\n* `liquid` - liquid'),
                        bytecode: zod.array(zod.unknown()).optional(),
                        order: zod.number().optional(),
                        transpiled: zod.unknown().optional(),
                    })
                )
                .optional()
                .describe('Values for each input defined in inputs_schema.'),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    filter_test_accounts: zod.boolean().optional(),
                })
                .optional()
                .describe('Event filters that control which events trigger this function.'),
            masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMin)
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMax)
                        .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                    threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                    hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                    bytecode: zod
                        .unknown()
                        .nullish()
                        .describe('Compiled bytecode for the hash expression. Auto-generated.'),
                })
                .nullish()
                .describe('PII masking configuration with TTL, threshold, and hash expression.'),
            mappings: zod
                .array(
                    zod.object({
                        name: zod.string().optional(),
                        inputs_schema: zod
                            .array(
                                zod.object({
                                    type: zod
                                        .enum([
                                            'string',
                                            'number',
                                            'boolean',
                                            'dictionary',
                                            'choice',
                                            'json',
                                            'integration',
                                            'integration_field',
                                            'email',
                                            'native_email',
                                            'posthog_assignee',
                                            'posthog_ticket_tags',
                                        ])
                                        .describe(
                                            '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                        ),
                                    key: zod.string(),
                                    label: zod.string().optional(),
                                    choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    required: zod
                                        .boolean()
                                        .default(
                                            environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemRequiredDefault
                                        ),
                                    default: zod.unknown().optional(),
                                    secret: zod
                                        .boolean()
                                        .default(
                                            environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemSecretDefault
                                        ),
                                    hidden: zod
                                        .boolean()
                                        .default(
                                            environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemHiddenDefault
                                        ),
                                    description: zod.string().optional(),
                                    templating: zod
                                        .union([
                                            zod.literal(true),
                                            zod.literal(false),
                                            zod.literal('hog'),
                                            zod.literal('liquid'),
                                        ])
                                        .optional()
                                        .describe(
                                            '* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'
                                        ),
                                })
                            )
                            .optional(),
                        inputs: zod
                            .record(
                                zod.string(),
                                zod.object({
                                    value: zod.unknown().optional(),
                                    templating: zod
                                        .enum(['hog', 'liquid'])
                                        .optional()
                                        .describe('* `hog` - hog\n* `liquid` - liquid'),
                                    bytecode: zod.array(zod.unknown()).optional(),
                                    order: zod.number().optional(),
                                    transpiled: zod.unknown().optional(),
                                })
                            )
                            .optional(),
                        filters: zod
                            .object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(
                                        environmentsHogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemFiltersSourceDefault
                                    ),
                                actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                filter_test_accounts: zod.boolean().optional(),
                            })
                            .optional(),
                    })
                )
                .nullish()
                .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
            icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
            template: zod
                .object({
                    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                    name: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneNameMax)
                        .describe('Display name of the template.'),
                    description: zod.string().nullish().describe('What this template does.'),
                    code: zod.string().describe('Source code of the template.'),
                    code_language: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneCodeLanguageMax)
                        .optional()
                        .describe("Programming language: 'hog' or 'javascript'."),
                    inputs_schema: zod
                        .unknown()
                        .describe('Schema defining configurable inputs for functions created from this template.'),
                    type: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneTypeMax)
                        .describe('Function type this template creates.'),
                    status: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneStatusMax)
                        .optional()
                        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                    free: zod.boolean().optional().describe('Whether available on free plans.'),
                    icon_url: zod.string().nullish().describe("URL for the template's icon."),
                    filters: zod.unknown().nullish().describe('Default event filters.'),
                    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                    mapping_templates: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Name of this mapping template.'),
                                include_by_default: zod
                                    .boolean()
                                    .nullish()
                                    .describe('Whether this mapping is enabled by default.'),
                                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                                inputs_schema: zod
                                    .unknown()
                                    .nullish()
                                    .describe('Additional input schema fields specific to this mapping.'),
                            })
                        )
                        .nullish()
                        .describe('Pre-defined mapping configurations for destination templates.'),
                })
                .optional(),
            template_id: zod
                .string()
                .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneTemplateIdMax)
                .nullish()
                .describe('ID of the template to create this function from.'),
            execution_order: zod
                .number()
                .min(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMin)
                .max(environmentsHogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMax)
                .nullish()
                .describe('Execution priority for transformations. Lower values run first.'),
        })
        .describe('Full function configuration to test.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock global variables available during test invocation.'),
    clickhouse_event: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock ClickHouse event data to test the function with.'),
    mock_async_functions: zod
        .boolean()
        .default(environmentsHogFunctionsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe('When true (default), async functions like fetch() are simulated.'),
    invocation_id: zod.string().nullish().describe('Optional invocation ID for correlation.'),
})

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneNameMax = 400

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneDistinctIdMax = 200

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneFirstNameMax = 150

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneLastNameMax = 150

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneEmailMax = 254

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMin = 60
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMax = 86400

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneNameMax = 400

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneCodeLanguageMax = 20

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneTypeMax = 50

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneStatusMax = 20

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateIdMax = 400

export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMin = 0
export const environmentsHogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMax = 32767

export const environmentsHogFunctionsInvocationsCreateResponseMockAsyncFunctionsDefault = true

export const EnvironmentsHogFunctionsInvocationsCreateResponse = zod.object({
    configuration: zod
        .object({
            id: zod.string().optional(),
            type: zod
                .union([
                    zod
                        .enum([
                            'destination',
                            'site_destination',
                            'internal_destination',
                            'source_webhook',
                            'warehouse_source_webhook',
                            'site_app',
                            'transformation',
                        ])
                        .describe(
                            '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                        ),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            name: zod
                .string()
                .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneNameMax)
                .nullish()
                .describe('Display name for the function.'),
            description: zod.string().optional().describe('Human-readable description of what this function does.'),
            created_at: zod.string().datetime({}).optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneLastNameMax)
                        .optional(),
                    email: zod
                        .string()
                        .email()
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneEmailMax),
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
            updated_at: zod.string().datetime({}).optional(),
            enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
            hog: zod
                .string()
                .optional()
                .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
            inputs_schema: zod
                .array(
                    zod.object({
                        type: zod
                            .enum([
                                'string',
                                'number',
                                'boolean',
                                'dictionary',
                                'choice',
                                'json',
                                'integration',
                                'integration_field',
                                'email',
                                'native_email',
                                'posthog_assignee',
                                'posthog_ticket_tags',
                            ])
                            .describe(
                                '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                            ),
                        key: zod.string(),
                        label: zod.string().optional(),
                        choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        required: zod
                            .boolean()
                            .default(
                                environmentsHogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemRequiredDefault
                            ),
                        default: zod.unknown().optional(),
                        secret: zod
                            .boolean()
                            .default(
                                environmentsHogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemSecretDefault
                            ),
                        hidden: zod
                            .boolean()
                            .default(
                                environmentsHogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemHiddenDefault
                            ),
                        description: zod.string().optional(),
                        templating: zod
                            .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                            .optional()
                            .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                    })
                )
                .optional()
                .describe('Schema defining the configurable input parameters for this function.'),
            inputs: zod
                .record(
                    zod.string(),
                    zod.object({
                        value: zod.unknown().optional(),
                        templating: zod
                            .enum(['hog', 'liquid'])
                            .optional()
                            .describe('* `hog` - hog\n* `liquid` - liquid'),
                        bytecode: zod.array(zod.unknown()).optional(),
                        order: zod.number().optional(),
                        transpiled: zod.unknown().optional(),
                    })
                )
                .optional()
                .describe('Values for each input defined in inputs_schema.'),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(
                            environmentsHogFunctionsInvocationsCreateResponseConfigurationOneFiltersOneSourceDefault
                        ),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    filter_test_accounts: zod.boolean().optional(),
                })
                .optional()
                .describe('Event filters that control which events trigger this function.'),
            masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMin)
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMax)
                        .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                    threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                    hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                    bytecode: zod
                        .unknown()
                        .nullish()
                        .describe('Compiled bytecode for the hash expression. Auto-generated.'),
                })
                .nullish()
                .describe('PII masking configuration with TTL, threshold, and hash expression.'),
            mappings: zod
                .array(
                    zod.object({
                        name: zod.string().optional(),
                        inputs_schema: zod
                            .array(
                                zod.object({
                                    type: zod
                                        .enum([
                                            'string',
                                            'number',
                                            'boolean',
                                            'dictionary',
                                            'choice',
                                            'json',
                                            'integration',
                                            'integration_field',
                                            'email',
                                            'native_email',
                                            'posthog_assignee',
                                            'posthog_ticket_tags',
                                        ])
                                        .describe(
                                            '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                        ),
                                    key: zod.string(),
                                    label: zod.string().optional(),
                                    choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    required: zod
                                        .boolean()
                                        .default(
                                            environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemRequiredDefault
                                        ),
                                    default: zod.unknown().optional(),
                                    secret: zod
                                        .boolean()
                                        .default(
                                            environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemSecretDefault
                                        ),
                                    hidden: zod
                                        .boolean()
                                        .default(
                                            environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemHiddenDefault
                                        ),
                                    description: zod.string().optional(),
                                    templating: zod
                                        .union([
                                            zod.literal(true),
                                            zod.literal(false),
                                            zod.literal('hog'),
                                            zod.literal('liquid'),
                                        ])
                                        .optional()
                                        .describe(
                                            '* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'
                                        ),
                                })
                            )
                            .optional(),
                        inputs: zod
                            .record(
                                zod.string(),
                                zod.object({
                                    value: zod.unknown().optional(),
                                    templating: zod
                                        .enum(['hog', 'liquid'])
                                        .optional()
                                        .describe('* `hog` - hog\n* `liquid` - liquid'),
                                    bytecode: zod.array(zod.unknown()).optional(),
                                    order: zod.number().optional(),
                                    transpiled: zod.unknown().optional(),
                                })
                            )
                            .optional(),
                        filters: zod
                            .object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(
                                        environmentsHogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemFiltersSourceDefault
                                    ),
                                actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                filter_test_accounts: zod.boolean().optional(),
                            })
                            .optional(),
                    })
                )
                .nullish()
                .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
            icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
            template: zod
                .object({
                    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                    name: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneNameMax)
                        .describe('Display name of the template.'),
                    description: zod.string().nullish().describe('What this template does.'),
                    code: zod.string().describe('Source code of the template.'),
                    code_language: zod
                        .string()
                        .max(
                            environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneCodeLanguageMax
                        )
                        .optional()
                        .describe("Programming language: 'hog' or 'javascript'."),
                    inputs_schema: zod
                        .unknown()
                        .describe('Schema defining configurable inputs for functions created from this template.'),
                    type: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneTypeMax)
                        .describe('Function type this template creates.'),
                    status: zod
                        .string()
                        .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneStatusMax)
                        .optional()
                        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                    free: zod.boolean().optional().describe('Whether available on free plans.'),
                    icon_url: zod.string().nullish().describe("URL for the template's icon."),
                    filters: zod.unknown().nullish().describe('Default event filters.'),
                    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                    mapping_templates: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Name of this mapping template.'),
                                include_by_default: zod
                                    .boolean()
                                    .nullish()
                                    .describe('Whether this mapping is enabled by default.'),
                                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                                inputs_schema: zod
                                    .unknown()
                                    .nullish()
                                    .describe('Additional input schema fields specific to this mapping.'),
                            })
                        )
                        .nullish()
                        .describe('Pre-defined mapping configurations for destination templates.'),
                })
                .optional(),
            template_id: zod
                .string()
                .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneTemplateIdMax)
                .nullish()
                .describe('ID of the template to create this function from.'),
            execution_order: zod
                .number()
                .min(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMin)
                .max(environmentsHogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMax)
                .nullish()
                .describe('Execution priority for transformations. Lower values run first.'),
        })
        .describe('Full function configuration to test.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock global variables available during test invocation.'),
    clickhouse_event: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock ClickHouse event data to test the function with.'),
    mock_async_functions: zod
        .boolean()
        .default(environmentsHogFunctionsInvocationsCreateResponseMockAsyncFunctionsDefault)
        .describe('When true (default), async functions like fetch() are simulated.'),
    status: zod.string().optional().describe('Invocation result status.'),
    logs: zod.array(zod.unknown()).optional().describe('Execution logs from the test invocation.'),
    invocation_id: zod.string().nullish().describe('Optional invocation ID for correlation.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsLogsRetrieveParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsMetricsRetrieveParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsMetricsTotalsRetrieveParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
    id: zod.string().describe('A UUID string identifying this hog function.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsIconRetrieveParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
})

/**
 * @deprecated
 */
export const EnvironmentsHogFunctionsIconsRetrieveParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
})

/**
 * Update the execution order of multiple HogFunctions.
 * @deprecated
 */
export const EnvironmentsHogFunctionsRearrangePartialUpdateParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
})

export const EnvironmentsHogFunctionsRearrangePartialUpdateBody = zod.object({
    orders: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe('Map of hog function UUIDs to their new execution_order values.'),
})

export const environmentsHogFunctionsRearrangePartialUpdateResponseNameMax = 400

export const environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneFirstNameMax = 150

export const environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneLastNameMax = 150

export const environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneEmailMax = 254

export const environmentsHogFunctionsRearrangePartialUpdateResponseInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsRearrangePartialUpdateResponseInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsRearrangePartialUpdateResponseInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsRearrangePartialUpdateResponseFiltersOneSourceDefault = `events`
export const environmentsHogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMin = 60
export const environmentsHogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMax = 86400

export const environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneNameMax = 400

export const environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneCodeLanguageMax = 20

export const environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneTypeMax = 50

export const environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneStatusMax = 20

export const environmentsHogFunctionsRearrangePartialUpdateResponseTemplateIdMax = 400

export const environmentsHogFunctionsRearrangePartialUpdateResponseExecutionOrderMin = 0
export const environmentsHogFunctionsRearrangePartialUpdateResponseExecutionOrderMax = 32767

export const EnvironmentsHogFunctionsRearrangePartialUpdateResponseItem = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(environmentsHogFunctionsRearrangePartialUpdateResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod
                .string()
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.string().email().max(environmentsHogFunctionsRearrangePartialUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod
                    .boolean()
                    .default(environmentsHogFunctionsRearrangePartialUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod
                    .boolean()
                    .default(environmentsHogFunctionsRearrangePartialUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod
                    .boolean()
                    .default(environmentsHogFunctionsRearrangePartialUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(environmentsHogFunctionsRearrangePartialUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(environmentsHogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMin)
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(
                                environmentsHogFunctionsRearrangePartialUpdateResponseMappingsItemFiltersSourceDefault
                            ),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(environmentsHogFunctionsRearrangePartialUpdateResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(environmentsHogFunctionsRearrangePartialUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(environmentsHogFunctionsRearrangePartialUpdateResponseExecutionOrderMin)
        .max(environmentsHogFunctionsRearrangePartialUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})
export const EnvironmentsHogFunctionsRearrangePartialUpdateResponse = zod.array(
    EnvironmentsHogFunctionsRearrangePartialUpdateResponseItem
)

export const HogFunctionsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsListQueryParams = zod.object({
    created_at: zod.string().datetime({}).optional(),
    created_by: zod.number().optional(),
    enabled: zod.boolean().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
    type: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    updated_at: zod.string().datetime({}).optional(),
})

export const hogFunctionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const hogFunctionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const hogFunctionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const hogFunctionsListResponseResultsItemCreatedByOneEmailMax = 254

export const hogFunctionsListResponseResultsItemTemplateOneNameMax = 400

export const hogFunctionsListResponseResultsItemTemplateOneCodeLanguageMax = 20

export const hogFunctionsListResponseResultsItemTemplateOneTypeMax = 50

export const hogFunctionsListResponseResultsItemTemplateOneStatusMax = 20

export const HogFunctionsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().optional(),
            type: zod.string().nullish(),
            name: zod.string().nullish(),
            description: zod.string().optional(),
            created_at: zod.string().datetime({}).optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(hogFunctionsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(hogFunctionsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod.string().max(hogFunctionsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.string().email().max(hogFunctionsListResponseResultsItemCreatedByOneEmailMax),
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
            updated_at: zod.string().datetime({}).optional(),
            enabled: zod.boolean().optional(),
            hog: zod.string().optional(),
            filters: zod.unknown().nullish(),
            icon_url: zod.string().nullish(),
            template: zod
                .object({
                    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                    name: zod
                        .string()
                        .max(hogFunctionsListResponseResultsItemTemplateOneNameMax)
                        .describe('Display name of the template.'),
                    description: zod.string().nullish().describe('What this template does.'),
                    code: zod.string().describe('Source code of the template.'),
                    code_language: zod
                        .string()
                        .max(hogFunctionsListResponseResultsItemTemplateOneCodeLanguageMax)
                        .optional()
                        .describe("Programming language: 'hog' or 'javascript'."),
                    inputs_schema: zod
                        .unknown()
                        .describe('Schema defining configurable inputs for functions created from this template.'),
                    type: zod
                        .string()
                        .max(hogFunctionsListResponseResultsItemTemplateOneTypeMax)
                        .describe('Function type this template creates.'),
                    status: zod
                        .string()
                        .max(hogFunctionsListResponseResultsItemTemplateOneStatusMax)
                        .optional()
                        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                    free: zod.boolean().optional().describe('Whether available on free plans.'),
                    icon_url: zod.string().nullish().describe("URL for the template's icon."),
                    filters: zod.unknown().nullish().describe('Default event filters.'),
                    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                    mapping_templates: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Name of this mapping template.'),
                                include_by_default: zod
                                    .boolean()
                                    .nullish()
                                    .describe('Whether this mapping is enabled by default.'),
                                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                                inputs_schema: zod
                                    .unknown()
                                    .nullish()
                                    .describe('Additional input schema fields specific to this mapping.'),
                            })
                        )
                        .nullish()
                        .describe('Pre-defined mapping configurations for destination templates.'),
                })
                .optional(),
            status: zod
                .object({
                    state: zod
                        .union([
                            zod.literal(0),
                            zod.literal(1),
                            zod.literal(2),
                            zod.literal(3),
                            zod.literal(11),
                            zod.literal(12),
                        ])
                        .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
                    tokens: zod.number(),
                })
                .nullish(),
            execution_order: zod.number().nullish(),
        })
    ),
})

export const HogFunctionsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsCreateBodyNameMax = 400

export const hogFunctionsCreateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsCreateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsCreateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsCreateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsCreateBodyMaskingOneTtlMin = 60
export const hogFunctionsCreateBodyMaskingOneTtlMax = 86400

export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsCreateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsCreateBodyTemplateIdMax = 400

export const hogFunctionsCreateBodyExecutionOrderMin = 0
export const hogFunctionsCreateBodyExecutionOrderMax = 32767

export const HogFunctionsCreateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsCreateBodyNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsCreateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsCreateBodyMaskingOneTtlMin)
                .max(hogFunctionsCreateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsCreateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsCreateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsCreateBodyExecutionOrderMin)
        .max(hogFunctionsCreateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const HogFunctionsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsRetrieveResponseNameMax = 400

export const hogFunctionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsRetrieveResponseCreatedByOneLastNameMax = 150

export const hogFunctionsRetrieveResponseCreatedByOneEmailMax = 254

export const hogFunctionsRetrieveResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsRetrieveResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsRetrieveResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsRetrieveResponseFiltersOneSourceDefault = `events`
export const hogFunctionsRetrieveResponseMaskingOneTtlMin = 60
export const hogFunctionsRetrieveResponseMaskingOneTtlMax = 86400

export const hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsRetrieveResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsRetrieveResponseTemplateOneNameMax = 400

export const hogFunctionsRetrieveResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsRetrieveResponseTemplateOneTypeMax = 50

export const hogFunctionsRetrieveResponseTemplateOneStatusMax = 20

export const hogFunctionsRetrieveResponseTemplateIdMax = 400

export const hogFunctionsRetrieveResponseExecutionOrderMin = 0
export const hogFunctionsRetrieveResponseExecutionOrderMax = 32767

export const HogFunctionsRetrieveResponse = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsRetrieveResponseNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFunctionsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFunctionsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFunctionsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFunctionsRetrieveResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsRetrieveResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsRetrieveResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsRetrieveResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsRetrieveResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsRetrieveResponseMaskingOneTtlMin)
                .max(hogFunctionsRetrieveResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsRetrieveResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(hogFunctionsRetrieveResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(hogFunctionsRetrieveResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(hogFunctionsRetrieveResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(hogFunctionsRetrieveResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(hogFunctionsRetrieveResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsRetrieveResponseExecutionOrderMin)
        .max(hogFunctionsRetrieveResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const HogFunctionsUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsUpdateBodyNameMax = 400

export const hogFunctionsUpdateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsUpdateBodyMaskingOneTtlMin = 60
export const hogFunctionsUpdateBodyMaskingOneTtlMax = 86400

export const hogFunctionsUpdateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsUpdateBodyTemplateIdMax = 400

export const hogFunctionsUpdateBodyExecutionOrderMin = 0
export const hogFunctionsUpdateBodyExecutionOrderMax = 32767

export const HogFunctionsUpdateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsUpdateBodyNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsUpdateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsUpdateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsUpdateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsUpdateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsUpdateBodyMaskingOneTtlMin)
                .max(hogFunctionsUpdateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsUpdateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsUpdateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsUpdateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsUpdateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsUpdateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsUpdateBodyExecutionOrderMin)
        .max(hogFunctionsUpdateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const hogFunctionsUpdateResponseNameMax = 400

export const hogFunctionsUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsUpdateResponseCreatedByOneLastNameMax = 150

export const hogFunctionsUpdateResponseCreatedByOneEmailMax = 254

export const hogFunctionsUpdateResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateResponseFiltersOneSourceDefault = `events`
export const hogFunctionsUpdateResponseMaskingOneTtlMin = 60
export const hogFunctionsUpdateResponseMaskingOneTtlMax = 86400

export const hogFunctionsUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsUpdateResponseTemplateOneNameMax = 400

export const hogFunctionsUpdateResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsUpdateResponseTemplateOneTypeMax = 50

export const hogFunctionsUpdateResponseTemplateOneStatusMax = 20

export const hogFunctionsUpdateResponseTemplateIdMax = 400

export const hogFunctionsUpdateResponseExecutionOrderMin = 0
export const hogFunctionsUpdateResponseExecutionOrderMax = 32767

export const HogFunctionsUpdateResponse = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsUpdateResponseNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFunctionsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFunctionsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFunctionsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFunctionsUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsUpdateResponseMaskingOneTtlMin)
                .max(hogFunctionsUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsUpdateResponseMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsUpdateResponseMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsUpdateResponseMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(hogFunctionsUpdateResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(hogFunctionsUpdateResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(hogFunctionsUpdateResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(hogFunctionsUpdateResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(hogFunctionsUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsUpdateResponseExecutionOrderMin)
        .max(hogFunctionsUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const HogFunctionsPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsPartialUpdateBodyNameMax = 400

export const hogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsPartialUpdateBodyMaskingOneTtlMin = 60
export const hogFunctionsPartialUpdateBodyMaskingOneTtlMax = 86400

export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsPartialUpdateBodyTemplateIdMax = 400

export const hogFunctionsPartialUpdateBodyExecutionOrderMin = 0
export const hogFunctionsPartialUpdateBodyExecutionOrderMax = 32767

export const HogFunctionsPartialUpdateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsPartialUpdateBodyNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsPartialUpdateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsPartialUpdateBodyMaskingOneTtlMin)
                .max(hogFunctionsPartialUpdateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsPartialUpdateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsPartialUpdateBodyExecutionOrderMin)
        .max(hogFunctionsPartialUpdateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const hogFunctionsPartialUpdateResponseNameMax = 400

export const hogFunctionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const hogFunctionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const hogFunctionsPartialUpdateResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateResponseFiltersOneSourceDefault = `events`
export const hogFunctionsPartialUpdateResponseMaskingOneTtlMin = 60
export const hogFunctionsPartialUpdateResponseMaskingOneTtlMax = 86400

export const hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsPartialUpdateResponseTemplateOneNameMax = 400

export const hogFunctionsPartialUpdateResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsPartialUpdateResponseTemplateOneTypeMax = 50

export const hogFunctionsPartialUpdateResponseTemplateOneStatusMax = 20

export const hogFunctionsPartialUpdateResponseTemplateIdMax = 400

export const hogFunctionsPartialUpdateResponseExecutionOrderMin = 0
export const hogFunctionsPartialUpdateResponseExecutionOrderMax = 32767

export const HogFunctionsPartialUpdateResponse = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(hogFunctionsPartialUpdateResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFunctionsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFunctionsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFunctionsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFunctionsPartialUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsPartialUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsPartialUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsPartialUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsPartialUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsPartialUpdateResponseMaskingOneTtlMin)
                .max(hogFunctionsPartialUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsPartialUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(hogFunctionsPartialUpdateResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(hogFunctionsPartialUpdateResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(hogFunctionsPartialUpdateResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(hogFunctionsPartialUpdateResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(hogFunctionsPartialUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsPartialUpdateResponseExecutionOrderMin)
        .max(hogFunctionsPartialUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const HogFunctionsDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsEnableBackfillsCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsEnableBackfillsCreateBodyNameMax = 400

export const hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsEnableBackfillsCreateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMin = 60
export const hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMax = 86400

export const hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsEnableBackfillsCreateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsEnableBackfillsCreateBodyTemplateIdMax = 400

export const hogFunctionsEnableBackfillsCreateBodyExecutionOrderMin = 0
export const hogFunctionsEnableBackfillsCreateBodyExecutionOrderMax = 32767

export const HogFunctionsEnableBackfillsCreateBody = zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(hogFunctionsEnableBackfillsCreateBodyNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsEnableBackfillsCreateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMin)
                .max(hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsEnableBackfillsCreateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsEnableBackfillsCreateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsEnableBackfillsCreateBodyExecutionOrderMin)
        .max(hogFunctionsEnableBackfillsCreateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const HogFunctionsInvocationsCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsInvocationsCreateBodyConfigurationOneNameMax = 400

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax = 200

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax = 150

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax = 150

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax = 254

export const hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneFiltersOneSourceDefault = `events`
export const hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMin = 60
export const hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMax = 86400

export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneNameMax = 400

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneCodeLanguageMax = 20

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneTypeMax = 50

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneStatusMax = 20

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateIdMax = 400

export const hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMin = 0
export const hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMax = 32767

export const hogFunctionsInvocationsCreateBodyMockAsyncFunctionsDefault = true

export const HogFunctionsInvocationsCreateBody = zod.object({
    configuration: zod
        .object({
            id: zod.string().optional(),
            type: zod
                .union([
                    zod
                        .enum([
                            'destination',
                            'site_destination',
                            'internal_destination',
                            'source_webhook',
                            'warehouse_source_webhook',
                            'site_app',
                            'transformation',
                        ])
                        .describe(
                            '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                        ),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            name: zod
                .string()
                .max(hogFunctionsInvocationsCreateBodyConfigurationOneNameMax)
                .nullish()
                .describe('Display name for the function.'),
            description: zod.string().optional().describe('Human-readable description of what this function does.'),
            created_at: zod.string().datetime({}).optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax)
                        .optional(),
                    email: zod
                        .string()
                        .email()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax),
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
            updated_at: zod.string().datetime({}).optional(),
            enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
            hog: zod
                .string()
                .optional()
                .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
            inputs_schema: zod
                .array(
                    zod.object({
                        type: zod
                            .enum([
                                'string',
                                'number',
                                'boolean',
                                'dictionary',
                                'choice',
                                'json',
                                'integration',
                                'integration_field',
                                'email',
                                'native_email',
                                'posthog_assignee',
                                'posthog_ticket_tags',
                            ])
                            .describe(
                                '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                            ),
                        key: zod.string(),
                        label: zod.string().optional(),
                        choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        required: zod
                            .boolean()
                            .default(hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemRequiredDefault),
                        default: zod.unknown().optional(),
                        secret: zod
                            .boolean()
                            .default(hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemSecretDefault),
                        hidden: zod
                            .boolean()
                            .default(hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemHiddenDefault),
                        description: zod.string().optional(),
                        templating: zod
                            .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                            .optional()
                            .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                    })
                )
                .optional()
                .describe('Schema defining the configurable input parameters for this function.'),
            inputs: zod
                .record(
                    zod.string(),
                    zod.object({
                        value: zod.unknown().optional(),
                        templating: zod
                            .enum(['hog', 'liquid'])
                            .optional()
                            .describe('* `hog` - hog\n* `liquid` - liquid'),
                        bytecode: zod.array(zod.unknown()).optional(),
                        order: zod.number().optional(),
                        transpiled: zod.unknown().optional(),
                    })
                )
                .optional()
                .describe('Values for each input defined in inputs_schema.'),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFunctionsInvocationsCreateBodyConfigurationOneFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    filter_test_accounts: zod.boolean().optional(),
                })
                .optional()
                .describe('Event filters that control which events trigger this function.'),
            masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMin)
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMax)
                        .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                    threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                    hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                    bytecode: zod
                        .unknown()
                        .nullish()
                        .describe('Compiled bytecode for the hash expression. Auto-generated.'),
                })
                .nullish()
                .describe('PII masking configuration with TTL, threshold, and hash expression.'),
            mappings: zod
                .array(
                    zod.object({
                        name: zod.string().optional(),
                        inputs_schema: zod
                            .array(
                                zod.object({
                                    type: zod
                                        .enum([
                                            'string',
                                            'number',
                                            'boolean',
                                            'dictionary',
                                            'choice',
                                            'json',
                                            'integration',
                                            'integration_field',
                                            'email',
                                            'native_email',
                                            'posthog_assignee',
                                            'posthog_ticket_tags',
                                        ])
                                        .describe(
                                            '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                        ),
                                    key: zod.string(),
                                    label: zod.string().optional(),
                                    choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    required: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemRequiredDefault
                                        ),
                                    default: zod.unknown().optional(),
                                    secret: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemSecretDefault
                                        ),
                                    hidden: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemHiddenDefault
                                        ),
                                    description: zod.string().optional(),
                                    templating: zod
                                        .union([
                                            zod.literal(true),
                                            zod.literal(false),
                                            zod.literal('hog'),
                                            zod.literal('liquid'),
                                        ])
                                        .optional()
                                        .describe(
                                            '* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'
                                        ),
                                })
                            )
                            .optional(),
                        inputs: zod
                            .record(
                                zod.string(),
                                zod.object({
                                    value: zod.unknown().optional(),
                                    templating: zod
                                        .enum(['hog', 'liquid'])
                                        .optional()
                                        .describe('* `hog` - hog\n* `liquid` - liquid'),
                                    bytecode: zod.array(zod.unknown()).optional(),
                                    order: zod.number().optional(),
                                    transpiled: zod.unknown().optional(),
                                })
                            )
                            .optional(),
                        filters: zod
                            .object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(
                                        hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemFiltersSourceDefault
                                    ),
                                actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                filter_test_accounts: zod.boolean().optional(),
                            })
                            .optional(),
                    })
                )
                .nullish()
                .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
            icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
            template: zod
                .object({
                    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                    name: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneNameMax)
                        .describe('Display name of the template.'),
                    description: zod.string().nullish().describe('What this template does.'),
                    code: zod.string().describe('Source code of the template.'),
                    code_language: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneCodeLanguageMax)
                        .optional()
                        .describe("Programming language: 'hog' or 'javascript'."),
                    inputs_schema: zod
                        .unknown()
                        .describe('Schema defining configurable inputs for functions created from this template.'),
                    type: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneTypeMax)
                        .describe('Function type this template creates.'),
                    status: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneStatusMax)
                        .optional()
                        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                    free: zod.boolean().optional().describe('Whether available on free plans.'),
                    icon_url: zod.string().nullish().describe("URL for the template's icon."),
                    filters: zod.unknown().nullish().describe('Default event filters.'),
                    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                    mapping_templates: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Name of this mapping template.'),
                                include_by_default: zod
                                    .boolean()
                                    .nullish()
                                    .describe('Whether this mapping is enabled by default.'),
                                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                                inputs_schema: zod
                                    .unknown()
                                    .nullish()
                                    .describe('Additional input schema fields specific to this mapping.'),
                            })
                        )
                        .nullish()
                        .describe('Pre-defined mapping configurations for destination templates.'),
                })
                .optional(),
            template_id: zod
                .string()
                .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateIdMax)
                .nullish()
                .describe('ID of the template to create this function from.'),
            execution_order: zod
                .number()
                .min(hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMin)
                .max(hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMax)
                .nullish()
                .describe('Execution priority for transformations. Lower values run first.'),
        })
        .describe('Full function configuration to test.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock global variables available during test invocation.'),
    clickhouse_event: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock ClickHouse event data to test the function with.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFunctionsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe('When true (default), async functions like fetch() are simulated.'),
    invocation_id: zod.string().nullish().describe('Optional invocation ID for correlation.'),
})

export const hogFunctionsInvocationsCreateResponseConfigurationOneNameMax = 400

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneDistinctIdMax = 200

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneFirstNameMax = 150

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneLastNameMax = 150

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneEmailMax = 254

export const hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneFiltersOneSourceDefault = `events`
export const hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMin = 60
export const hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMax = 86400

export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneNameMax = 400

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneCodeLanguageMax = 20

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneTypeMax = 50

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneStatusMax = 20

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateIdMax = 400

export const hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMin = 0
export const hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMax = 32767

export const hogFunctionsInvocationsCreateResponseMockAsyncFunctionsDefault = true

export const HogFunctionsInvocationsCreateResponse = zod.object({
    configuration: zod
        .object({
            id: zod.string().optional(),
            type: zod
                .union([
                    zod
                        .enum([
                            'destination',
                            'site_destination',
                            'internal_destination',
                            'source_webhook',
                            'warehouse_source_webhook',
                            'site_app',
                            'transformation',
                        ])
                        .describe(
                            '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                        ),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            name: zod
                .string()
                .max(hogFunctionsInvocationsCreateResponseConfigurationOneNameMax)
                .nullish()
                .describe('Display name for the function.'),
            description: zod.string().optional().describe('Human-readable description of what this function does.'),
            created_at: zod.string().datetime({}).optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneLastNameMax)
                        .optional(),
                    email: zod
                        .string()
                        .email()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneEmailMax),
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
            updated_at: zod.string().datetime({}).optional(),
            enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
            hog: zod
                .string()
                .optional()
                .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
            inputs_schema: zod
                .array(
                    zod.object({
                        type: zod
                            .enum([
                                'string',
                                'number',
                                'boolean',
                                'dictionary',
                                'choice',
                                'json',
                                'integration',
                                'integration_field',
                                'email',
                                'native_email',
                                'posthog_assignee',
                                'posthog_ticket_tags',
                            ])
                            .describe(
                                '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                            ),
                        key: zod.string(),
                        label: zod.string().optional(),
                        choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        required: zod
                            .boolean()
                            .default(
                                hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemRequiredDefault
                            ),
                        default: zod.unknown().optional(),
                        secret: zod
                            .boolean()
                            .default(
                                hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemSecretDefault
                            ),
                        hidden: zod
                            .boolean()
                            .default(
                                hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemHiddenDefault
                            ),
                        description: zod.string().optional(),
                        templating: zod
                            .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                            .optional()
                            .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                    })
                )
                .optional()
                .describe('Schema defining the configurable input parameters for this function.'),
            inputs: zod
                .record(
                    zod.string(),
                    zod.object({
                        value: zod.unknown().optional(),
                        templating: zod
                            .enum(['hog', 'liquid'])
                            .optional()
                            .describe('* `hog` - hog\n* `liquid` - liquid'),
                        bytecode: zod.array(zod.unknown()).optional(),
                        order: zod.number().optional(),
                        transpiled: zod.unknown().optional(),
                    })
                )
                .optional()
                .describe('Values for each input defined in inputs_schema.'),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFunctionsInvocationsCreateResponseConfigurationOneFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    filter_test_accounts: zod.boolean().optional(),
                })
                .optional()
                .describe('Event filters that control which events trigger this function.'),
            masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMin)
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMax)
                        .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                    threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                    hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                    bytecode: zod
                        .unknown()
                        .nullish()
                        .describe('Compiled bytecode for the hash expression. Auto-generated.'),
                })
                .nullish()
                .describe('PII masking configuration with TTL, threshold, and hash expression.'),
            mappings: zod
                .array(
                    zod.object({
                        name: zod.string().optional(),
                        inputs_schema: zod
                            .array(
                                zod.object({
                                    type: zod
                                        .enum([
                                            'string',
                                            'number',
                                            'boolean',
                                            'dictionary',
                                            'choice',
                                            'json',
                                            'integration',
                                            'integration_field',
                                            'email',
                                            'native_email',
                                            'posthog_assignee',
                                            'posthog_ticket_tags',
                                        ])
                                        .describe(
                                            '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                        ),
                                    key: zod.string(),
                                    label: zod.string().optional(),
                                    choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    required: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemRequiredDefault
                                        ),
                                    default: zod.unknown().optional(),
                                    secret: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemSecretDefault
                                        ),
                                    hidden: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemHiddenDefault
                                        ),
                                    description: zod.string().optional(),
                                    templating: zod
                                        .union([
                                            zod.literal(true),
                                            zod.literal(false),
                                            zod.literal('hog'),
                                            zod.literal('liquid'),
                                        ])
                                        .optional()
                                        .describe(
                                            '* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'
                                        ),
                                })
                            )
                            .optional(),
                        inputs: zod
                            .record(
                                zod.string(),
                                zod.object({
                                    value: zod.unknown().optional(),
                                    templating: zod
                                        .enum(['hog', 'liquid'])
                                        .optional()
                                        .describe('* `hog` - hog\n* `liquid` - liquid'),
                                    bytecode: zod.array(zod.unknown()).optional(),
                                    order: zod.number().optional(),
                                    transpiled: zod.unknown().optional(),
                                })
                            )
                            .optional(),
                        filters: zod
                            .object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(
                                        hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemFiltersSourceDefault
                                    ),
                                actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                filter_test_accounts: zod.boolean().optional(),
                            })
                            .optional(),
                    })
                )
                .nullish()
                .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
            icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
            template: zod
                .object({
                    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                    name: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneNameMax)
                        .describe('Display name of the template.'),
                    description: zod.string().nullish().describe('What this template does.'),
                    code: zod.string().describe('Source code of the template.'),
                    code_language: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneCodeLanguageMax)
                        .optional()
                        .describe("Programming language: 'hog' or 'javascript'."),
                    inputs_schema: zod
                        .unknown()
                        .describe('Schema defining configurable inputs for functions created from this template.'),
                    type: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneTypeMax)
                        .describe('Function type this template creates.'),
                    status: zod
                        .string()
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneStatusMax)
                        .optional()
                        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                    free: zod.boolean().optional().describe('Whether available on free plans.'),
                    icon_url: zod.string().nullish().describe("URL for the template's icon."),
                    filters: zod.unknown().nullish().describe('Default event filters.'),
                    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                    mapping_templates: zod
                        .array(
                            zod.object({
                                name: zod.string().describe('Name of this mapping template.'),
                                include_by_default: zod
                                    .boolean()
                                    .nullish()
                                    .describe('Whether this mapping is enabled by default.'),
                                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                                inputs_schema: zod
                                    .unknown()
                                    .nullish()
                                    .describe('Additional input schema fields specific to this mapping.'),
                            })
                        )
                        .nullish()
                        .describe('Pre-defined mapping configurations for destination templates.'),
                })
                .optional(),
            template_id: zod
                .string()
                .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateIdMax)
                .nullish()
                .describe('ID of the template to create this function from.'),
            execution_order: zod
                .number()
                .min(hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMin)
                .max(hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMax)
                .nullish()
                .describe('Execution priority for transformations. Lower values run first.'),
        })
        .describe('Full function configuration to test.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock global variables available during test invocation.'),
    clickhouse_event: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock ClickHouse event data to test the function with.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFunctionsInvocationsCreateResponseMockAsyncFunctionsDefault)
        .describe('When true (default), async functions like fetch() are simulated.'),
    status: zod.string().optional().describe('Invocation result status.'),
    logs: zod.array(zod.unknown()).optional().describe('Execution logs from the test invocation.'),
    invocation_id: zod.string().nullish().describe('Optional invocation ID for correlation.'),
})

export const HogFunctionsLogsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsMetricsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsMetricsTotalsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsIconRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsIconsRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Update the execution order of multiple HogFunctions.
 */
export const HogFunctionsRearrangePartialUpdateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsRearrangePartialUpdateBody = zod.object({
    orders: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe('Map of hog function UUIDs to their new execution_order values.'),
})

export const hogFunctionsRearrangePartialUpdateResponseNameMax = 400

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneLastNameMax = 150

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneEmailMax = 254

export const hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsRearrangePartialUpdateResponseFiltersOneSourceDefault = `events`
export const hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMin = 60
export const hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMax = 86400

export const hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsRearrangePartialUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsRearrangePartialUpdateResponseTemplateOneNameMax = 400

export const hogFunctionsRearrangePartialUpdateResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsRearrangePartialUpdateResponseTemplateOneTypeMax = 50

export const hogFunctionsRearrangePartialUpdateResponseTemplateOneStatusMax = 20

export const hogFunctionsRearrangePartialUpdateResponseTemplateIdMax = 400

export const hogFunctionsRearrangePartialUpdateResponseExecutionOrderMin = 0
export const hogFunctionsRearrangePartialUpdateResponseExecutionOrderMax = 32767

export const HogFunctionsRearrangePartialUpdateResponseItem = zod.object({
    id: zod.string().optional(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(hogFunctionsRearrangePartialUpdateResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod
                .string()
                .max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod.string().max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod
                    .boolean()
                    .default(hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsRearrangePartialUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            filter_test_accounts: zod.boolean().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMin)
                .max(hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsRearrangePartialUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod
        .object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
        .optional(),
    template_id: zod
        .string()
        .max(hogFunctionsRearrangePartialUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsRearrangePartialUpdateResponseExecutionOrderMin)
        .max(hogFunctionsRearrangePartialUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})
export const HogFunctionsRearrangePartialUpdateResponse = zod.array(HogFunctionsRearrangePartialUpdateResponseItem)
