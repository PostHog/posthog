/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
 * config versions, dry-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Backs the in-product score lab scene; run/save/activate share the classifier machinery
 * in products.growth.backend.enrichment.lab with the batch runner, so a dry run and a
 * shadow run compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const GrowthScoreLabActivateCreateBody = /* @__PURE__ */ zod.object({
    config_id: zod.uuid().describe('Prompt config id to activate for its label.'),
})

/**
 * One JSON object per line: a verdict row as each LLM call completes, then a final {summary: {classified, unknown, errors}} line. A legacy config (no output_fields) emits {company, domain, verdict, confidence, reasoning} rows; a configurable output schema (output_fields set) emits {company, domain, outputs: {<key>: value, ...}} rows instead. When input_query is set, rows are built from that HogQL query (capped at `sample`) instead of recently archived orgs. Persists nothing - spends real LLM money, so sample is capped at 100.
 * @summary Stream classifier verdicts for an unsaved draft config against recent archived orgs or a HogQL input query.
 */
export const growthScoreLabRunCreateBodyLabelMax = 128

export const growthScoreLabRunCreateBodyModelMax = 128

export const growthScoreLabRunCreateBodySampleDefault = 10
export const growthScoreLabRunCreateBodySampleMax = 100

export const growthScoreLabRunCreateBodyContainsDefault = ``

export const GrowthScoreLabRunCreateBody = /* @__PURE__ */ zod.object({
    label: zod
        .string()
        .max(growthScoreLabRunCreateBodyLabelMax)
        .describe(
            'Label this config computes, e.g. ai_pilled. Need not already exist - run classifies against an in-memory config only and persists nothing.'
        ),
    prompt_text: zod.string().describe('System prompt; {email} is replaced with the signup email domain at runtime.'),
    model: zod
        .string()
        .max(growthScoreLabRunCreateBodyModelMax)
        .describe(
            'Gateway model to classify with, routed through the LLM gateway. Must be a curated model (see GET \/models\/), a model the gateway currently lists, or one already persisted on this label.'
        ),
    input_fields: zod
        .array(zod.string())
        .optional()
        .describe(
            'Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Ignored when input_query is set.'
        ),
    input_query: zod
        .string()
        .nullish()
        .describe(
            "HogQL SELECT defining classifier input rows, an alternative to input_fields. When set, rows are built from this query (capped at `sample` rows) instead of recently archived orgs; 'contains' is ignored. Parsed and validated on submit but never executed until \/run\/ actually runs."
        ),
    output_fields: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe(
                        "Output key, e.g. ai_pilled. Must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs' (reserved for provenance)."
                    ),
                type: zod
                    .enum(['boolean', 'number', 'string'])
                    .describe('Value type the LLM must return for this key.'),
                description: zod
                    .string()
                    .optional()
                    .describe('Shown to the LLM to describe what this key means. Optional.'),
            })
        )
        .optional()
        .describe(
            "Configurable output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. Empty (the default) means the legacy output shape ({<label>: boolean, confidence: number 0-1, reasoning: string}). Keys must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs'."
        ),
    sample: zod
        .number()
        .min(1)
        .max(growthScoreLabRunCreateBodySampleMax)
        .default(growthScoreLabRunCreateBodySampleDefault)
        .describe(
            'Number of rows to classify (1-100): recent archived orgs, or HogQL query rows when input_query is set. Each sampled row costs one LLM call, so keep this bounded during iteration.'
        ),
    contains: zod
        .string()
        .default(growthScoreLabRunCreateBodyContainsDefault)
        .describe(
            'Optional case-insensitive substring filter on the archived company or organization name. Ignored when input_query is set.'
        ),
})

/**
 * Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
 * config versions, dry-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Backs the in-product score lab scene; run/save/activate share the classifier machinery
 * in products.growth.backend.enrichment.lab with the batch runner, so a dry run and a
 * shadow run compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const growthScoreLabSaveCreateBodyLabelMax = 128

export const growthScoreLabSaveCreateBodyVersionMax = 128

export const growthScoreLabSaveCreateBodyModelMax = 128

export const GrowthScoreLabSaveCreateBody = /* @__PURE__ */ zod.object({
    label: zod
        .string()
        .max(growthScoreLabSaveCreateBodyLabelMax)
        .describe('Label this config computes, e.g. ai_pilled.'),
    version: zod
        .string()
        .max(growthScoreLabSaveCreateBodyVersionMax)
        .describe('Human-readable classifier version, e.g. ai-pilled-clay-v2. Must be unique per label.'),
    prompt_text: zod.string().describe('System prompt; {email} is replaced with the signup email domain at runtime.'),
    model: zod
        .string()
        .max(growthScoreLabSaveCreateBodyModelMax)
        .describe(
            'Gateway model to classify with, routed through the LLM gateway. Must be a curated model (see GET \/models\/), a model the gateway currently lists, or one already persisted on this label.'
        ),
    input_fields: zod
        .array(zod.string())
        .optional()
        .describe(
            'Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Ignored when input_query is set.'
        ),
    input_query: zod
        .string()
        .nullish()
        .describe(
            'HogQL SELECT defining classifier input rows, an alternative to input_fields. Parsed and validated on save but never executed - execution only happens on \/run\/.'
        ),
    output_fields: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe(
                        "Output key, e.g. ai_pilled. Must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs' (reserved for provenance)."
                    ),
                type: zod
                    .enum(['boolean', 'number', 'string'])
                    .describe('Value type the LLM must return for this key.'),
                description: zod
                    .string()
                    .optional()
                    .describe('Shown to the LLM to describe what this key means. Optional.'),
            })
        )
        .optional()
        .describe(
            "Configurable output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. Empty (the default) means the legacy output shape ({<label>: boolean, confidence: number 0-1, reasoning: string}). Keys must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs'."
        ),
})
