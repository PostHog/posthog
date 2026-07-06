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
 * Opens a pull request that edits the repository's checked-in .test_quarantine.json — and, for a new quarantine, a tracking issue the PR links but does not close. The file stays the source of truth that CI enforces; this never bypasses it. A quarantine only affects CI runs that start after the PR merges.
 * @summary Quarantine, extend, or unquarantine a flaky test
 */
export const EngineeringAnalyticsQuarantineRequestBody = /* @__PURE__ */ zod.object({
    operation: zod
        .enum(['quarantine', 'extend', 'remove'])
        .describe('\* `quarantine` - QUARANTINE\n\* `extend` - EXTEND\n\* `remove` - REMOVE')
        .describe(
            "What to do: 'quarantine' (add or replace an entry and file a tracking issue), 'extend' (re-stamp an existing entry's expiry, reusing its issue), or 'remove' (delete the entry). All three open a pull request.\n\n\* `quarantine` - QUARANTINE\n\* `extend` - EXTEND\n\* `remove` - REMOVE"
        ),
    selector: zod
        .string()
        .describe(
            "Test selector to act on: an exact test id, a file, a directory, a class prefix, or 'product:<dashed-name>'."
        ),
    repo: zod
        .string()
        .nullish()
        .describe("Optional 'owner\/name' repository override; defaults to the team's most active repo."),
    reason: zod
        .string()
        .optional()
        .describe('Why the test is quarantined. Required for quarantine and extend; ignored by remove.'),
    owner: zod
        .string()
        .optional()
        .describe(
            "GitHub team or user handle responsible for the fix, e.g. '@PostHog\/team-x'. Required for quarantine and extend."
        ),
    issue: zod
        .string()
        .optional()
        .describe(
            'Existing tracking issue URL, carried forward on extend and remove. Ignored by quarantine, which files a fresh issue.'
        ),
    expires: zod.iso
        .date()
        .nullish()
        .describe(
            'ISO date the quarantine expires (at most 30 days out). Defaults to 14 days from today. Ignored by remove.'
        ),
    mode: zod
        .enum(['run', 'skip'])
        .describe('\* `run` - RUN\n\* `skip` - SKIP')
        .optional()
        .describe(
            "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all). Defaults to 'run'.\n\n\* `run` - RUN\n\* `skip` - SKIP"
        ),
})
