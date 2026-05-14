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
 * Upsert a catalog entity by name. The clustering agent calls this for each
cluster it proposes.
 */
export const CatalogEntitiesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const catalogEntitiesCreateBodyNameMax = 200

export const catalogEntitiesCreateBodyConfidenceMin = 0
export const catalogEntitiesCreateBodyConfidenceMax = 1

export const catalogEntitiesCreateBodyReasoningDefault = ``
export const catalogEntitiesCreateBodyGeneratorModelMax = 64

export const CatalogEntitiesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(catalogEntitiesCreateBodyNameMax)
            .describe(
                'Display name for this entity, e.g. `Customer`, `Order`, `Subscription`. Must be unique per team. Re-calling with the same name updates the row in place rather than creating a duplicate.'
            ),
        description: zod
            .string()
            .nullish()
            .describe('What this entity represents in the business. Markdown supported.'),
        member_node_ids: zod
            .array(zod.string())
            .optional()
            .describe(
                'IDs of CatalogNodes that back this entity (e.g. `stripe_customers` + `auth_users` for the Customer entity). Look node ids up via `system.tables`.'
            ),
        confidence: zod
            .number()
            .min(catalogEntitiesCreateBodyConfidenceMin)
            .max(catalogEntitiesCreateBodyConfidenceMax)
            .nullish()
            .describe('Agent confidence (0..1) that this is a real business entity grouping.'),
        reasoning: zod
            .string()
            .default(catalogEntitiesCreateBodyReasoningDefault)
            .describe('Free-text justification — which signals the agent used to identify the cluster.'),
        generator_model: zod
            .string()
            .max(catalogEntitiesCreateBodyGeneratorModelMax)
            .nullish()
            .describe('Identifier of the LLM that proposed this entity, e.g. `claude-opus-4-7`.'),
    })
    .describe(
        'Body for catalog-entities create. Idempotent on (team, name) — the clustering\nagent calls this for each cluster it proposes.'
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
            .enum(['foreign_key', 'same_entity', 'lineage', 'declared_join', 'join_candidate'])
            .describe(
                '* `foreign_key` - foreign_key\n* `same_entity` - same_entity\n* `lineage` - lineage\n* `declared_join` - declared_join\n* `join_candidate` - join_candidate'
            )
            .describe(
                'Relationship type. `foreign_key` when the source column references a target PK. `same_entity` when two columns identify the same business object (Stripe.customer_id ≈ Postgres.users.id). `lineage` when the target table is derived from the source. `declared_join` for an officially supported join. `join_candidate` for an inferred-but-unconfirmed join.\n\n* `foreign_key` - foreign_key\n* `same_entity` - same_entity\n* `lineage` - lineage\n* `declared_join` - declared_join\n* `join_candidate` - join_candidate'
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
