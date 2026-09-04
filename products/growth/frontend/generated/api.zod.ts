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

export const growthAiEnrichmentRunCreateBodySourcesItemKeyMax = 32

export const growthAiEnrichmentRunCreateBodySourcesItemKeyRegExp = new RegExp('^[a-z][a-z0-9_]{0,31}$')
export const growthAiEnrichmentRunCreateBodySourcesItemUrlMax = 2048

export const growthAiEnrichmentRunCreateBodySourcesItemQueryMax = 500

export const growthAiEnrichmentRunCreateBodySourcesItemLimitMax = 10

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
    sources: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .max(growthAiEnrichmentRunCreateBodySourcesItemKeyMax)
                    .regex(growthAiEnrichmentRunCreateBodySourcesItemKeyRegExp)
                    .describe(
                        "Column prefix this source contributes, e.g. 'pricing'. Lowercase, starts with a letter, letters\/digits\/underscore only."
                    ),
                kind: zod
                    .enum(['fetch', 'search'])
                    .describe('\* `fetch` - fetch\n\* `search` - search')
                    .describe(
                        "'fetch' scrapes one url; 'search' runs a web search.\n\n\* `fetch` - fetch\n\* `search` - search"
                    ),
                url: zod
                    .string()
                    .max(growthAiEnrichmentRunCreateBodySourcesItemUrlMax)
                    .optional()
                    .describe(
                        "Url template for a 'fetch' source, e.g. 'https:\/\/{domain}\/pricing'. Required for kind 'fetch'."
                    ),
                query: zod
                    .string()
                    .max(growthAiEnrichmentRunCreateBodySourcesItemQueryMax)
                    .optional()
                    .describe(
                        "Search query template for a 'search' source, e.g. '\"{name}\" AI OR LLM product'. Required for kind 'search'."
                    ),
                limit: zod
                    .number()
                    .min(1)
                    .max(growthAiEnrichmentRunCreateBodySourcesItemLimitMax)
                    .optional()
                    .describe("Max results for a 'search' source (1-10). Ignored for kind 'fetch'."),
            })
        )
        .optional()
        .describe(
            "Web sources this config fetches per org through Firecrawl before classifying. Kind 'fetch' scrapes one url template; kind 'search' runs a web search from a query template. Templates may reference {domain} (the signup domain) and {name} (the Harmonic payload's name, falling back to the organization's name). Each fetch costs 1 Firecrawl credit and each search costs 2. Results reach the LLM as extra input columns and are stored on the result row, so a config with any sources must declare a string 'evidence_url' output field."
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

export const growthAiEnrichmentSaveCreateBodySourcesItemKeyMax = 32

export const growthAiEnrichmentSaveCreateBodySourcesItemKeyRegExp = new RegExp('^[a-z][a-z0-9_]{0,31}$')
export const growthAiEnrichmentSaveCreateBodySourcesItemUrlMax = 2048

export const growthAiEnrichmentSaveCreateBodySourcesItemQueryMax = 500

export const growthAiEnrichmentSaveCreateBodySourcesItemLimitMax = 10

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
    sources: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .max(growthAiEnrichmentSaveCreateBodySourcesItemKeyMax)
                    .regex(growthAiEnrichmentSaveCreateBodySourcesItemKeyRegExp)
                    .describe(
                        "Column prefix this source contributes, e.g. 'pricing'. Lowercase, starts with a letter, letters\/digits\/underscore only."
                    ),
                kind: zod
                    .enum(['fetch', 'search'])
                    .describe('\* `fetch` - fetch\n\* `search` - search')
                    .describe(
                        "'fetch' scrapes one url; 'search' runs a web search.\n\n\* `fetch` - fetch\n\* `search` - search"
                    ),
                url: zod
                    .string()
                    .max(growthAiEnrichmentSaveCreateBodySourcesItemUrlMax)
                    .optional()
                    .describe(
                        "Url template for a 'fetch' source, e.g. 'https:\/\/{domain}\/pricing'. Required for kind 'fetch'."
                    ),
                query: zod
                    .string()
                    .max(growthAiEnrichmentSaveCreateBodySourcesItemQueryMax)
                    .optional()
                    .describe(
                        "Search query template for a 'search' source, e.g. '\"{name}\" AI OR LLM product'. Required for kind 'search'."
                    ),
                limit: zod
                    .number()
                    .min(1)
                    .max(growthAiEnrichmentSaveCreateBodySourcesItemLimitMax)
                    .optional()
                    .describe("Max results for a 'search' source (1-10). Ignored for kind 'fetch'."),
            })
        )
        .optional()
        .describe(
            "Web sources this config fetches per org through Firecrawl before classifying. Kind 'fetch' scrapes one url template; kind 'search' runs a web search from a query template. Templates may reference {domain} (the signup domain) and {name} (the Harmonic payload's name, falling back to the organization's name). Each fetch costs 1 Firecrawl credit and each search costs 2. Results reach the LLM as extra input columns and are stored on the result row, so a config with any sources must declare a string 'evidence_url' output field."
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
