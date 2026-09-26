/**
 * The four fields a refusal carries.
 *
 * Read `status` to branch, and print `message`, `why` and `fix` to the author. The
 * PostHog API refuses a write with the same four fields, so one handler covers both.
 */
export interface WorkflowErrorFields {
    /** A stable code to branch on, for example `missing_secret`. Safe to match exactly. */
    readonly status: string
    /** What happened, in one sentence. */
    readonly message: string
    /** Why the SDK refuses this rather than accepting it. */
    readonly why: string
    /** The next action the author takes to make it pass. */
    readonly fix: string
}

/**
 * A refusal: the error every function in this package throws when it will not proceed.
 *
 * A refusal is the SDK's one failure mode. It fires before anything reaches PostHog,
 * so an author fixes the file rather than a half-written workflow. Catch it, read
 * `fields.status` to decide what to do, and show `fields.message`, `fields.why` and
 * `fields.fix` unchanged. Each function that throws one documents its own statuses.
 *
 * @example
 * ```ts
 * import { WorkflowError, delay, onSchedule, path, workflow } from '@posthog/workflows'
 *
 * // Replace this key with your own before you push.
 * const flow = workflow({
 *     key: 'replace-me-nightly-digest',
 *     name: 'Nightly digest',
 *     on: onSchedule(),
 *     steps: path(delay('1d', { name: 'Wait a day' })),
 *     exit: { reason: 'Digest sent' },
 * })
 *
 * try {
 *     flow.emit()
 * } catch (error) {
 *     if (error instanceof WorkflowError && error.fields.status === 'missing_secret') {
 *         const report = error.print()
 *     }
 * }
 * ```
 */
export class WorkflowError extends Error {
    /** The four fields of this refusal. */
    readonly fields: WorkflowErrorFields

    /**
     * Builds a refusal from its four fields.
     *
     * @param fields - The status to branch on, and the three lines to show the author.
     */
    constructor(fields: WorkflowErrorFields) {
        super(fields.message)
        this.name = 'WorkflowError'
        this.fields = fields
    }

    /**
     * The four fields as four labelled lines, ready to write to a terminal.
     *
     * @returns One string of four lines, in the order status, message, why, fix.
     */
    print(): string {
        return [
            `status: ${this.fields.status}`,
            `message: ${this.fields.message}`,
            `why: ${this.fields.why}`,
            `fix: ${this.fields.fix}`,
        ].join('\n')
    }
}
