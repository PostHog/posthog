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
 * Stage 1 (Ideation) commit. Called by the FE when the cofounder chat reaches `should_end_chat=true`. Body carries `{name, ideation: {what, how, who, problem}}`. **Side effect:** if `ideation` is non-empty, validation (stage 2) is auto-fired on commit — saves a round-trip vs creating then POSTing `run_validation/`.
 */
export const FounderProjectsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Full replace. Mainly used for renames. **Side effect:** if `ideation` changes, validation is re-fired automatically. Avoid sending unchanged ideation — re-runs burn a Gemini call.
 */
export const FounderProjectsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Patch fields on a founder project. Same auto-revalidation as full update — sending a changed `ideation` re-fires the validation Celery task. Sending only `name` (or other non-ideation fields) is the safe rename path.
 */
export const FounderProjectsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 3 (GTM).** Generate the *conceptual* GTM summary — positioning statement, primary + secondary target segments, category, moat, pricing philosophy and tiers, primary + secondary acquisition channels. Single Gemini call grounded on `ideation` + `validation.report`. NOT the practical launch playbook (that's `run_practical_steps`). Writes to the `gtm` column. Poll until `gtm.status` is `completed` or `failed`.
 */
export const FounderProjectsRunGtmCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 5 (Marketing) — landing page half.** Generate the landing page *build spec* (copy hooks, design notes, shadcn/ui component recipes, PostHog event signatures, acceptance criteria) from the full project state. NOT a rendered page — a brief a developer or AI coding agent takes and turns into Next.js + Tailwind code. Writes to the `marketing_page` column. The marketing UI stage fires this in parallel with `run_practical_steps`. Poll until `marketing_page.status` is `completed` or `failed`.
 */
export const FounderProjectsRunLandingPageCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 4 (MVP).** Generate the MVP happy-path spec — one-liner, 3-7 step user journey from first touch to value delivered, must-have features, deliberately excluded features. Single Gemini call grounded on `ideation` + `validation` + `gtm`. Placeholder prompt — content shape may change as stage 4 stabilizes. Writes to the `mvp` column. Poll until `mvp.status` is `completed` or `failed`.
 */
export const FounderProjectsRunMvpCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 5 (Marketing) — practical playbook half.** Generate the concrete launch checklist — ready-to-publish copy for Product Hunt, LinkedIn, Twitter, Reddit, HN, Indie Hackers, etc., ordered D-7 → launch day → D+7. Each step has a platform, timeline, and full post text the founder can copy-paste. Writes to the `marketing_steps` column. The marketing UI stage fires this in parallel with `run_landing_page`. Poll until `marketing_steps.status` is `completed` or `failed`.
 */
export const FounderProjectsRunPracticalStepsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 2 (Validation).** Kick off the two-pass competitor research + assumptions report against the current `ideation` payload. Two sequential Gemini calls — grounded search, then structured synthesis — ~30-60s end to end. Writes to the `validation` column with intermediate `current_pass` updates so the FE can show real staged progress. Poll the detail endpoint until `validation.status` is `completed` or `failed`.
 */
export const FounderProjectsRunValidationCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 1 (Ideation).** One turn of the cofounder chat. Synchronous Gemini call. The request carries the full conversation state (chat is ephemeral on the FE until the founder commits at end-of-chat); the response carries the agent's next message plus an optional canvas-slot decision and an end-of-chat signal. When `should_end_chat=true`, the response also includes a synthesized `ideation_payload` that the FE then POSTs to `founder_projects/` to commit the ideation and auto-fire validation (stage 2).
 */

export const FounderProjectsCofounderTurnCreateBody = /* @__PURE__ */ zod
    .object({
        user_answer: zod.string().describe("The founder's latest reply."),
        last_question: zod
            .union([zod.string(), zod.null()])
            .nullish()
            .default(null)
            .describe("The agent's previous question this answer is responding to."),
        messages: zod
            .array(
                zod
                    .object({
                        author: zod.enum(['agent', 'user']),
                        value: zod.string(),
                    })
                    .describe('A prior message in the conversation. Used to give the agent context.')
            )
            .optional()
            .describe('Full conversation history so the agent can reference prior context.'),
        canvas_notes: zod
            .array(
                zod
                    .object({
                        key: zod.enum([
                            'idea',
                            'pain',
                            'audience',
                            'currentSolution',
                            'worstCase',
                            'success',
                            'killerFeature',
                        ]),
                        label: zod.string(),
                        value: zod.string(),
                    })
                    .describe("A canvas slot that's already been filled. Used so the agent knows what's left to ask.")
            )
            .optional()
            .describe('Slots already filled. The agent should not ask questions for these.'),
    })
    .describe('What the frontend POSTs each turn.')
