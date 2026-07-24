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
 * Supersedes the admin lab UI's read paths; run/save/activate share the same underlying
 * machinery (products.growth.backend.enrichment.lab) as the admin dry-run action so both
 * surfaces compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const GrowthScoreLabActivateCreateBody = /* @__PURE__ */ zod.object({
    config_id: zod.uuid().describe('Prompt config id to activate for its label.'),
})

/**
 * One JSON object per line: a verdict row ({company, domain, verdict, confidence, reasoning}) as each LLM call completes, then a final {summary: {classified, unknown, errors}} line. Persists nothing - spends real LLM money, so sample is capped at 100.
 * @summary Stream classifier verdicts for an unsaved draft config against recent archived orgs.
 */
export const growthScoreLabRunCreateBodyLabelMax = 128

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
        .enum([
            'gpt-5.2',
            'gpt-5.2-pro',
            'gpt-5.1',
            'gpt-5',
            'gpt-5-mini',
            'gpt-5-nano',
            'gpt-4.1',
            'gpt-4.1-mini',
            'claude-fable-5',
            'claude-opus-4-8',
            'claude-sonnet-5',
            'claude-haiku-4-5',
        ])
        .describe(
            '\* `gpt-5.2` - gpt-5.2\n\* `gpt-5.2-pro` - gpt-5.2-pro\n\* `gpt-5.1` - gpt-5.1\n\* `gpt-5` - gpt-5\n\* `gpt-5-mini` - gpt-5-mini\n\* `gpt-5-nano` - gpt-5-nano\n\* `gpt-4.1` - gpt-4.1\n\* `gpt-4.1-mini` - gpt-4.1-mini\n\* `claude-fable-5` - claude-fable-5\n\* `claude-opus-4-8` - claude-opus-4-8\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-haiku-4-5` - claude-haiku-4-5'
        )
        .describe(
            'Gateway model to classify with, routed through the LLM gateway.\n\n\* `gpt-5.2` - gpt-5.2\n\* `gpt-5.2-pro` - gpt-5.2-pro\n\* `gpt-5.1` - gpt-5.1\n\* `gpt-5` - gpt-5\n\* `gpt-5-mini` - gpt-5-mini\n\* `gpt-5-nano` - gpt-5-nano\n\* `gpt-4.1` - gpt-4.1\n\* `gpt-4.1-mini` - gpt-4.1-mini\n\* `claude-fable-5` - claude-fable-5\n\* `claude-opus-4-8` - claude-opus-4-8\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-haiku-4-5` - claude-haiku-4-5'
        ),
    input_fields: zod
        .array(zod.string())
        .optional()
        .describe('Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage.'),
    sample: zod
        .number()
        .min(1)
        .max(growthScoreLabRunCreateBodySampleMax)
        .default(growthScoreLabRunCreateBodySampleDefault)
        .describe(
            'Number of recent archived orgs to classify (1-100). Each sampled org costs one LLM call, so keep this bounded during iteration.'
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
 * Supersedes the admin lab UI's read paths; run/save/activate share the same underlying
 * machinery (products.growth.backend.enrichment.lab) as the admin dry-run action so both
 * surfaces compute identical verdicts.
 *
 * Registered on the root router so it is not team-nested - prompt configs are instance-global,
 * not scoped to any team or org.
 */
export const growthScoreLabSaveCreateBodyLabelMax = 128

export const growthScoreLabSaveCreateBodyVersionMax = 128

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
        .enum([
            'gpt-5.2',
            'gpt-5.2-pro',
            'gpt-5.1',
            'gpt-5',
            'gpt-5-mini',
            'gpt-5-nano',
            'gpt-4.1',
            'gpt-4.1-mini',
            'claude-fable-5',
            'claude-opus-4-8',
            'claude-sonnet-5',
            'claude-haiku-4-5',
        ])
        .describe(
            '\* `gpt-5.2` - gpt-5.2\n\* `gpt-5.2-pro` - gpt-5.2-pro\n\* `gpt-5.1` - gpt-5.1\n\* `gpt-5` - gpt-5\n\* `gpt-5-mini` - gpt-5-mini\n\* `gpt-5-nano` - gpt-5-nano\n\* `gpt-4.1` - gpt-4.1\n\* `gpt-4.1-mini` - gpt-4.1-mini\n\* `claude-fable-5` - claude-fable-5\n\* `claude-opus-4-8` - claude-opus-4-8\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-haiku-4-5` - claude-haiku-4-5'
        )
        .describe(
            'Gateway model to classify with, routed through the LLM gateway.\n\n\* `gpt-5.2` - gpt-5.2\n\* `gpt-5.2-pro` - gpt-5.2-pro\n\* `gpt-5.1` - gpt-5.1\n\* `gpt-5` - gpt-5\n\* `gpt-5-mini` - gpt-5-mini\n\* `gpt-5-nano` - gpt-5-nano\n\* `gpt-4.1` - gpt-4.1\n\* `gpt-4.1-mini` - gpt-4.1-mini\n\* `claude-fable-5` - claude-fable-5\n\* `claude-opus-4-8` - claude-opus-4-8\n\* `claude-sonnet-5` - claude-sonnet-5\n\* `claude-haiku-4-5` - claude-haiku-4-5'
        ),
    input_fields: zod
        .array(zod.string())
        .optional()
        .describe('Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage.'),
})
