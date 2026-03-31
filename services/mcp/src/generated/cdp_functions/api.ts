/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
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
    created_at: zod.iso.datetime({}).optional(),
    created_by: zod.number().optional(),
    enabled: zod.boolean().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
    type: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    updated_at: zod.iso.datetime({}).optional(),
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
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
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

export const HogFunctionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
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

export const HogFunctionsInvocationsCreateParams = /* @__PURE__ */ zod.object({
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

export const HogFunctionsInvocationsCreateBody = /* @__PURE__ */ zod.object({
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
            created_at: zod.iso.datetime({}).optional(),
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
                    email: zod.email().max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax),
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
            updated_at: zod.iso.datetime({}).optional(),
            enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
            deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
            hog: zod
                .string()
                .optional()
                .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.string().nullish(),
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
                        integration: zod.string().optional(),
                        integration_key: zod.string().optional(),
                        requires_field: zod.string().optional(),
                        integration_field: zod.string().optional(),
                        requiredScopes: zod.string().optional(),
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
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
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
                                    integration: zod.string().optional(),
                                    integration_key: zod.string().optional(),
                                    requires_field: zod.string().optional(),
                                    integration_field: zod.string().optional(),
                                    requiredScopes: zod.string().optional(),
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
                                bytecode: zod.unknown().nullish(),
                                transpiled: zod.unknown().optional(),
                                filter_test_accounts: zod.boolean().optional(),
                                bytecode_error: zod.string().optional(),
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
            execution_order: zod
                .number()
                .min(hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMin)
                .max(hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMax)
                .nullish()
                .describe('Execution priority for transformations. Lower values run first.'),
            _create_in_folder: zod.string().optional(),
            batch_export_id: zod.string().nullish(),
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

/**
 * Update the execution order of multiple HogFunctions.
 */
export const HogFunctionsRearrangePartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsRearrangePartialUpdateBody = /* @__PURE__ */ zod.object({
    orders: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe('Map of hog function UUIDs to their new execution_order values.'),
})
