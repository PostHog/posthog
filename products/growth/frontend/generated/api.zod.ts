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
 * Staff-only, unscoped API for the enrichment AI enrichment: browse labels and their prompt
 * config versions, test-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const GrowthAiEnrichmentActivateCreateBody = /* @__PURE__ */ zod.object({
    config_id: zod.uuid().describe('Prompt config id to activate for its label.'),
})

/**
 * One JSON object per line: a {company, domain, inputs, outputs: {<key>: value, ...}, meta} row as each LLM call completes, keyed by the submitted output_fields, then a final {summary: {classified, unknown, errors}} line. A run that fails partway ends with {error, aborted: true} instead of a summary. Persists nothing - spends real LLM money, so sample is capped at 10 and the endpoint is rate limited.
 * @summary Stream classifier verdicts for an unsaved draft config against recently archived orgs.
 */
export const growthAiEnrichmentRunCreateBodyLabelMax = 128

export const growthAiEnrichmentRunCreateBodyPromptTextMax = 20000

export const growthAiEnrichmentRunCreateBodyModelMax = 128

export const growthAiEnrichmentRunCreateBodyOutputFieldsItemKeyRegExp = new RegExp('^[a-z][a-z0-9_]\*$')
export const growthAiEnrichmentRunCreateBodyOutputFieldsItemDescriptionDefault = ``
export const growthAiEnrichmentRunCreateBodyOutputFieldsItemDescriptionMax = 400

export const growthAiEnrichmentRunCreateBodySampleDefault = 5
export const growthAiEnrichmentRunCreateBodySampleMax = 10

export const GrowthAiEnrichmentRunCreateBody = /* @__PURE__ */ zod.object({
    label: zod
        .string()
        .max(growthAiEnrichmentRunCreateBodyLabelMax)
        .describe(
            'Label this draft config computes, e.g. ai_pilled. Need not already exist - run classifies against an in-memory config only and persists nothing.'
        ),
    prompt_text: zod
        .string()
        .max(growthAiEnrichmentRunCreateBodyPromptTextMax)
        .describe(
            'System prompt; {email} is replaced with the signup email domain at runtime. At most 20000 characters.'
        ),
    model: zod
        .string()
        .max(growthAiEnrichmentRunCreateBodyModelMax)
        .describe(
            'Gateway model to classify with, routed through the LLM gateway. See GET \/models\/ for what it serves.'
        ),
    input_fields: zod
        .array(zod.string())
        .optional()
        .describe(
            'Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Every selected value reaches the LLM and is then stored on the result indefinitely, so keep this list intentional.'
        ),
    output_fields: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .regex(growthAiEnrichmentRunCreateBodyOutputFieldsItemKeyRegExp)
                    .describe(
                        'Output key, e.g. ai_pilled. Lowercase, starts with a letter, letters\/digits\/underscore only.'
                    ),
                type: zod
                    .enum(['boolean', 'number', 'string'])
                    .describe('\* `boolean` - boolean\n\* `number` - number\n\* `string` - string')
                    .describe(
                        'Value type the LLM must return for this key.\n\n\* `boolean` - boolean\n\* `number` - number\n\* `string` - string'
                    ),
                description: zod
                    .string()
                    .max(growthAiEnrichmentRunCreateBodyOutputFieldsItemDescriptionMax)
                    .default(growthAiEnrichmentRunCreateBodyOutputFieldsItemDescriptionDefault)
                    .describe('Shown to the LLM to describe what this key means. At most 400 characters.'),
            })
        )
        .describe(
            "Output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. This is the classifier's entire output contract - the label is a human name and is never an output key, so renaming a label changes nothing about what a version computes. Keys must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs'. At most 20 fields."
        ),
    sample: zod
        .number()
        .min(1)
        .max(growthAiEnrichmentRunCreateBodySampleMax)
        .default(growthAiEnrichmentRunCreateBodySampleDefault)
        .describe(
            'Number of the most recently archived, distinct orgs to classify (1-10). Each sampled org costs one LLM call, so keep this bounded during iteration.'
        ),
})

/**
 * Staff-only, unscoped API for the enrichment AI enrichment: browse labels and their prompt
 * config versions, test-run a draft config against recently archived orgs, save a new
 * immutable version, and flip which version is active.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const growthAiEnrichmentSaveCreateBodyLabelMax = 128

export const growthAiEnrichmentSaveCreateBodyVersionMax = 128

export const growthAiEnrichmentSaveCreateBodyPromptTextMax = 20000

export const growthAiEnrichmentSaveCreateBodyModelMax = 128

export const growthAiEnrichmentSaveCreateBodyOutputFieldsItemKeyRegExp = new RegExp('^[a-z][a-z0-9_]\*$')
export const growthAiEnrichmentSaveCreateBodyOutputFieldsItemDescriptionDefault = ``
export const growthAiEnrichmentSaveCreateBodyOutputFieldsItemDescriptionMax = 400

export const GrowthAiEnrichmentSaveCreateBody = /* @__PURE__ */ zod.object({
    label: zod
        .string()
        .max(growthAiEnrichmentSaveCreateBodyLabelMax)
        .describe('Label this config computes, e.g. ai_pilled.'),
    version: zod
        .string()
        .max(growthAiEnrichmentSaveCreateBodyVersionMax)
        .optional()
        .describe(
            'Version identity for the new row, e.g. v3. Optional: omit (or send blank) to accept the server-suggested next version for this label. Versions are immutable once created - there is no update endpoint - and (label, version) must be unique.'
        ),
    prompt_text: zod
        .string()
        .max(growthAiEnrichmentSaveCreateBodyPromptTextMax)
        .describe(
            'System prompt; {email} is replaced with the signup email domain at runtime. At most 20000 characters.'
        ),
    model: zod
        .string()
        .max(growthAiEnrichmentSaveCreateBodyModelMax)
        .describe(
            'Gateway model to classify with, routed through the LLM gateway. See GET \/models\/ for what it serves.'
        ),
    input_fields: zod
        .array(zod.string())
        .optional()
        .describe(
            'Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Every selected value reaches the LLM and is then stored on the result indefinitely, so keep this list intentional.'
        ),
    output_fields: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .regex(growthAiEnrichmentSaveCreateBodyOutputFieldsItemKeyRegExp)
                    .describe(
                        'Output key, e.g. ai_pilled. Lowercase, starts with a letter, letters\/digits\/underscore only.'
                    ),
                type: zod
                    .enum(['boolean', 'number', 'string'])
                    .describe('\* `boolean` - boolean\n\* `number` - number\n\* `string` - string')
                    .describe(
                        'Value type the LLM must return for this key.\n\n\* `boolean` - boolean\n\* `number` - number\n\* `string` - string'
                    ),
                description: zod
                    .string()
                    .max(growthAiEnrichmentSaveCreateBodyOutputFieldsItemDescriptionMax)
                    .default(growthAiEnrichmentSaveCreateBodyOutputFieldsItemDescriptionDefault)
                    .describe('Shown to the LLM to describe what this key means. At most 400 characters.'),
            })
        )
        .describe(
            "Output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. This is the classifier's entire output contract - the label is a human name and is never an output key, so renaming a label changes nothing about what a version computes. Keys must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs'. At most 20 fields."
        ),
})
