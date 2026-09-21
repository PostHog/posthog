/** The four fields every refusal carries, in the SDK and in the API alike. */
export interface WorkflowErrorFields {
    /** A stable machine-readable code, for example `missing_secret`. */
    readonly status: string
    /** What happened, in one sentence. */
    readonly message: string
    /** Why it is refused rather than accepted. */
    readonly why: string
    /** The next action the author takes. */
    readonly fix: string
}

export class WorkflowError extends Error {
    readonly fields: WorkflowErrorFields

    constructor(fields: WorkflowErrorFields) {
        super(fields.message)
        this.name = 'WorkflowError'
        this.fields = fields
    }

    /** The four fields as the CLI prints them. */
    print(): string {
        return [
            `status: ${this.fields.status}`,
            `message: ${this.fields.message}`,
            `why: ${this.fields.why}`,
            `fix: ${this.fields.fix}`,
        ].join('\n')
    }
}
