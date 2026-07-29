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
 * Rename a label. Purely cosmetic: the classifier's output contract is output_fields,
 * so no stored verdict changes meaning and no config's content_hash moves.
 */
export const growthScoreLabRenameCreateBodyLabelMax = 128

export const GrowthScoreLabRenameCreateBody = /* @__PURE__ */ zod.object({
    config_id: zod.uuid().describe('Any config of the label to rename.'),
    label: zod
        .string()
        .max(growthScoreLabRenameCreateBodyLabelMax)
        .describe(
            'New label name. A label is shared by every version of it, so this renames them all. It changes nothing about what the classifier does: the output contract is output_fields.'
        ),
})

/**
 * One JSON object per line: a {company, domain, outputs: {<key>: value, ...}} row as each LLM call completes, keyed by the submitted output_fields, then a final {summary: {classified, unknown, errors}} line. A run that fails partway ends with {error, aborted: true} instead of a summary. Persists nothing - spends real LLM money, so sample is capped at 100 and the endpoint is rate limited.
 * @summary Stream classifier verdicts for an unsaved draft config against recent archived orgs.
 */
export const growthScoreLabRunCreateBodyLabelMax = 128

export const growthScoreLabRunCreateBodyModelMax = 128

export const growthScoreLabRunCreateBodyOutputFieldsItemKeyRegExp = new RegExp('^[a-z][a-z0-9_]\*$')
export const growthScoreLabRunCreateBodyOutputFieldsItemDescriptionDefault = ``
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
            'Gateway model to classify with, routed through the LLM gateway. See GET \/models\/ for what it serves.'
        ),
    input_fields: zod
        .array(
            zod
                .enum([
                    'name',
                    'description',
                    'website.url',
                    'companyType',
                    'headcount',
                    'tagsV2',
                    'funding.fundingStage',
                    'funding.fundingTotal',
                    'funding.lastFundingAt',
                    'funding.investors',
                    'location.country',
                    'foundingDate.date',
                ])
                .describe(
                    '\* `name` - name\n\* `description` - description\n\* `website.url` - website.url\n\* `companyType` - companyType\n\* `headcount` - headcount\n\* `tagsV2` - tagsV2\n\* `funding.fundingStage` - funding.fundingStage\n\* `funding.fundingTotal` - funding.fundingTotal\n\* `funding.lastFundingAt` - funding.lastFundingAt\n\* `funding.investors` - funding.investors\n\* `location.country` - location.country\n\* `foundingDate.date` - foundingDate.date'
                )
        )
        .optional()
        .describe(
            'Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Restricted to the allow-list served by GET \/input_fields\/, because every selected value reaches the LLM and is then stored on the result indefinitely.'
        ),
    output_fields: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .regex(growthScoreLabRunCreateBodyOutputFieldsItemKeyRegExp)
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
                    .default(growthScoreLabRunCreateBodyOutputFieldsItemDescriptionDefault)
                    .describe('Shown to the LLM to describe what this key means.'),
            })
        )
        .describe(
            "Output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. This is the classifier's entire output contract - the label is a human name and is never an output key, so renaming a label changes nothing about what a version computes. Keys must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs'."
        ),
    sample: zod
        .number()
        .min(1)
        .max(growthScoreLabRunCreateBodySampleMax)
        .default(growthScoreLabRunCreateBodySampleDefault)
        .describe(
            'Number of rows to classify (1-100) from recent archived orgs. Each sampled row costs one LLM call, so keep this bounded during iteration.'
        ),
    contains: zod
        .string()
        .default(growthScoreLabRunCreateBodyContainsDefault)
        .describe('Optional case-insensitive substring filter on the archived company or organization name.'),
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

export const growthScoreLabSaveCreateBodyModelMax = 128

export const growthScoreLabSaveCreateBodyOutputFieldsItemKeyRegExp = new RegExp('^[a-z][a-z0-9_]\*$')
export const growthScoreLabSaveCreateBodyOutputFieldsItemDescriptionDefault = ``

export const GrowthScoreLabSaveCreateBody = /* @__PURE__ */ zod.object({
    label: zod
        .string()
        .max(growthScoreLabSaveCreateBodyLabelMax)
        .describe('Label this config computes, e.g. ai_pilled.'),
    prompt_text: zod.string().describe('System prompt; {email} is replaced with the signup email domain at runtime.'),
    model: zod
        .string()
        .max(growthScoreLabSaveCreateBodyModelMax)
        .describe(
            'Gateway model to classify with, routed through the LLM gateway. See GET \/models\/ for what it serves.'
        ),
    input_fields: zod
        .array(
            zod
                .enum([
                    'name',
                    'description',
                    'website.url',
                    'companyType',
                    'headcount',
                    'tagsV2',
                    'funding.fundingStage',
                    'funding.fundingTotal',
                    'funding.lastFundingAt',
                    'funding.investors',
                    'location.country',
                    'foundingDate.date',
                ])
                .describe(
                    '\* `name` - name\n\* `description` - description\n\* `website.url` - website.url\n\* `companyType` - companyType\n\* `headcount` - headcount\n\* `tagsV2` - tagsV2\n\* `funding.fundingStage` - funding.fundingStage\n\* `funding.fundingTotal` - funding.fundingTotal\n\* `funding.lastFundingAt` - funding.lastFundingAt\n\* `funding.investors` - funding.investors\n\* `location.country` - location.country\n\* `foundingDate.date` - foundingDate.date'
                )
        )
        .optional()
        .describe(
            'Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Restricted to the allow-list served by GET \/input_fields\/, because every selected value reaches the LLM and is then stored on the result indefinitely.'
        ),
    output_fields: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .regex(growthScoreLabSaveCreateBodyOutputFieldsItemKeyRegExp)
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
                    .default(growthScoreLabSaveCreateBodyOutputFieldsItemDescriptionDefault)
                    .describe('Shown to the LLM to describe what this key means.'),
            })
        )
        .describe(
            "Output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. This is the classifier's entire output contract - the label is a human name and is never an output key, so renaming a label changes nothing about what a version computes. Keys must match ^[a-z][a-z0-9_]\*$, be unique, and not be 'meta' or 'inputs'."
        ),
})
