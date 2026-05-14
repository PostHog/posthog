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
 * Stage 1 (Ideation) commit. Called by the FE when the cofounder chat reaches `should_end_chat=true`. Body carries `{name, ideation: {what, how, who, problem}}`. **Side effect:** if `ideation` is non-empty, validation (stage 2) is auto-fired on commit — saves a round-trip vs creating then POSTing `run_validation/`. **Idempotent:** if a project already exists for this team, the existing row is updated and returned instead of creating a duplicate.
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
 * **Stage 6b (Scaffold — publish).** Push the previously-generated file tree to a fresh GitHub repository on the authenticated user's account. Body carries the `github_token` (PAT with `repo` scope — used once, never persisted), `repo_name`, `visibility` (public/private), and optional `description`. Returns 202 + the project; poll `scaffold.status` and read `scaffold.repo` once it's `completed`. Requires `scaffold.files` to be populated by a prior `run_scaffold` call.
 */

export const founderProjectsPublishScaffoldCreateBodyRepoNameMax = 100

export const founderProjectsPublishScaffoldCreateBodyRepoNameRegExp = new RegExp('^[A-Za-z0-9_.-]+$')
export const founderProjectsPublishScaffoldCreateBodyVisibilityDefault = `private`
export const founderProjectsPublishScaffoldCreateBodyVisibilityRegExp = new RegExp('^(public|private)$')
export const founderProjectsPublishScaffoldCreateBodyDescriptionDefault = ``
export const founderProjectsPublishScaffoldCreateBodyDescriptionMax = 350

export const FounderProjectsPublishScaffoldCreateBody = /* @__PURE__ */ zod
    .object({
        github_token: zod
            .union([zod.string(), zod.null()])
            .nullish()
            .default(null)
            .describe(
                'GitHub personal access token with `repo` scope. Used once to create the repo and push the initial commit, then discarded — not persisted. If omitted, the server falls back to the `FOUNDER_MODE_GITHUB_PAT` env var (local-dev convenience).'
            ),
        repo_name: zod
            .string()
            .min(1)
            .max(founderProjectsPublishScaffoldCreateBodyRepoNameMax)
            .regex(founderProjectsPublishScaffoldCreateBodyRepoNameRegExp)
            .describe("Name for the new repository on the authenticated user's account."),
        visibility: zod
            .string()
            .regex(founderProjectsPublishScaffoldCreateBodyVisibilityRegExp)
            .default(founderProjectsPublishScaffoldCreateBodyVisibilityDefault)
            .describe('Repository visibility. `public` or `private`. Defaults to private.'),
        description: zod
            .string()
            .max(founderProjectsPublishScaffoldCreateBodyDescriptionMax)
            .default(founderProjectsPublishScaffoldCreateBodyDescriptionDefault)
            .describe('Optional one-line repo description.'),
    })
    .describe('Body for the `publish_scaffold` action.')

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
 * **Stage 6a (Scaffold — generate).** Render the landing page build spec into a Next.js + Tailwind + react-markdown file tree, stored as `{path: contents}` on the `scaffold.files` column. Requires `marketing_page.status='completed'` (i.e. the spec exists). Pure Python — no LLM call, no network — should complete in well under a second. Poll until `scaffold.status` is `completed` or `failed`.
 */
export const FounderProjectsRunScaffoldCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 2 (Validation).** Kick off the two-pass competitor research + assumptions report against the current `ideation` payload. Two sequential Gemini calls — grounded search, then structured synthesis — ~30-60s end to end. Writes to the `validation` column with intermediate `current_pass` updates so the FE can show real staged progress. Poll the detail endpoint until `validation.status` is `completed` or `failed`.
 */
export const FounderProjectsRunValidationCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * **Stage 1 (Ideation).** One turn of a topic-scoped cofounder mini-chat. Synchronous Gemini call. The request carries `{topic, goal, user_answer, messages, founder_mode}` — the topic's whole thread so far (chat is ephemeral on the FE). The response carries the agent's next `agent_message`, a `satisfied` flag, and — when satisfied — a `crystallized_value` dict whose keys are defined by the request `goal` (for the `idea` topic: `{what, how, who, problem}`). On `satisfied=true` the FE POSTs the crystallized value to `founder_projects/` to commit the ideation and auto-fire validation (stage 2).
 */
export const founderProjectsCofounderTurnCreateBodyFounderModeDefault = `commercial_cofounder`

export const FounderProjectsCofounderTurnCreateBody = /* @__PURE__ */ zod
    .object({
        topic: zod
            .string()
            .describe('Which topic this mini-chat is about. Currently always \"idea\" (the ideation step).'),
        goal: zod
            .string()
            .describe(
                'What the cofounder must extract from this topic before it can be satisfied. Topic-specific — the frontend defines it. For the idea topic this describes the {what, how, who, problem} the validation pass needs, and tells the cofounder which keys `crystallized_value` must carry.'
            ),
        user_answer: zod.string().describe("The founder's latest reply in this thread."),
        messages: zod
            .array(
                zod
                    .object({
                        author: zod.enum(['agent', 'user']),
                        value: zod.string(),
                    })
                    .describe("A prior message in this topic's mini-chat thread.")
            )
            .optional()
            .describe("This topic's prior thread (everything before `user_answer`). Empty on the first turn."),
        founder_mode: zod
            .enum(['technical_cofounder', 'commercial_cofounder'])
            .default(founderProjectsCofounderTurnCreateBodyFounderModeDefault)
            .describe(
                'Which half of the founding team the cofounder plays. Selects the mode block injected into the system prompt. Defaults to commercial so older clients still get a coherent persona.'
            ),
    })
    .describe("What the frontend POSTs each turn of a topic's mini-chat.")
