/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const HogFunctionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsListQueryParams = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.number().optional(),
    enabled: zod.boolean().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    type: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export const HogFunctionsCreateParams = /* @__PURE__ */ zod.object({
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

export const HogFunctionsCreateBody = /* @__PURE__ */ zod.object({
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
            zod.null(),
        ])
        .optional()
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
                        'posthog_business_hours',
                        'non_failure_status_codes',
                        'customer_analytics_account_properties',
                        'customer_analytics_account_relationships',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours\n* `non_failure_status_codes` - non_failure_status_codes\n* `customer_analytics_account_properties` - customer_analytics_account_properties\n* `customer_analytics_account_relationships` - customer_analytics_account_relationships'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                searchable: zod.boolean().optional(),
                required: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
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
            bytecode: zod.unknown().optional(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFunctionsCreateBodyMaskingOneTtlMin)
                    .max(hogFunctionsCreateBodyMaskingOneTtlMax)
                    .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                bytecode: zod
                    .unknown()
                    .optional()
                    .describe('Compiled bytecode for the hash expression. Auto-generated.'),
            }),
            zod.null(),
        ])
        .optional()
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
                                    'posthog_business_hours',
                                    'non_failure_status_codes',
                                    'customer_analytics_account_properties',
                                    'customer_analytics_account_relationships',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours\n* `non_failure_status_codes` - non_failure_status_codes\n* `customer_analytics_account_properties` - customer_analytics_account_properties\n* `customer_analytics_account_relationships` - customer_analytics_account_relationships'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            searchable: zod.boolean().optional(),
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
                            templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
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

export const HogFunctionsPartialUpdateParams = /* @__PURE__ */ zod.object({
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

export const HogFunctionsPartialUpdateBody = /* @__PURE__ */ zod.object({
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
            zod.null(),
        ])
        .optional()
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
                        'posthog_business_hours',
                        'non_failure_status_codes',
                        'customer_analytics_account_properties',
                        'customer_analytics_account_relationships',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours\n* `non_failure_status_codes` - non_failure_status_codes\n* `customer_analytics_account_properties` - customer_analytics_account_properties\n* `customer_analytics_account_relationships` - customer_analytics_account_relationships'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                searchable: zod.boolean().optional(),
                required: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
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
            bytecode: zod.unknown().optional(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFunctionsPartialUpdateBodyMaskingOneTtlMin)
                    .max(hogFunctionsPartialUpdateBodyMaskingOneTtlMax)
                    .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                bytecode: zod
                    .unknown()
                    .optional()
                    .describe('Compiled bytecode for the hash expression. Auto-generated.'),
            }),
            zod.null(),
        ])
        .optional()
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
                                    'posthog_business_hours',
                                    'non_failure_status_codes',
                                    'customer_analytics_account_properties',
                                    'customer_analytics_account_relationships',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours\n* `non_failure_status_codes` - non_failure_status_codes\n* `customer_analytics_account_properties` - customer_analytics_account_properties\n* `customer_analytics_account_relationships` - customer_analytics_account_relationships'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            searchable: zod.boolean().optional(),
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
                            templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
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

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const HogFunctionsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
