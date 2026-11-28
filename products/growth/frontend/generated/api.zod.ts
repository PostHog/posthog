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
            'System prompt; {email} is replaced with the signup email domain at runtime. When the prompt asks for it, the model may call web_search and fetch_page (run through Firecrawl) to look things up; each call costs Firecrawl credits. At most 20000 characters.'
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
            'System prompt; {email} is replaced with the signup email domain at runtime. When the prompt asks for it, the model may call web_search and fetch_page (run through Firecrawl) to look things up; each call costs Firecrawl credits. At most 20000 characters.'
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

/**
 * Called by a PostHog realtime destination, not by API clients. Requires the X-PostHog-Webhook-Secret header to match the GROWTH_RESCORE_WEBHOOK_SECRET instance setting.
 * @summary Re-score an organization's ICP fit after its wizard AI-SDK stamp lands.
 */
export const GrowthEnrichmentRescoreCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod
        .uuid()
        .describe("Organization to re-score, from the $group_key of the wizard's $groupidentify event."),
})

export const GrowthEnrichmentScoringActivateCreateBody = /* @__PURE__ */ zod.object({
    config_id: zod.uuid().describe('Saved scoring version to activate for subsequent evaluations.'),
})

export const growthEnrichmentScoringPreviewCreateBodySourceMax = 30000

export const growthEnrichmentScoringPreviewCreateBodySampleDefault = 10
export const growthEnrichmentScoringPreviewCreateBodySampleMax = 10

export const GrowthEnrichmentScoringPreviewCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .string()
        .max(growthEnrichmentScoringPreviewCreateBodySourceMax)
        .describe('Hog formula to compile and execute.'),
    base_config_id: zod.uuid().describe('Configuration whose curated tags and investors to use for the draft.'),
    sample: zod
        .number()
        .min(1)
        .max(growthEnrichmentScoringPreviewCreateBodySampleMax)
        .default(growthEnrichmentScoringPreviewCreateBodySampleDefault)
        .describe('Number of recent companies to preview.'),
})

export const growthEnrichmentScoringSaveCreateBodySourceMax = 30000

export const growthEnrichmentScoringSaveCreateBodyVersionMax = 128

export const GrowthEnrichmentScoringSaveCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .string()
        .max(growthEnrichmentScoringSaveCreateBodySourceMax)
        .describe('Hog formula to compile and execute.'),
    version: zod
        .string()
        .max(growthEnrichmentScoringSaveCreateBodyVersionMax)
        .describe('Unique name for the new scoring version.'),
    base_config_id: zod.uuid().describe('Configuration whose curated tags and investors to retain.'),
})

/**
 * Saves a draft ticket to PostHog support. It does not send it. Refuses a topic that an agent can't file, and a plan without support for the topic, and says where the person can ask instead. The person approves it in chat, so the agent sends it with the send endpoint.
 * @summary Draft a PostHog support ticket for the person to approve
 */
export const posthogSupportDraftsCreateBodyTitleMax = 100

export const posthogSupportDraftsCreateBodyRequestMax = 2000

export const posthogSupportDraftsCreateBodyDetailsMax = 3000

export const posthogSupportDraftsCreateBodyAlreadyCheckedMax = 1500

export const posthogSupportDraftsCreateBodyErrorMax = 1500

export const posthogSupportDraftsCreateBodyAgentNameOneRegExp = new RegExp('^[\\w .\\-]{1,40}$')
export const posthogSupportDraftsCreateBodyAgentNameTwoMax = 0

export const PosthogSupportDraftsCreateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(posthogSupportDraftsCreateBodyTitleMax)
        .describe(
            "A short title that names the problem, such as 'Delete test events that contain customer emails'. It opens the ticket, and ticket lists show it, so don't start it with 'Request'."
        ),
    request: zod
        .string()
        .max(posthogSupportDraftsCreateBodyRequestMax)
        .describe(
            "The whole ask, in the person's voice. Open with what happened in one sentence, with the numbers and dates. Then add the action they need in one sentence, or list every question the docs did not answer, numbered in the person's order, with every part of each question. When they heard your answer and still want a human, give your answer in one sentence, as yours."
        ),
    details: zod
        .string()
        .max(posthogSupportDraftsCreateBodyDetailsMax)
        .optional()
        .describe(
            "Markdown bullets of facts support needs: the project and the region, a link to each object involved, SDK and version, and every required detail for the kind of request, such as a deletion query and its count. Link each object on its name, such as '- Project: [Web app](<link>)', and put the region on its own line. Take links from _posthogUrl. No guesses."
        ),
    already_checked: zod
        .string()
        .max(posthogSupportDraftsCreateBodyAlreadyCheckedMax)
        .optional()
        .describe(
            "Markdown bullets of what was already checked, each with its result. Start a docs check with 'Docs:' and link the page on its title, a lookup you ran in this conversation with '<your name> checked:', and a step the person took with 'I tried:'. When filing_reason is user_disagrees_with_agent or user_asked_for_support, this is required: add the answer you already gave them, with a link to each docs page it came from. List only your checks that bear on the open questions, because support can look up the rest of your calls. Never write a number the person gave you as your own check."
        ),
    error: zod
        .string()
        .max(posthogSupportDraftsCreateBodyErrorMax)
        .optional()
        .describe(
            'The exact text of an error the person saw, and its top frames. A lookup of yours that failed goes in already_checked. Remove any credential and say that you removed it.'
        ),
    topic: zod
        .enum([
            'privacy',
            'security',
            'compliance',
            'retention',
            'dpa',
            'baa',
            'privacy_or_security_deletion',
            'other_deletion',
            'billing',
            'other',
        ])
        .describe(
            '\* `privacy` - Privacy\n\* `security` - Security\n\* `compliance` - Compliance\n\* `retention` - Data retention\n\* `dpa` - Data processing agreement (DPA)\n\* `baa` - Business associate agreement (BAA)\n\* `privacy_or_security_deletion` - Deleting data for a privacy or security reason\n\* `other_deletion` - Deleting data for another reason\n\* `billing` - Billing or usage\n\* `other` - Anything else'
        )
        .describe(
            "What the ticket as a whole is about. Only privacy, security, compliance, retention, deletion, DPA, BAA and billing tickets can be filed from here. Use other for everything else, and don't stretch a topic to fit: support sees the topic. A login problem is other, never security. Use privacy_or_security_deletion only when the person gave a privacy or security reason for the deletion. Use billing only when the ticket is about billing or usage, not for a billing question asked in passing.\n\n\* `privacy` - Privacy\n\* `security` - Security\n\* `compliance` - Compliance\n\* `retention` - Data retention\n\* `dpa` - Data processing agreement (DPA)\n\* `baa` - Business associate agreement (BAA)\n\* `privacy_or_security_deletion` - Deleting data for a privacy or security reason\n\* `other_deletion` - Deleting data for another reason\n\* `billing` - Billing or usage\n\* `other` - Anything else"
        ),
    filing_reason: zod
        .enum(['user_asked_for_support', 'needs_posthog_staff', 'unexplained_error', 'user_disagrees_with_agent'])
        .describe(
            "\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `needs_posthog_staff` - Only PostHog staff can do or see what the person needs\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        )
        .describe(
            "Why a human at PostHog should look at this. Your own conclusion that it is a PostHog bug is not a reason.\n\n\* `user_asked_for_support` - The person asked to contact PostHog support\n\* `needs_posthog_staff` - Only PostHog staff can do or see what the person needs\n\* `unexplained_error` - A reproducible error the agent confirmed but cannot explain\n\* `user_disagrees_with_agent` - The person disagrees with the agent's answer"
        ),
    agent_name: zod
        .union([
            zod.string().regex(posthogSupportDraftsCreateBodyAgentNameOneRegExp),
            zod.string().max(posthogSupportDraftsCreateBodyAgentNameTwoMax),
        ])
        .optional()
        .describe('Name of the agent or client drafting the ticket, such as Claude Code or Codex.'),
})
