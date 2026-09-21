import type { ExitCondition, TriggerConfig, WorkflowStatus, WorkflowVariable } from './definition.js'
import { compile, type EmitOptions, type EmitResult } from './emit.js'
import type { Path } from './steps.js'

export interface WorkflowOptions {
    /**
     * The workflow's identity in the source file, unique for each team. The CLI will
     * resolve it through the list filter and then create or update, so one file can
     * reach a staging and a production project. PostHog's own id never travels back
     * into the source. The API accepts `key` from a later backend change on.
     */
    readonly key: string
    readonly name: string
    readonly description?: string
    /** Defaults to `draft`, so a first push sends nothing to a real person. */
    readonly status?: WorkflowStatus
    readonly exitCondition?: ExitCondition
    readonly variables?: readonly WorkflowVariable[]
    readonly on: TriggerConfig
    readonly steps: Path
    readonly exit: { readonly reason: string }
}

export interface Workflow {
    readonly key: string
    /** Resolves the secrets, validates the graph, and returns the definition to push. */
    emit(options?: EmitOptions): EmitResult
}

/** Declares one workflow. The file exports it, and `posthog-workflows push` sends it. */
export function workflow(options: WorkflowOptions): Workflow {
    return {
        key: options.key,
        emit: (emitOptions) =>
            compile(
                {
                    key: options.key,
                    name: options.name,
                    ...(options.description === undefined ? {} : { description: options.description }),
                    ...(options.status === undefined ? {} : { status: options.status }),
                    ...(options.exitCondition === undefined ? {} : { exitCondition: options.exitCondition }),
                    ...(options.variables === undefined ? {} : { variables: options.variables }),
                    trigger: options.on,
                    steps: options.steps,
                    exit: options.exit,
                },
                emitOptions
            ),
    }
}
