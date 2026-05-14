/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Upsert a column on a catalog node with its typing and description.
 */
export const CatalogColumnsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const catalogColumnsCreateBodyNameMax = 400

export const catalogColumnsCreateBodyPositionDefault = 0
export const catalogColumnsCreateBodyClickhouseTypeMax = 255

export const catalogColumnsCreateBodyHogqlTypeMax = 128

export const catalogColumnsCreateBodyNullableDefault = true
export const catalogColumnsCreateBodyGeneratorModelMax = 64

export const catalogColumnsCreateBodyConfidenceMin = 0
export const catalogColumnsCreateBodyConfidenceMax = 1

export const CatalogColumnsCreateBody = /* @__PURE__ */ zod
    .object({
        node_id: zod.string().describe('ID of the parent CatalogNode (returned by catalog-nodes-create).'),
        name: zod
            .string()
            .max(catalogColumnsCreateBodyNameMax)
            .describe(
                'Column name as it appears in the underlying table. Case-sensitive. Combined with `node_id` to form the upsert key — calling create again with the same (node_id, name) updates in place.'
            ),
        position: zod
            .number()
            .default(catalogColumnsCreateBodyPositionDefault)
            .describe('Ordinal position of the column in the source table. Used for display and stable iteration.'),
        clickhouse_type: zod
            .string()
            .max(catalogColumnsCreateBodyClickhouseTypeMax)
            .nullish()
            .describe(
                'Raw ClickHouse type string (`String`, `Nullable(DateTime64(3))`, `Array(String)`...). Set when the column comes from a ClickHouse-backed table; null for Postgres-only sources.'
            ),
        hogql_type: zod
            .string()
            .max(catalogColumnsCreateBodyHogqlTypeMax)
            .nullish()
            .describe(
                'HogQL-normalized type — `String`, `Int`, `Float`, `Boolean`, `DateTime`, `Array`, `JSON`. What the agent sees when reading via `system.columns`. Inferred from clickhouse_type when not set explicitly.'
            ),
        nullable: zod
            .boolean()
            .default(catalogColumnsCreateBodyNullableDefault)
            .describe('Whether the column can hold NULL values. Drives null-handling guidance in generated queries.'),
        synthetic_description: zod
            .string()
            .nullish()
            .describe(
                'What the column represents in business terms — meaning, units, valid values, gotchas. Example: "Subscription monthly recurring revenue in USD cents. Excludes refunds. Null for one-time charges."'
            ),
        semantic_type: zod
            .union([
                zod
                    .enum([
                        'entity_id',
                        'foreign_key',
                        'timestamp',
                        'measure',
                        'dimension',
                        'monetary',
                        'free_text',
                        'enum',
                        'uuid',
                        'unknown',
                    ])
                    .describe(
                        '* `entity_id` - entity_id\n* `foreign_key` - foreign_key\n* `timestamp` - timestamp\n* `measure` - measure\n* `dimension` - dimension\n* `monetary` - monetary\n* `free_text` - free_text\n* `enum` - enum\n* `uuid` - uuid\n* `unknown` - unknown'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Role of the column for query planning. `entity_id` for primary identifiers, `foreign_key` for join targets, `timestamp` for time filtering, `measure` for aggregation, `dimension` for group-by, `monetary` for currency, `free_text` for unstructured prose, `enum` for closed value sets.\n\n* `entity_id` - entity_id\n* `foreign_key` - foreign_key\n* `timestamp` - timestamp\n* `measure` - measure\n* `dimension` - dimension\n* `monetary` - monetary\n* `free_text` - free_text\n* `enum` - enum\n* `uuid` - uuid\n* `unknown` - unknown'
            ),
        pii_class: zod
            .union([
                zod
                    .enum(['pii', 'sensitive', 'public', 'unknown'])
                    .describe('* `pii` - pii\n* `sensitive` - sensitive\n* `public` - public\n* `unknown` - unknown'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Sensitivity classification. `pii` for personally identifiable (email, name, IP), `sensitive` for business-confidential, `public` for safe-to-export, `unknown` to defer classification.\n\n* `pii` - pii\n* `sensitive` - sensitive\n* `public` - public\n* `unknown` - unknown'
            ),
        generator_model: zod
            .string()
            .max(catalogColumnsCreateBodyGeneratorModelMax)
            .nullish()
            .describe('Model that generated the description/typing — same convention as on nodes.'),
        confidence: zod
            .number()
            .min(catalogColumnsCreateBodyConfidenceMin)
            .max(catalogColumnsCreateBodyConfidenceMax)
            .nullish()
            .describe('Agent confidence (0..1) in the description and semantic typing.'),
    })
    .describe('Body for catalog-columns-create. Identified by (node_id, name).')

/**
 * Propose a semantic metric and bind its CatalogNode in one call.
 */
export const CatalogMetricsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const catalogMetricsCreateBodyNameMax = 400

export const catalogMetricsCreateBodyDescriptionDefault = ``
export const catalogMetricsCreateBodyDefinitionOneOneCustomNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneEventDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneOperatorDefault = `exact`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneTypeDefault = `event`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwoTypeDefault = `person`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemThreeLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemThreeTypeDefault = `element`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemThreeValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFourTypeDefault = `event_metadata`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFiveTypeDefault = `session`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixCohortNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixKeyDefault = `id`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixOperatorDefault = `in`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixTypeDefault = `cohort`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSevenTypeDefault = `recording`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemEightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemEightTypeDefault = `log_entry`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemEightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineGroupKeyNamesDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineGroupTypeIndexDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineTypeDefault = `group`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnezeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnezeroTypeDefault = `feature`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnezeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneoneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneoneOperatorDefault = `flag_evaluates_to`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneoneTypeDefault = `flag`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnetwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnetwoTypeDefault = `hogql`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnetwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnethreeTypeDefault = `empty`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefourTypeDefault = `data_warehouse`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse_person_property`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesixTypeDefault = `error_tracking_issue`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesixValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneeightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneeightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnenineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnenineTypeDefault = `revenue_analytics`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnenineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwozeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwozeroTypeDefault = `workflow_variable`
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwozeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneKindDefault = `EventsNode`
export const catalogMetricsCreateBodyDefinitionOneOneLimitDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathGroupTypeIndexDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathHogqlDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathMultiplierDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathPropertyDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathPropertyRevenueCurrencyOnePropertyDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathPropertyRevenueCurrencyOneStaticDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathPropertyRevenueCurrencyDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneMathPropertyTypeDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneOptionalInFunnelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneOrderByDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneOperatorDefault = `exact`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneTypeDefault = `event`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwoTypeDefault = `person`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemThreeLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemThreeTypeDefault = `element`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemThreeValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFourTypeDefault = `event_metadata`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFiveTypeDefault = `session`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixCohortNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixKeyDefault = `id`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixOperatorDefault = `in`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixTypeDefault = `cohort`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSevenTypeDefault = `recording`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemEightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemEightTypeDefault = `log_entry`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemEightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineGroupKeyNamesDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineGroupTypeIndexDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineTypeDefault = `group`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnezeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnezeroTypeDefault = `feature`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnezeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneoneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneoneOperatorDefault = `flag_evaluates_to`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneoneTypeDefault = `flag`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnetwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnetwoTypeDefault = `hogql`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnetwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnethreeTypeDefault = `empty`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefourTypeDefault = `data_warehouse`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefiveTypeDefault = `data_warehouse_person_property`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesixTypeDefault = `error_tracking_issue`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesixValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneeightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneeightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnenineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnenineTypeDefault = `revenue_analytics`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnenineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwozeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwozeroTypeDefault = `workflow_variable`
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwozeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneOnePropertiesDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneResponseDefault = null
export const catalogMetricsCreateBodyDefinitionOneOneVersionDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoCustomNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoDwSourceTypeDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneOperatorDefault = `exact`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneTypeDefault = `event`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwoTypeDefault = `person`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemThreeLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemThreeTypeDefault = `element`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemThreeValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFourTypeDefault = `event_metadata`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFiveTypeDefault = `session`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixCohortNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixKeyDefault = `id`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixOperatorDefault = `in`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixTypeDefault = `cohort`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSevenTypeDefault = `recording`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemEightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemEightTypeDefault = `log_entry`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemEightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineGroupKeyNamesDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineGroupTypeIndexDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineTypeDefault = `group`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnezeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnezeroTypeDefault = `feature`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnezeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneoneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneoneOperatorDefault = `flag_evaluates_to`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneoneTypeDefault = `flag`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnetwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnetwoTypeDefault = `hogql`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnetwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnethreeTypeDefault = `empty`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefourTypeDefault = `data_warehouse`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefiveTypeDefault = `data_warehouse_person_property`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesixTypeDefault = `error_tracking_issue`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesixValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneeightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneeightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnenineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnenineTypeDefault = `revenue_analytics`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnenineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwozeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwozeroTypeDefault = `workflow_variable`
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwozeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoKindDefault = `DataWarehouseNode`
export const catalogMetricsCreateBodyDefinitionOneTwoMathDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathGroupTypeIndexDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathHogqlDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathMultiplierDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathPropertyDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathPropertyRevenueCurrencyOnePropertyDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathPropertyRevenueCurrencyOneStaticDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathPropertyRevenueCurrencyDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoMathPropertyTypeDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoOptionalInFunnelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneOperatorDefault = `exact`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneTypeDefault = `event`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwoTypeDefault = `person`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemThreeLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemThreeTypeDefault = `element`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemThreeValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFourTypeDefault = `event_metadata`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFiveTypeDefault = `session`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixCohortNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixKeyDefault = `id`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixOperatorDefault = `in`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixTypeDefault = `cohort`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSevenTypeDefault = `recording`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemEightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemEightTypeDefault = `log_entry`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemEightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineGroupKeyNamesDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineGroupTypeIndexDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineTypeDefault = `group`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnezeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnezeroTypeDefault = `feature`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnezeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneoneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneoneOperatorDefault = `flag_evaluates_to`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneoneTypeDefault = `flag`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnetwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnetwoTypeDefault = `hogql`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnetwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnethreeTypeDefault = `empty`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefourTypeDefault = `data_warehouse`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefiveTypeDefault = `data_warehouse_person_property`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesixTypeDefault = `error_tracking_issue`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesixValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneeightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneeightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnenineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnenineTypeDefault = `revenue_analytics`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnenineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwozeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwozeroTypeDefault = `workflow_variable`
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwozeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoPropertiesDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoResponseDefault = null
export const catalogMetricsCreateBodyDefinitionOneTwoVersionDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeConnectionIdDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeExplainDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeOneDateFromDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeOneDateToDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeOneExplicitDateDefault = false
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOneFilterTestAccountsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneOperatorDefault = `exact`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneTypeDefault = `event`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwoTypeDefault = `person`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemThreeLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemThreeTypeDefault = `element`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemThreeValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFourTypeDefault = `event_metadata`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFiveTypeDefault = `session`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixCohortNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixKeyDefault = `id`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixOperatorDefault = `in`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixTypeDefault = `cohort`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSevenTypeDefault = `recording`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemEightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemEightTypeDefault = `log_entry`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemEightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineGroupKeyNamesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineGroupTypeIndexDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineTypeDefault = `group`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnezeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnezeroTypeDefault = `feature`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnezeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneoneLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneoneOperatorDefault = `flag_evaluates_to`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneoneTypeDefault = `flag`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnetwoLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnetwoTypeDefault = `hogql`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnetwoValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnethreeTypeDefault = `empty`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefourLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefourTypeDefault = `data_warehouse`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefourValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefiveLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefiveTypeDefault = `data_warehouse_person_property`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefiveValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesixLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesixTypeDefault = `error_tracking_issue`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesixValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesevenLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesevenValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneeightLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneeightValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnenineLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnenineTypeDefault = `revenue_analytics`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnenineValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwozeroLabelDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwozeroTypeDefault = `workflow_variable`
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwozeroValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeFiltersDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeKindDefault = `HogQLQuery`
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneBounceRateDurationSecondsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneBounceRatePageViewModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneConvertToProjectTimezoneDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneCustomChannelTypeRulesOneItemItemsItemValueDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneCustomChannelTypeRulesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneDataWarehouseEventsModifiersDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneDebugDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneForceClickhouseDataSkippingIndexesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneFormatCsvAllowDoubleQuotesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneInCohortViaDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneInlineCohortCalculationDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneMaterializationModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneMaterializedColumnsOptimizationModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneOptimizeJoinedFiltersDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneOptimizeProjectionsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePersonsArgMaxVersionDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePersonsJoinModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePersonsOnEventsModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePropertyGroupsModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneS3TableUseInvalidColumnsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionIdPushdownDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionPropertyPreAggregationDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionTableVersionDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionsV2JoinModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneTimingsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUseMaterializedViewsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUsePreaggregatedIntermediateResultsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUsePreaggregatedTableTransformsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUseWebAnalyticsPreAggregatedTablesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeModifiersDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneClickhouseDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneColumnsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneErrorDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneExplainDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneHasMoreDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneHogqlDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneLimitDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneChTableNamesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneErrorsItemEndDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneErrorsItemFixDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneErrorsItemStartDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneIsUsingIndicesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneIsValidDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneNoticesItemEndDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneNoticesItemFixDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneNoticesItemStartDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneQueryDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneTableNamesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneWarningsItemEndDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneWarningsItemFixDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneWarningsItemStartDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneBounceRateDurationSecondsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneBounceRatePageViewModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneConvertToProjectTimezoneDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneCustomChannelTypeRulesOneItemItemsItemValueDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneCustomChannelTypeRulesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneDataWarehouseEventsModifiersDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneDebugDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneForceClickhouseDataSkippingIndexesDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneFormatCsvAllowDoubleQuotesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneInCohortViaDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneInlineCohortCalculationDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneMaterializationModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneMaterializedColumnsOptimizationModeDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneOptimizeJoinedFiltersDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneOptimizeProjectionsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePersonsArgMaxVersionDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePersonsJoinModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePersonsOnEventsModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePropertyGroupsModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneS3TableUseInvalidColumnsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionIdPushdownDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionPropertyPreAggregationDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionTableVersionDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionsV2JoinModeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneTimingsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUseMaterializedViewsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUsePreaggregatedIntermediateResultsDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUsePreaggregatedTableTransformsDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUseWebAnalyticsPreAggregatedTablesDefault =
    null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneOffsetDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneCompleteDefault = false
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneDashboardIdDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneEndTimeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneErrorDefault = false
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneErrorMessageDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneExpirationTimeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneInsightIdDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneLabelsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOnePickupTimeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneQueryAsyncDefault = true
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneQueryProgressDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneResultsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneStartTimeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneTaskIdDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneResolvedDateRangeDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneTimingsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseOneTypesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeResponseDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeSendRawQueryDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeTagsOneNameDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeTagsOneProductKeyDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeTagsOneSceneDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeTagsDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeValuesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeVariablesOneIsNullDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeVariablesOneValueDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeVariablesDefault = null
export const catalogMetricsCreateBodyDefinitionOneThreeVersionDefault = null
export const catalogMetricsCreateBodyGeneratorModelMax = 64

export const catalogMetricsCreateBodyConfidenceMin = 0
export const catalogMetricsCreateBodyConfidenceMax = 1

export const CatalogMetricsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(catalogMetricsCreateBodyNameMax)
            .describe(
                "Stable identifier for the metric, unique per team. Use a short snake_case or kebab-case slug that won't change as the metric evolves (e.g. `monthly_recurring_revenue`, `signup_conversion_rate`). The agent looks metrics up by name before upserting, so keep this stable across runs."
            ),
        description: zod
            .string()
            .default(catalogMetricsCreateBodyDescriptionDefault)
            .describe(
                'Human-readable description of what this metric measures, when to use it, and any caveats — 1-2 sentences. Becomes the primary signal future agents use to decide whether this is the right metric to reference for a question.'
            ),
        definition: zod
            .union([
                zod.object({
                    custom_name: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneCustomNameDefault),
                    event: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneEventDefault)
                        .describe('The event or `null` for all events.'),
                    fixedProperties: zod
                        .union([
                            zod.array(
                                zod.union([
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneOperatorDefault
                                            ),
                                        type: zod
                                            .literal('event')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwoLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('person')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwoTypeDefault
                                            )
                                            .describe('Person properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemThreeLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('element')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemThreeTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemThreeValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('event_metadata')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('session')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemFiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        cohort_name: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixCohortNameDefault
                                            ),
                                        key: zod
                                            .literal('id')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixKeyDefault
                                            ),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixOperatorDefault
                                            ),
                                        type: zod
                                            .literal('cohort')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSixTypeDefault
                                            ),
                                        value: zod.number(),
                                    }),
                                    zod.object({
                                        key: zod.union([
                                            zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                            zod.string(),
                                        ]),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('recording')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSevenTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemSevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemEightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('log_entry')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemEightTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemEightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        group_key_names: zod
                                            .union([zod.record(zod.string(), zod.string()), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineGroupKeyNamesDefault
                                            ),
                                        group_type_index: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineGroupTypeIndexDefault
                                            ),
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('group')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemNineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnezeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('feature')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnezeroTypeDefault
                                            )
                                            .describe('Event property with "$feature/" prepended'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnezeroValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('The key should be the flag ID'),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneoneLabelDefault
                                            ),
                                        operator: zod
                                            .literal('flag_evaluates_to')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneoneOperatorDefault
                                            )
                                            .describe(
                                                'Only flag_evaluates_to operator is allowed for flag dependencies'
                                            ),
                                        type: zod
                                            .literal('flag')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneoneTypeDefault
                                            )
                                            .describe('Feature flag dependency'),
                                        value: zod
                                            .union([zod.boolean(), zod.string()])
                                            .describe('The value can be true, false, or a variant name'),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnetwoLabelDefault
                                            ),
                                        type: zod
                                            .literal('hogql')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnetwoTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnetwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        type: zod
                                            .literal('empty')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnethreeTypeDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse_person_property')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnefiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesixLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('error_tracking_issue')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesixTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesixValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnesevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneeightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOneeightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnenineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('revenue_analytics')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnenineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemOnenineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwozeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('workflow_variable')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwozeroTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesOneItemTwozeroValueDefault
                                            ),
                                    }),
                                ])
                            ),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneOneFixedPropertiesDefault)
                        .describe(
                            "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                        ),
                    kind: zod.literal('EventsNode').default(catalogMetricsCreateBodyDefinitionOneOneKindDefault),
                    limit: zod
                        .union([zod.number(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneLimitDefault),
                    math: zod
                        .union([
                            zod.enum([
                                'total',
                                'dau',
                                'weekly_active',
                                'monthly_active',
                                'unique_session',
                                'first_time_for_user',
                                'first_matching_event_for_user',
                            ]),
                            zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                            zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                            zod.enum([
                                'avg_count_per_actor',
                                'min_count_per_actor',
                                'max_count_per_actor',
                                'median_count_per_actor',
                                'p75_count_per_actor',
                                'p90_count_per_actor',
                                'p95_count_per_actor',
                                'p99_count_per_actor',
                            ]),
                            zod.enum([
                                'total',
                                'sum',
                                'unique_session',
                                'min',
                                'max',
                                'avg',
                                'dau',
                                'unique_group',
                                'hogql',
                            ]),
                            zod.enum(['total', 'dau']),
                            zod.literal('unique_group'),
                            zod.literal('hogql'),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneOneMathDefault),
                    math_group_type_index: zod
                        .union([
                            zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneOneMathGroupTypeIndexDefault),
                    math_hogql: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneMathHogqlDefault),
                    math_multiplier: zod
                        .union([zod.number(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneMathMultiplierDefault),
                    math_property: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneMathPropertyDefault),
                    math_property_revenue_currency: zod
                        .union([
                            zod.object({
                                property: zod
                                    .union([zod.string(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneOneMathPropertyRevenueCurrencyOnePropertyDefault
                                    ),
                                static: zod
                                    .union([
                                        zod.enum([
                                            'AED',
                                            'AFN',
                                            'ALL',
                                            'AMD',
                                            'ANG',
                                            'AOA',
                                            'ARS',
                                            'AUD',
                                            'AWG',
                                            'AZN',
                                            'BAM',
                                            'BBD',
                                            'BDT',
                                            'BGN',
                                            'BHD',
                                            'BIF',
                                            'BMD',
                                            'BND',
                                            'BOB',
                                            'BRL',
                                            'BSD',
                                            'BTC',
                                            'BTN',
                                            'BWP',
                                            'BYN',
                                            'BZD',
                                            'CAD',
                                            'CDF',
                                            'CHF',
                                            'CLP',
                                            'CNY',
                                            'COP',
                                            'CRC',
                                            'CVE',
                                            'CZK',
                                            'DJF',
                                            'DKK',
                                            'DOP',
                                            'DZD',
                                            'EGP',
                                            'ERN',
                                            'ETB',
                                            'EUR',
                                            'FJD',
                                            'GBP',
                                            'GEL',
                                            'GHS',
                                            'GIP',
                                            'GMD',
                                            'GNF',
                                            'GTQ',
                                            'GYD',
                                            'HKD',
                                            'HNL',
                                            'HRK',
                                            'HTG',
                                            'HUF',
                                            'IDR',
                                            'ILS',
                                            'INR',
                                            'IQD',
                                            'IRR',
                                            'ISK',
                                            'JMD',
                                            'JOD',
                                            'JPY',
                                            'KES',
                                            'KGS',
                                            'KHR',
                                            'KMF',
                                            'KRW',
                                            'KWD',
                                            'KYD',
                                            'KZT',
                                            'LAK',
                                            'LBP',
                                            'LKR',
                                            'LRD',
                                            'LTL',
                                            'LVL',
                                            'LSL',
                                            'LYD',
                                            'MAD',
                                            'MDL',
                                            'MGA',
                                            'MKD',
                                            'MMK',
                                            'MNT',
                                            'MOP',
                                            'MRU',
                                            'MTL',
                                            'MUR',
                                            'MVR',
                                            'MWK',
                                            'MXN',
                                            'MYR',
                                            'MZN',
                                            'NAD',
                                            'NGN',
                                            'NIO',
                                            'NOK',
                                            'NPR',
                                            'NZD',
                                            'OMR',
                                            'PAB',
                                            'PEN',
                                            'PGK',
                                            'PHP',
                                            'PKR',
                                            'PLN',
                                            'PYG',
                                            'QAR',
                                            'RON',
                                            'RSD',
                                            'RUB',
                                            'RWF',
                                            'SAR',
                                            'SBD',
                                            'SCR',
                                            'SDG',
                                            'SEK',
                                            'SGD',
                                            'SRD',
                                            'SSP',
                                            'STN',
                                            'SYP',
                                            'SZL',
                                            'THB',
                                            'TJS',
                                            'TMT',
                                            'TND',
                                            'TOP',
                                            'TRY',
                                            'TTD',
                                            'TWD',
                                            'TZS',
                                            'UAH',
                                            'UGX',
                                            'USD',
                                            'UYU',
                                            'UZS',
                                            'VES',
                                            'VND',
                                            'VUV',
                                            'WST',
                                            'XAF',
                                            'XCD',
                                            'XOF',
                                            'XPF',
                                            'YER',
                                            'ZAR',
                                            'ZMW',
                                        ]),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneOneMathPropertyRevenueCurrencyOneStaticDefault
                                    ),
                            }),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneOneMathPropertyRevenueCurrencyDefault),
                    math_property_type: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneMathPropertyTypeDefault),
                    name: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneNameDefault),
                    optionalInFunnel: zod
                        .union([zod.boolean(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneOptionalInFunnelDefault),
                    orderBy: zod
                        .union([zod.array(zod.string()), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneOrderByDefault)
                        .describe('Columns to order by'),
                    properties: zod
                        .union([
                            zod.array(
                                zod.union([
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneOperatorDefault
                                            ),
                                        type: zod
                                            .literal('event')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwoLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('person')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwoTypeDefault
                                            )
                                            .describe('Person properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemThreeLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('element')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemThreeTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemThreeValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('event_metadata')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('session')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemFiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        cohort_name: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixCohortNameDefault
                                            ),
                                        key: zod
                                            .literal('id')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixKeyDefault
                                            ),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixOperatorDefault
                                            ),
                                        type: zod
                                            .literal('cohort')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSixTypeDefault
                                            ),
                                        value: zod.number(),
                                    }),
                                    zod.object({
                                        key: zod.union([
                                            zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                            zod.string(),
                                        ]),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('recording')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSevenTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemSevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemEightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('log_entry')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemEightTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemEightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        group_key_names: zod
                                            .union([zod.record(zod.string(), zod.string()), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineGroupKeyNamesDefault
                                            ),
                                        group_type_index: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineGroupTypeIndexDefault
                                            ),
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('group')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemNineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnezeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('feature')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnezeroTypeDefault
                                            )
                                            .describe('Event property with "$feature/" prepended'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnezeroValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('The key should be the flag ID'),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneoneLabelDefault
                                            ),
                                        operator: zod
                                            .literal('flag_evaluates_to')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneoneOperatorDefault
                                            )
                                            .describe(
                                                'Only flag_evaluates_to operator is allowed for flag dependencies'
                                            ),
                                        type: zod
                                            .literal('flag')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneoneTypeDefault
                                            )
                                            .describe('Feature flag dependency'),
                                        value: zod
                                            .union([zod.boolean(), zod.string()])
                                            .describe('The value can be true, false, or a variant name'),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnetwoLabelDefault
                                            ),
                                        type: zod
                                            .literal('hogql')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnetwoTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnetwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        type: zod
                                            .literal('empty')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnethreeTypeDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse_person_property')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnefiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesixLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('error_tracking_issue')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesixTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesixValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnesevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneeightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOneeightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnenineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('revenue_analytics')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnenineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemOnenineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwozeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('workflow_variable')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwozeroTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneOnePropertiesOneItemTwozeroValueDefault
                                            ),
                                    }),
                                ])
                            ),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneOnePropertiesDefault)
                        .describe('Properties configurable in the interface'),
                    response: zod
                        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneResponseDefault),
                    version: zod
                        .union([zod.number(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneOneVersionDefault)
                        .describe('version of the node, used for schema migrations'),
                }),
                zod.object({
                    custom_name: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoCustomNameDefault),
                    distinct_id_field: zod.string(),
                    dw_source_type: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoDwSourceTypeDefault),
                    fixedProperties: zod
                        .union([
                            zod.array(
                                zod.union([
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneOperatorDefault
                                            ),
                                        type: zod
                                            .literal('event')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwoLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('person')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwoTypeDefault
                                            )
                                            .describe('Person properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemThreeLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('element')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemThreeTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemThreeValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('event_metadata')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('session')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemFiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        cohort_name: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixCohortNameDefault
                                            ),
                                        key: zod
                                            .literal('id')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixKeyDefault
                                            ),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixOperatorDefault
                                            ),
                                        type: zod
                                            .literal('cohort')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSixTypeDefault
                                            ),
                                        value: zod.number(),
                                    }),
                                    zod.object({
                                        key: zod.union([
                                            zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                            zod.string(),
                                        ]),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('recording')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSevenTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemSevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemEightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('log_entry')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemEightTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemEightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        group_key_names: zod
                                            .union([zod.record(zod.string(), zod.string()), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineGroupKeyNamesDefault
                                            ),
                                        group_type_index: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineGroupTypeIndexDefault
                                            ),
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('group')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemNineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnezeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('feature')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnezeroTypeDefault
                                            )
                                            .describe('Event property with "$feature/" prepended'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnezeroValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('The key should be the flag ID'),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneoneLabelDefault
                                            ),
                                        operator: zod
                                            .literal('flag_evaluates_to')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneoneOperatorDefault
                                            )
                                            .describe(
                                                'Only flag_evaluates_to operator is allowed for flag dependencies'
                                            ),
                                        type: zod
                                            .literal('flag')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneoneTypeDefault
                                            )
                                            .describe('Feature flag dependency'),
                                        value: zod
                                            .union([zod.boolean(), zod.string()])
                                            .describe('The value can be true, false, or a variant name'),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnetwoLabelDefault
                                            ),
                                        type: zod
                                            .literal('hogql')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnetwoTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnetwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        type: zod
                                            .literal('empty')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnethreeTypeDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse_person_property')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnefiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesixLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('error_tracking_issue')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesixTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesixValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnesevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneeightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOneeightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnenineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('revenue_analytics')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnenineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemOnenineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwozeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('workflow_variable')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwozeroTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesOneItemTwozeroValueDefault
                                            ),
                                    }),
                                ])
                            ),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoFixedPropertiesDefault)
                        .describe(
                            "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)"
                        ),
                    id: zod.string(),
                    id_field: zod.string(),
                    kind: zod.literal('DataWarehouseNode').default(catalogMetricsCreateBodyDefinitionOneTwoKindDefault),
                    math: zod
                        .union([
                            zod.enum([
                                'total',
                                'dau',
                                'weekly_active',
                                'monthly_active',
                                'unique_session',
                                'first_time_for_user',
                                'first_matching_event_for_user',
                            ]),
                            zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters']),
                            zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99']),
                            zod.enum([
                                'avg_count_per_actor',
                                'min_count_per_actor',
                                'max_count_per_actor',
                                'median_count_per_actor',
                                'p75_count_per_actor',
                                'p90_count_per_actor',
                                'p95_count_per_actor',
                                'p99_count_per_actor',
                            ]),
                            zod.enum([
                                'total',
                                'sum',
                                'unique_session',
                                'min',
                                'max',
                                'avg',
                                'dau',
                                'unique_group',
                                'hogql',
                            ]),
                            zod.enum(['total', 'dau']),
                            zod.literal('unique_group'),
                            zod.literal('hogql'),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoMathDefault),
                    math_group_type_index: zod
                        .union([
                            zod.union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(4)]),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoMathGroupTypeIndexDefault),
                    math_hogql: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoMathHogqlDefault),
                    math_multiplier: zod
                        .union([zod.number(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoMathMultiplierDefault),
                    math_property: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoMathPropertyDefault),
                    math_property_revenue_currency: zod
                        .union([
                            zod.object({
                                property: zod
                                    .union([zod.string(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneTwoMathPropertyRevenueCurrencyOnePropertyDefault
                                    ),
                                static: zod
                                    .union([
                                        zod.enum([
                                            'AED',
                                            'AFN',
                                            'ALL',
                                            'AMD',
                                            'ANG',
                                            'AOA',
                                            'ARS',
                                            'AUD',
                                            'AWG',
                                            'AZN',
                                            'BAM',
                                            'BBD',
                                            'BDT',
                                            'BGN',
                                            'BHD',
                                            'BIF',
                                            'BMD',
                                            'BND',
                                            'BOB',
                                            'BRL',
                                            'BSD',
                                            'BTC',
                                            'BTN',
                                            'BWP',
                                            'BYN',
                                            'BZD',
                                            'CAD',
                                            'CDF',
                                            'CHF',
                                            'CLP',
                                            'CNY',
                                            'COP',
                                            'CRC',
                                            'CVE',
                                            'CZK',
                                            'DJF',
                                            'DKK',
                                            'DOP',
                                            'DZD',
                                            'EGP',
                                            'ERN',
                                            'ETB',
                                            'EUR',
                                            'FJD',
                                            'GBP',
                                            'GEL',
                                            'GHS',
                                            'GIP',
                                            'GMD',
                                            'GNF',
                                            'GTQ',
                                            'GYD',
                                            'HKD',
                                            'HNL',
                                            'HRK',
                                            'HTG',
                                            'HUF',
                                            'IDR',
                                            'ILS',
                                            'INR',
                                            'IQD',
                                            'IRR',
                                            'ISK',
                                            'JMD',
                                            'JOD',
                                            'JPY',
                                            'KES',
                                            'KGS',
                                            'KHR',
                                            'KMF',
                                            'KRW',
                                            'KWD',
                                            'KYD',
                                            'KZT',
                                            'LAK',
                                            'LBP',
                                            'LKR',
                                            'LRD',
                                            'LTL',
                                            'LVL',
                                            'LSL',
                                            'LYD',
                                            'MAD',
                                            'MDL',
                                            'MGA',
                                            'MKD',
                                            'MMK',
                                            'MNT',
                                            'MOP',
                                            'MRU',
                                            'MTL',
                                            'MUR',
                                            'MVR',
                                            'MWK',
                                            'MXN',
                                            'MYR',
                                            'MZN',
                                            'NAD',
                                            'NGN',
                                            'NIO',
                                            'NOK',
                                            'NPR',
                                            'NZD',
                                            'OMR',
                                            'PAB',
                                            'PEN',
                                            'PGK',
                                            'PHP',
                                            'PKR',
                                            'PLN',
                                            'PYG',
                                            'QAR',
                                            'RON',
                                            'RSD',
                                            'RUB',
                                            'RWF',
                                            'SAR',
                                            'SBD',
                                            'SCR',
                                            'SDG',
                                            'SEK',
                                            'SGD',
                                            'SRD',
                                            'SSP',
                                            'STN',
                                            'SYP',
                                            'SZL',
                                            'THB',
                                            'TJS',
                                            'TMT',
                                            'TND',
                                            'TOP',
                                            'TRY',
                                            'TTD',
                                            'TWD',
                                            'TZS',
                                            'UAH',
                                            'UGX',
                                            'USD',
                                            'UYU',
                                            'UZS',
                                            'VES',
                                            'VND',
                                            'VUV',
                                            'WST',
                                            'XAF',
                                            'XCD',
                                            'XOF',
                                            'XPF',
                                            'YER',
                                            'ZAR',
                                            'ZMW',
                                        ]),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneTwoMathPropertyRevenueCurrencyOneStaticDefault
                                    ),
                            }),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoMathPropertyRevenueCurrencyDefault),
                    math_property_type: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoMathPropertyTypeDefault),
                    name: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoNameDefault),
                    optionalInFunnel: zod
                        .union([zod.boolean(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoOptionalInFunnelDefault),
                    properties: zod
                        .union([
                            zod.array(
                                zod.union([
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneOperatorDefault
                                            ),
                                        type: zod
                                            .literal('event')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwoLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('person')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwoTypeDefault
                                            )
                                            .describe('Person properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemThreeLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('element')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemThreeTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemThreeValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('event_metadata')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('session')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemFiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        cohort_name: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixCohortNameDefault
                                            ),
                                        key: zod
                                            .literal('id')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixKeyDefault
                                            ),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixLabelDefault
                                            ),
                                        operator: zod
                                            .union([
                                                zod.enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ]),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixOperatorDefault
                                            ),
                                        type: zod
                                            .literal('cohort')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSixTypeDefault
                                            ),
                                        value: zod.number(),
                                    }),
                                    zod.object({
                                        key: zod.union([
                                            zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                            zod.string(),
                                        ]),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('recording')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSevenTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemSevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemEightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('log_entry')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemEightTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemEightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        group_key_names: zod
                                            .union([zod.record(zod.string(), zod.string()), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineGroupKeyNamesDefault
                                            ),
                                        group_type_index: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineGroupTypeIndexDefault
                                            ),
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('group')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemNineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnezeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('feature')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnezeroTypeDefault
                                            )
                                            .describe('Event property with "$feature/" prepended'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnezeroValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string().describe('The key should be the flag ID'),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneoneLabelDefault
                                            ),
                                        operator: zod
                                            .literal('flag_evaluates_to')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneoneOperatorDefault
                                            )
                                            .describe(
                                                'Only flag_evaluates_to operator is allowed for flag dependencies'
                                            ),
                                        type: zod
                                            .literal('flag')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneoneTypeDefault
                                            )
                                            .describe('Feature flag dependency'),
                                        value: zod
                                            .union([zod.boolean(), zod.string()])
                                            .describe('The value can be true, false, or a variant name'),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnetwoLabelDefault
                                            ),
                                        type: zod
                                            .literal('hogql')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnetwoTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnetwoValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        type: zod
                                            .literal('empty')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnethreeTypeDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefourLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefourTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefourValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefiveLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('data_warehouse_person_property')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefiveTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnefiveValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesixLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('error_tracking_issue')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesixTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesixValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesevenLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnesevenValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneeightLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod.enum(['span', 'span_attribute', 'span_resource_attribute']),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOneeightValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnenineLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('revenue_analytics')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnenineTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemOnenineValueDefault
                                            ),
                                    }),
                                    zod.object({
                                        key: zod.string(),
                                        label: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwozeroLabelDefault
                                            ),
                                        operator: zod.enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ]),
                                        type: zod
                                            .literal('workflow_variable')
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwozeroTypeDefault
                                            ),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                                zod.null(),
                                            ])
                                            .default(
                                                catalogMetricsCreateBodyDefinitionOneTwoPropertiesOneItemTwozeroValueDefault
                                            ),
                                    }),
                                ])
                            ),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoPropertiesDefault)
                        .describe('Properties configurable in the interface'),
                    response: zod
                        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoResponseDefault),
                    table_name: zod.string(),
                    timestamp_field: zod.string(),
                    version: zod
                        .union([zod.number(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneTwoVersionDefault)
                        .describe('version of the node, used for schema migrations'),
                }),
                zod.object({
                    connectionId: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeConnectionIdDefault)
                        .describe('Optional direct external data source id for running against a specific source'),
                    explain: zod
                        .union([zod.boolean(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeExplainDefault),
                    filters: zod
                        .union([
                            zod.object({
                                dateRange: zod
                                    .union([
                                        zod.object({
                                            date_from: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeOneDateFromDefault
                                                )
                                                .describe(
                                                    'Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),\n-1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year).'
                                                ),
                                            date_to: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeOneDateToDefault
                                                )
                                                .describe(
                                                    'End of the date range. Same format as date_from. Omit or null for "now".'
                                                ),
                                            explicitDate: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeOneExplicitDateDefault
                                                )
                                                .describe(
                                                    'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeFiltersOneDateRangeDefault),
                                filterTestAccounts: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeFiltersOneFilterTestAccountsDefault
                                    ),
                                properties: zod
                                    .union([
                                        zod.array(
                                            zod.union([
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneLabelDefault
                                                        ),
                                                    operator: zod
                                                        .union([
                                                            zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneOperatorDefault
                                                        ),
                                                    type: zod
                                                        .literal('event')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneTypeDefault
                                                        )
                                                        .describe('Event properties'),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwoLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('person')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwoTypeDefault
                                                        )
                                                        .describe('Person properties'),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwoValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.enum(['tag_name', 'text', 'href', 'selector']),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemThreeLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('element')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemThreeTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemThreeValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFourLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('event_metadata')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFourTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFourValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFiveLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('session')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFiveTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemFiveValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    cohort_name: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixCohortNameDefault
                                                        ),
                                                    key: zod
                                                        .literal('id')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixKeyDefault
                                                        ),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixLabelDefault
                                                        ),
                                                    operator: zod
                                                        .union([
                                                            zod.enum([
                                                                'exact',
                                                                'is_not',
                                                                'icontains',
                                                                'not_icontains',
                                                                'regex',
                                                                'not_regex',
                                                                'gt',
                                                                'gte',
                                                                'lt',
                                                                'lte',
                                                                'is_set',
                                                                'is_not_set',
                                                                'is_date_exact',
                                                                'is_date_before',
                                                                'is_date_after',
                                                                'between',
                                                                'not_between',
                                                                'min',
                                                                'max',
                                                                'in',
                                                                'not_in',
                                                                'is_cleaned_path_exact',
                                                                'flag_evaluates_to',
                                                                'semver_eq',
                                                                'semver_neq',
                                                                'semver_gt',
                                                                'semver_gte',
                                                                'semver_lt',
                                                                'semver_lte',
                                                                'semver_tilde',
                                                                'semver_caret',
                                                                'semver_wildcard',
                                                                'icontains_multi',
                                                                'not_icontains_multi',
                                                            ]),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixOperatorDefault
                                                        ),
                                                    type: zod
                                                        .literal('cohort')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSixTypeDefault
                                                        ),
                                                    value: zod.number(),
                                                }),
                                                zod.object({
                                                    key: zod.union([
                                                        zod.enum(['duration', 'active_seconds', 'inactive_seconds']),
                                                        zod.string(),
                                                    ]),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSevenLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('recording')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSevenTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemSevenValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemEightLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('log_entry')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemEightTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemEightValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    group_key_names: zod
                                                        .union([zod.record(zod.string(), zod.string()), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineGroupKeyNamesDefault
                                                        ),
                                                    group_type_index: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineGroupTypeIndexDefault
                                                        ),
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('group')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemNineValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnezeroLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('feature')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnezeroTypeDefault
                                                        )
                                                        .describe('Event property with "$feature/" prepended'),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnezeroValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string().describe('The key should be the flag ID'),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneoneLabelDefault
                                                        ),
                                                    operator: zod
                                                        .literal('flag_evaluates_to')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneoneOperatorDefault
                                                        )
                                                        .describe(
                                                            'Only flag_evaluates_to operator is allowed for flag dependencies'
                                                        ),
                                                    type: zod
                                                        .literal('flag')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneoneTypeDefault
                                                        )
                                                        .describe('Feature flag dependency'),
                                                    value: zod
                                                        .union([zod.boolean(), zod.string()])
                                                        .describe('The value can be true, false, or a variant name'),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnetwoLabelDefault
                                                        ),
                                                    type: zod
                                                        .literal('hogql')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnetwoTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnetwoValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    type: zod
                                                        .literal('empty')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnethreeTypeDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefourLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('data_warehouse')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefourTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefourValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefiveLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('data_warehouse_person_property')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefiveTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnefiveValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesixLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('error_tracking_issue')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesixTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesixValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesevenLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod.enum(['log', 'log_attribute', 'log_resource_attribute']),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnesevenValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneeightLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod.enum([
                                                        'span',
                                                        'span_attribute',
                                                        'span_resource_attribute',
                                                    ]),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOneeightValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnenineLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('revenue_analytics')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnenineTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemOnenineValueDefault
                                                        ),
                                                }),
                                                zod.object({
                                                    key: zod.string(),
                                                    label: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwozeroLabelDefault
                                                        ),
                                                    operator: zod.enum([
                                                        'exact',
                                                        'is_not',
                                                        'icontains',
                                                        'not_icontains',
                                                        'regex',
                                                        'not_regex',
                                                        'gt',
                                                        'gte',
                                                        'lt',
                                                        'lte',
                                                        'is_set',
                                                        'is_not_set',
                                                        'is_date_exact',
                                                        'is_date_before',
                                                        'is_date_after',
                                                        'between',
                                                        'not_between',
                                                        'min',
                                                        'max',
                                                        'in',
                                                        'not_in',
                                                        'is_cleaned_path_exact',
                                                        'flag_evaluates_to',
                                                        'semver_eq',
                                                        'semver_neq',
                                                        'semver_gt',
                                                        'semver_gte',
                                                        'semver_lt',
                                                        'semver_lte',
                                                        'semver_tilde',
                                                        'semver_caret',
                                                        'semver_wildcard',
                                                        'icontains_multi',
                                                        'not_icontains_multi',
                                                    ]),
                                                    type: zod
                                                        .literal('workflow_variable')
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwozeroTypeDefault
                                                        ),
                                                    value: zod
                                                        .union([
                                                            zod.array(
                                                                zod.union([zod.string(), zod.number(), zod.boolean()])
                                                            ),
                                                            zod.string(),
                                                            zod.number(),
                                                            zod.boolean(),
                                                            zod.null(),
                                                        ])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesOneItemTwozeroValueDefault
                                                        ),
                                                }),
                                            ])
                                        ),
                                        zod.null(),
                                    ])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeFiltersOnePropertiesDefault),
                            }),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeFiltersDefault),
                    kind: zod.literal('HogQLQuery').default(catalogMetricsCreateBodyDefinitionOneThreeKindDefault),
                    modifiers: zod
                        .union([
                            zod.object({
                                bounceRateDurationSeconds: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneBounceRateDurationSecondsDefault
                                    ),
                                bounceRatePageViewMode: zod
                                    .union([
                                        zod.enum(['count_pageviews', 'uniq_urls', 'uniq_page_screen_autocaptures']),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneBounceRatePageViewModeDefault
                                    ),
                                convertToProjectTimezone: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneConvertToProjectTimezoneDefault
                                    ),
                                customChannelTypeRules: zod
                                    .union([
                                        zod.array(
                                            zod.object({
                                                channel_type: zod.string(),
                                                combiner: zod.enum(['AND', 'OR']),
                                                id: zod.string(),
                                                items: zod.array(
                                                    zod.object({
                                                        id: zod.string(),
                                                        key: zod.enum([
                                                            'utm_source',
                                                            'utm_medium',
                                                            'utm_campaign',
                                                            'referring_domain',
                                                            'url',
                                                            'pathname',
                                                            'hostname',
                                                        ]),
                                                        op: zod.enum([
                                                            'exact',
                                                            'is_not',
                                                            'is_set',
                                                            'is_not_set',
                                                            'icontains',
                                                            'not_icontains',
                                                            'regex',
                                                            'not_regex',
                                                        ]),
                                                        value: zod
                                                            .union([zod.string(), zod.array(zod.string()), zod.null()])
                                                            .default(
                                                                catalogMetricsCreateBodyDefinitionOneThreeModifiersOneCustomChannelTypeRulesOneItemItemsItemValueDefault
                                                            ),
                                                    })
                                                ),
                                            })
                                        ),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneCustomChannelTypeRulesDefault
                                    ),
                                dataWarehouseEventsModifiers: zod
                                    .union([
                                        zod.array(
                                            zod.object({
                                                distinct_id_field: zod.string(),
                                                id_field: zod.string(),
                                                table_name: zod.string(),
                                                timestamp_field: zod.string(),
                                            })
                                        ),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneDataWarehouseEventsModifiersDefault
                                    ),
                                debug: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeModifiersOneDebugDefault),
                                forceClickhouseDataSkippingIndexes: zod
                                    .union([zod.array(zod.string()), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneForceClickhouseDataSkippingIndexesDefault
                                    )
                                    .describe(
                                        'If these are provided, the query will fail if these skip indexes are not used'
                                    ),
                                formatCsvAllowDoubleQuotes: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneFormatCsvAllowDoubleQuotesDefault
                                    ),
                                inCohortVia: zod
                                    .union([
                                        zod.enum(['auto', 'leftjoin', 'subquery', 'leftjoin_conjoined']),
                                        zod.null(),
                                    ])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeModifiersOneInCohortViaDefault),
                                inlineCohortCalculation: zod
                                    .union([zod.enum(['off', 'auto', 'always']), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneInlineCohortCalculationDefault
                                    ),
                                materializationMode: zod
                                    .union([
                                        zod.enum(['auto', 'legacy_null_as_string', 'legacy_null_as_null', 'disabled']),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneMaterializationModeDefault
                                    ),
                                materializedColumnsOptimizationMode: zod
                                    .union([zod.enum(['disabled', 'optimized']), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneMaterializedColumnsOptimizationModeDefault
                                    ),
                                optimizeJoinedFilters: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneOptimizeJoinedFiltersDefault
                                    ),
                                optimizeProjections: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneOptimizeProjectionsDefault
                                    ),
                                personsArgMaxVersion: zod
                                    .union([zod.enum(['auto', 'v1', 'v2']), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePersonsArgMaxVersionDefault
                                    ),
                                personsJoinMode: zod
                                    .union([zod.enum(['inner', 'left']), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePersonsJoinModeDefault
                                    ),
                                personsOnEventsMode: zod
                                    .union([
                                        zod.enum([
                                            'disabled',
                                            'person_id_no_override_properties_on_events',
                                            'person_id_override_properties_on_events',
                                            'person_id_override_properties_joined',
                                        ]),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePersonsOnEventsModeDefault
                                    ),
                                propertyGroupsMode: zod
                                    .union([zod.enum(['enabled', 'disabled', 'optimized']), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOnePropertyGroupsModeDefault
                                    ),
                                s3TableUseInvalidColumns: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneS3TableUseInvalidColumnsDefault
                                    ),
                                sessionIdPushdown: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionIdPushdownDefault
                                    )
                                    .describe(
                                        'Push a `session_id_v7 IN (SELECT … FROM events WHERE …)` predicate into the raw_sessions subquery to limit aggregation to sessions that participate in the outer events filter.'
                                    ),
                                sessionPropertyPreAggregation: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionPropertyPreAggregationDefault
                                    )
                                    .describe(
                                        'Pre-filter raw_sessions aggregation by `session_id_v7 IN (cheap pre-aggregation that only materializes the columns referenced by the outer-WHERE session predicate)`. Useful when the breakdown/SELECT pulls in many session columns (e.g. `$channel_type`) but the filter only references one (e.g. `$entry_current_url`).'
                                    ),
                                sessionTableVersion: zod
                                    .union([zod.enum(['auto', 'v1', 'v2', 'v3']), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionTableVersionDefault
                                    ),
                                sessionsV2JoinMode: zod
                                    .union([zod.enum(['string', 'uuid']), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneSessionsV2JoinModeDefault
                                    ),
                                timings: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeModifiersOneTimingsDefault),
                                useMaterializedViews: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUseMaterializedViewsDefault
                                    ),
                                usePreaggregatedIntermediateResults: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUsePreaggregatedIntermediateResultsDefault
                                    ),
                                usePreaggregatedTableTransforms: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUsePreaggregatedTableTransformsDefault
                                    )
                                    .describe(
                                        'Try to automatically convert HogQL queries to use preaggregated tables at the AST level *'
                                    ),
                                useWebAnalyticsPreAggregatedTables: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeModifiersOneUseWebAnalyticsPreAggregatedTablesDefault
                                    ),
                            }),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeModifiersDefault)
                        .describe('Modifiers used when performing the query'),
                    name: zod
                        .union([zod.string(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeNameDefault)
                        .describe('Client provided name of the query'),
                    query: zod.string(),
                    response: zod
                        .union([
                            zod.object({
                                clickhouse: zod
                                    .union([zod.string(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneClickhouseDefault)
                                    .describe('Executed ClickHouse query'),
                                columns: zod
                                    .union([zod.array(zod.unknown()), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneColumnsDefault)
                                    .describe('Returned columns'),
                                error: zod
                                    .union([zod.string(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneErrorDefault)
                                    .describe(
                                        "Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."
                                    ),
                                explain: zod
                                    .union([zod.array(zod.string()), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneExplainDefault)
                                    .describe('Query explanation output'),
                                hasMore: zod
                                    .union([zod.boolean(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneHasMoreDefault),
                                hogql: zod
                                    .union([zod.string(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneHogqlDefault)
                                    .describe('Generated HogQL query.'),
                                limit: zod
                                    .union([zod.number(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneLimitDefault),
                                metadata: zod
                                    .union([
                                        zod.object({
                                            ch_table_names: zod
                                                .union([zod.array(zod.string()), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneChTableNamesDefault
                                                ),
                                            errors: zod.array(
                                                zod.object({
                                                    end: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneErrorsItemEndDefault
                                                        ),
                                                    fix: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneErrorsItemFixDefault
                                                        ),
                                                    message: zod.string(),
                                                    start: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneErrorsItemStartDefault
                                                        ),
                                                })
                                            ),
                                            isUsingIndices: zod
                                                .union([zod.enum(['undecisive', 'no', 'partial', 'yes']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneIsUsingIndicesDefault
                                                ),
                                            isValid: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneIsValidDefault
                                                ),
                                            notices: zod.array(
                                                zod.object({
                                                    end: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneNoticesItemEndDefault
                                                        ),
                                                    fix: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneNoticesItemFixDefault
                                                        ),
                                                    message: zod.string(),
                                                    start: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneNoticesItemStartDefault
                                                        ),
                                                })
                                            ),
                                            query: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneQueryDefault
                                                ),
                                            table_names: zod
                                                .union([zod.array(zod.string()), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneTableNamesDefault
                                                ),
                                            warnings: zod.array(
                                                zod.object({
                                                    end: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneWarningsItemEndDefault
                                                        ),
                                                    fix: zod
                                                        .union([zod.string(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneWarningsItemFixDefault
                                                        ),
                                                    message: zod.string(),
                                                    start: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataOneWarningsItemStartDefault
                                                        ),
                                                })
                                            ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneMetadataDefault)
                                    .describe('Query metadata output'),
                                modifiers: zod
                                    .union([
                                        zod.object({
                                            bounceRateDurationSeconds: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneBounceRateDurationSecondsDefault
                                                ),
                                            bounceRatePageViewMode: zod
                                                .union([
                                                    zod.enum([
                                                        'count_pageviews',
                                                        'uniq_urls',
                                                        'uniq_page_screen_autocaptures',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneBounceRatePageViewModeDefault
                                                ),
                                            convertToProjectTimezone: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneConvertToProjectTimezoneDefault
                                                ),
                                            customChannelTypeRules: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            channel_type: zod.string(),
                                                            combiner: zod.enum(['AND', 'OR']),
                                                            id: zod.string(),
                                                            items: zod.array(
                                                                zod.object({
                                                                    id: zod.string(),
                                                                    key: zod.enum([
                                                                        'utm_source',
                                                                        'utm_medium',
                                                                        'utm_campaign',
                                                                        'referring_domain',
                                                                        'url',
                                                                        'pathname',
                                                                        'hostname',
                                                                    ]),
                                                                    op: zod.enum([
                                                                        'exact',
                                                                        'is_not',
                                                                        'is_set',
                                                                        'is_not_set',
                                                                        'icontains',
                                                                        'not_icontains',
                                                                        'regex',
                                                                        'not_regex',
                                                                    ]),
                                                                    value: zod
                                                                        .union([
                                                                            zod.string(),
                                                                            zod.array(zod.string()),
                                                                            zod.null(),
                                                                        ])
                                                                        .default(
                                                                            catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneCustomChannelTypeRulesOneItemItemsItemValueDefault
                                                                        ),
                                                                })
                                                            ),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneCustomChannelTypeRulesDefault
                                                ),
                                            dataWarehouseEventsModifiers: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            distinct_id_field: zod.string(),
                                                            id_field: zod.string(),
                                                            table_name: zod.string(),
                                                            timestamp_field: zod.string(),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneDataWarehouseEventsModifiersDefault
                                                ),
                                            debug: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneDebugDefault
                                                ),
                                            forceClickhouseDataSkippingIndexes: zod
                                                .union([zod.array(zod.string()), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneForceClickhouseDataSkippingIndexesDefault
                                                )
                                                .describe(
                                                    'If these are provided, the query will fail if these skip indexes are not used'
                                                ),
                                            formatCsvAllowDoubleQuotes: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneFormatCsvAllowDoubleQuotesDefault
                                                ),
                                            inCohortVia: zod
                                                .union([
                                                    zod.enum(['auto', 'leftjoin', 'subquery', 'leftjoin_conjoined']),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneInCohortViaDefault
                                                ),
                                            inlineCohortCalculation: zod
                                                .union([zod.enum(['off', 'auto', 'always']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneInlineCohortCalculationDefault
                                                ),
                                            materializationMode: zod
                                                .union([
                                                    zod.enum([
                                                        'auto',
                                                        'legacy_null_as_string',
                                                        'legacy_null_as_null',
                                                        'disabled',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneMaterializationModeDefault
                                                ),
                                            materializedColumnsOptimizationMode: zod
                                                .union([zod.enum(['disabled', 'optimized']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneMaterializedColumnsOptimizationModeDefault
                                                ),
                                            optimizeJoinedFilters: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneOptimizeJoinedFiltersDefault
                                                ),
                                            optimizeProjections: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneOptimizeProjectionsDefault
                                                ),
                                            personsArgMaxVersion: zod
                                                .union([zod.enum(['auto', 'v1', 'v2']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePersonsArgMaxVersionDefault
                                                ),
                                            personsJoinMode: zod
                                                .union([zod.enum(['inner', 'left']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePersonsJoinModeDefault
                                                ),
                                            personsOnEventsMode: zod
                                                .union([
                                                    zod.enum([
                                                        'disabled',
                                                        'person_id_no_override_properties_on_events',
                                                        'person_id_override_properties_on_events',
                                                        'person_id_override_properties_joined',
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePersonsOnEventsModeDefault
                                                ),
                                            propertyGroupsMode: zod
                                                .union([zod.enum(['enabled', 'disabled', 'optimized']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOnePropertyGroupsModeDefault
                                                ),
                                            s3TableUseInvalidColumns: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneS3TableUseInvalidColumnsDefault
                                                ),
                                            sessionIdPushdown: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionIdPushdownDefault
                                                )
                                                .describe(
                                                    'Push a `session_id_v7 IN (SELECT … FROM events WHERE …)` predicate into the raw_sessions subquery to limit aggregation to sessions that participate in the outer events filter.'
                                                ),
                                            sessionPropertyPreAggregation: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionPropertyPreAggregationDefault
                                                )
                                                .describe(
                                                    'Pre-filter raw_sessions aggregation by `session_id_v7 IN (cheap pre-aggregation that only materializes the columns referenced by the outer-WHERE session predicate)`. Useful when the breakdown/SELECT pulls in many session columns (e.g. `$channel_type`) but the filter only references one (e.g. `$entry_current_url`).'
                                                ),
                                            sessionTableVersion: zod
                                                .union([zod.enum(['auto', 'v1', 'v2', 'v3']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionTableVersionDefault
                                                ),
                                            sessionsV2JoinMode: zod
                                                .union([zod.enum(['string', 'uuid']), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneSessionsV2JoinModeDefault
                                                ),
                                            timings: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneTimingsDefault
                                                ),
                                            useMaterializedViews: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUseMaterializedViewsDefault
                                                ),
                                            usePreaggregatedIntermediateResults: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUsePreaggregatedIntermediateResultsDefault
                                                ),
                                            usePreaggregatedTableTransforms: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUsePreaggregatedTableTransformsDefault
                                                )
                                                .describe(
                                                    'Try to automatically convert HogQL queries to use preaggregated tables at the AST level *'
                                                ),
                                            useWebAnalyticsPreAggregatedTables: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersOneUseWebAnalyticsPreAggregatedTablesDefault
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneModifiersDefault)
                                    .describe('Modifiers used when performing the query'),
                                offset: zod
                                    .union([zod.number(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneOffsetDefault),
                                query: zod
                                    .union([zod.string(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryDefault)
                                    .describe('Input query string'),
                                query_status: zod
                                    .union([
                                        zod.object({
                                            complete: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneCompleteDefault
                                                )
                                                .describe(
                                                    'Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set.'
                                                ),
                                            dashboard_id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneDashboardIdDefault
                                                ),
                                            end_time: zod
                                                .union([zod.iso.datetime({ offset: true }), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneEndTimeDefault
                                                )
                                                .describe(
                                                    'When did the query execution task finish (whether successfully or not).'
                                                ),
                                            error: zod
                                                .union([zod.boolean(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneErrorDefault
                                                )
                                                .describe(
                                                    'If the query failed, this will be set to true. More information can be found in the error_message field.'
                                                ),
                                            error_message: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneErrorMessageDefault
                                                ),
                                            expiration_time: zod
                                                .union([zod.iso.datetime({ offset: true }), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneExpirationTimeDefault
                                                ),
                                            id: zod.string(),
                                            insight_id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneInsightIdDefault
                                                ),
                                            labels: zod
                                                .union([zod.array(zod.string()), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneLabelsDefault
                                                ),
                                            pickup_time: zod
                                                .union([zod.iso.datetime({ offset: true }), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOnePickupTimeDefault
                                                )
                                                .describe('When was the query execution task picked up by a worker.'),
                                            query_async: zod
                                                .boolean()
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneQueryAsyncDefault
                                                )
                                                .describe('ONLY async queries use QueryStatus.'),
                                            query_progress: zod
                                                .union([
                                                    zod.object({
                                                        active_cpu_time: zod.number(),
                                                        bytes_read: zod.number(),
                                                        estimated_rows_total: zod.number(),
                                                        rows_read: zod.number(),
                                                        time_elapsed: zod.number(),
                                                    }),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneQueryProgressDefault
                                                ),
                                            results: zod
                                                .unknown()
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneResultsDefault
                                                ),
                                            start_time: zod
                                                .union([zod.iso.datetime({ offset: true }), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneStartTimeDefault
                                                )
                                                .describe('When was query execution task enqueued.'),
                                            task_id: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusOneTaskIdDefault
                                                ),
                                            team_id: zod.number(),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneQueryStatusDefault)
                                    .describe(
                                        'Query status indicates whether next to the provided data, a query is still running.'
                                    ),
                                resolved_date_range: zod
                                    .union([
                                        zod.object({
                                            date_from: zod.iso.datetime({ offset: true }),
                                            date_to: zod.iso.datetime({ offset: true }),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        catalogMetricsCreateBodyDefinitionOneThreeResponseOneResolvedDateRangeDefault
                                    )
                                    .describe('The date range used for the query'),
                                results: zod.array(zod.unknown()),
                                timings: zod
                                    .union([
                                        zod.array(
                                            zod.object({
                                                k: zod.string().describe("Key. Shortened to 'k' to save on data."),
                                                t: zod
                                                    .number()
                                                    .describe("Time in seconds. Shortened to 't' to save on data."),
                                            })
                                        ),
                                        zod.null(),
                                    ])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneTimingsDefault)
                                    .describe('Measured timings for different parts of the query generation process'),
                                types: zod
                                    .union([zod.array(zod.unknown()), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeResponseOneTypesDefault)
                                    .describe('Types of returned columns'),
                            }),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeResponseDefault),
                    sendRawQuery: zod
                        .union([zod.boolean(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeSendRawQueryDefault)
                        .describe(
                            'Run the selected connection query directly without translating it through HogQL first'
                        ),
                    tags: zod
                        .union([
                            zod.object({
                                name: zod
                                    .union([zod.string(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeTagsOneNameDefault)
                                    .describe('Name of the query, preferably unique. For example web_analytics_vitals'),
                                productKey: zod
                                    .union([zod.string(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeTagsOneProductKeyDefault)
                                    .describe(
                                        "Product responsible for this query. Use string, there's no need to churn the Schema when we add a new product *"
                                    ),
                                scene: zod
                                    .union([zod.string(), zod.null()])
                                    .default(catalogMetricsCreateBodyDefinitionOneThreeTagsOneSceneDefault)
                                    .describe(
                                        "Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a new Scene *"
                                    ),
                            }),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeTagsDefault),
                    values: zod
                        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeValuesDefault)
                        .describe('Constant values that can be referenced with the {placeholder} syntax in the query'),
                    variables: zod
                        .union([
                            zod.record(
                                zod.string(),
                                zod.object({
                                    code_name: zod.string(),
                                    isNull: zod
                                        .union([zod.boolean(), zod.null()])
                                        .default(catalogMetricsCreateBodyDefinitionOneThreeVariablesOneIsNullDefault),
                                    value: zod
                                        .unknown()
                                        .default(catalogMetricsCreateBodyDefinitionOneThreeVariablesOneValueDefault),
                                    variableId: zod.string(),
                                })
                            ),
                            zod.null(),
                        ])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeVariablesDefault)
                        .describe('Variables to be substituted into the query'),
                    version: zod
                        .union([zod.number(), zod.null()])
                        .default(catalogMetricsCreateBodyDefinitionOneThreeVersionDefault)
                        .describe('version of the node, used for schema migrations'),
                }),
            ])
            .describe(
                'Schema for `CatalogMetric.definition` — same shape as an `Insight.query.series` item.\n\nA metric is computed from exactly one of: an event count (EventsNode), a data-warehouse\naggregate (DataWarehouseNode), or a raw HogQL query (HogQLQuery). All three carry a\n`kind` discriminator so consumers can route on shape without parsing the body.'
            )
            .describe(
                'How the metric is computed. Exactly one of `EventsNode` (event count with math and filters), `DataWarehouseNode` (warehouse-table aggregate), or `HogQLQuery` (raw HogQL SQL) — the same shape an `Insight.query.series` item uses, discriminated by the inner `kind` field. Example: `{"kind": "EventsNode", "event": "signup_completed", "math": "dau"}`.'
            ),
        generator_model: zod
            .string()
            .max(catalogMetricsCreateBodyGeneratorModelMax)
            .nullish()
            .describe(
                'Model that proposed the metric — e.g. `claude-opus-4-7`. Stored on the bound CatalogNode for auditing. Leave null when humans author the metric.'
            ),
        confidence: zod
            .number()
            .min(catalogMetricsCreateBodyConfidenceMin)
            .max(catalogMetricsCreateBodyConfidenceMax)
            .nullish()
            .describe(
                "Agent's confidence (0..1) that this metric is correctly defined and worth showing to humans. Surfaces as a draft/confirmed indicator on the bound CatalogNode. Use 1.0 for metrics derived directly from a popular dashboard's saved query; lower values for inferred or aggregated proposals."
            ),
    })
    .describe(
        'Body for catalog-metrics-create. team_id is taken from the URL, not the body.\n\nIdempotent on (team, name): re-posting with the same name updates description and\ndefinition in place. The bound CatalogNode(kind=metric) is created on first insert\nand reused on update — agents can re-propose metrics across traversal runs safely.'
    )

/**
 * Upsert a catalog node and its agent-authored descriptions.
 */
export const CatalogNodesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const catalogNodesCreateBodyNameMax = 400

export const catalogNodesCreateBodySemanticRoleMax = 64

export const catalogNodesCreateBodyBusinessDomainMax = 64

export const catalogNodesCreateBodyTagsItemMax = 64

export const catalogNodesCreateBodyGeneratorModelMax = 64

export const catalogNodesCreateBodyConfidenceMin = 0
export const catalogNodesCreateBodyConfidenceMax = 1

export const CatalogNodesCreateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum(['warehouse_table', 'saved_query', 'system_table', 'posthog_table'])
            .describe(
                '* `warehouse_table` - warehouse_table\n* `saved_query` - saved_query\n* `system_table` - system_table\n* `posthog_table` - posthog_table'
            )
            .describe(
                'What kind of catalog entry this is. `warehouse_table` for an imported data warehouse table, `saved_query` for a derived view, `system_table` for a built-in PostHog system table like `events` or `persons`, `posthog_table` for other first-party tables.\n\n* `warehouse_table` - warehouse_table\n* `saved_query` - saved_query\n* `system_table` - system_table\n* `posthog_table` - posthog_table'
            ),
        name: zod
            .string()
            .max(catalogNodesCreateBodyNameMax)
            .describe(
                'Stable identifier for the node, unique per (team, kind). For warehouse tables this is the imported table name (e.g. `stripe_charges`). For system tables use the canonical name (e.g. `events`). The agent looks nodes up by name before upserting, so keep this stable across runs.'
            ),
        warehouse_table_id: zod
            .uuid()
            .nullish()
            .describe(
                'Set when `kind=warehouse_table` to bind this node to the backing `DataWarehouseTable` row. Used for cascade cleanup when the warehouse table is deleted. Leave null for system/posthog tables.'
            ),
        saved_query_id: zod
            .uuid()
            .nullish()
            .describe(
                'Set when `kind=saved_query` to bind this node to the backing `DataWarehouseSavedQuery` row. Leave null for non-saved-query kinds.'
            ),
        synthetic_description: zod
            .string()
            .nullish()
            .describe(
                'Markdown description of what this table contains, when to use it, caveats, and how it relates to other tables. Written by the agent or human. Becomes the primary signal future agent runs use to pick the right table for a question.'
            ),
        semantic_role: zod
            .string()
            .max(catalogNodesCreateBodySemanticRoleMax)
            .nullish()
            .describe(
                "Short tag for the table's role in the business model — e.g. `fact`, `dimension`, `bridge`, `event_source`, `identity`. Helps the agent reason about join cardinality and aggregation safety."
            ),
        business_domain: zod
            .string()
            .max(catalogNodesCreateBodyBusinessDomainMax)
            .nullish()
            .describe(
                'Domain this table belongs to — e.g. `billing`, `crm`, `product_usage`, `support`. Used to group related tables in discovery and to scope cross-source queries.'
            ),
        tags: zod
            .array(zod.string().max(catalogNodesCreateBodyTagsItemMax))
            .optional()
            .describe(
                'Free-form tags for filtering and grouping. Lowercase, short. Examples: `pii`, `derived`, `incremental`, `stripe`, `canonical`.'
            ),
        generator_model: zod
            .string()
            .max(catalogNodesCreateBodyGeneratorModelMax)
            .nullish()
            .describe(
                'Identifier of the model that produced this row when generated by an agent — e.g. `claude-opus-4-7`. Leave null when humans author the description. Used for auditing autofill quality over time.'
            ),
        confidence: zod
            .number()
            .min(catalogNodesCreateBodyConfidenceMin)
            .max(catalogNodesCreateBodyConfidenceMax)
            .nullish()
            .describe(
                "Agent's confidence (0..1) in the description and semantic tagging it just wrote. Surfaces as a draft/confirmed indicator and lets review workflows prioritize low-confidence rows."
            ),
    })
    .describe('Body for catalog-nodes-create. team_id is taken from the URL, not the body.')

/**
 * Propose a relationship between two catalog nodes.
 */
export const CatalogRelationshipsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const catalogRelationshipsCreateBodyConfidenceMin = 0
export const catalogRelationshipsCreateBodyConfidenceMax = 1

export const catalogRelationshipsCreateBodyReasoningDefault = ``
export const catalogRelationshipsCreateBodyGeneratorModelMax = 64

export const CatalogRelationshipsCreateBody = /* @__PURE__ */ zod
    .object({
        source_node_id: zod
            .string()
            .describe('ID of the node the relationship originates from — e.g. the fact table, source side of a join.'),
        target_node_id: zod
            .string()
            .describe(
                'ID of the node the relationship points to. For joins this is the other table; for foreign keys, the referenced table.'
            ),
        kind: zod
            .enum(['foreign_key', 'same_entity', 'lineage', 'declared_join', 'join_candidate', 'depends_on'])
            .describe(
                '* `foreign_key` - foreign_key\n* `same_entity` - same_entity\n* `lineage` - lineage\n* `declared_join` - declared_join\n* `join_candidate` - join_candidate\n* `depends_on` - depends_on'
            )
            .describe(
                "Relationship type. `foreign_key` when the source column references a target PK. `same_entity` when two columns identify the same business object (Stripe.customer_id ≈ Postgres.users.id). `lineage` when the target table is derived from the source (data-flow lineage). `declared_join` for an officially supported join. `join_candidate` for an inferred-but-unconfirmed join. `depends_on` for a logical dependency that isn't data-flow lineage (e.g. a metric built from an event definition or property).\n\n* `foreign_key` - foreign_key\n* `same_entity` - same_entity\n* `lineage` - lineage\n* `declared_join` - declared_join\n* `join_candidate` - join_candidate\n* `depends_on` - depends_on"
            ),
        confidence: zod
            .number()
            .min(catalogRelationshipsCreateBodyConfidenceMin)
            .max(catalogRelationshipsCreateBodyConfidenceMax)
            .describe(
                "Agent's confidence (0..1) that this relationship is correct. Drives the review queue — low-confidence edges surface for human approval before agents trust them for joins."
            ),
        source_column_id: zod
            .uuid()
            .nullish()
            .describe(
                'Narrows the source side to a specific column. Set for foreign-key and join edges; null for table-level lineage.'
            ),
        target_column_id: zod
            .uuid()
            .nullish()
            .describe('Narrows the target side to a specific column. Same semantics as source_column_id.'),
        reasoning: zod
            .string()
            .default(catalogRelationshipsCreateBodyReasoningDefault)
            .describe(
                'Free-text justification for the proposal — the data points or column-name signals the agent used. Surfaces in the review UI so a human can decide whether to accept or reject.'
            ),
        discovered_in_run_id: zod
            .uuid()
            .nullish()
            .describe(
                'ID of the CatalogTraversalRun this relationship was discovered in. Leave null for ad-hoc proposals.'
            ),
        generator_model: zod
            .string()
            .max(catalogRelationshipsCreateBodyGeneratorModelMax)
            .nullish()
            .describe('Model that proposed the relationship — same convention as on nodes and columns.'),
    })
    .describe('Body for catalog-relationships-create. Always lands in PROPOSED status until reviewed.')
