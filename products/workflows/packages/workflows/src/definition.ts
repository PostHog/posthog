// The create/update body that POST/PATCH /api/projects/{id}/hog_flows/ accepts.

/**
 * A wait the API accepts: a number and a unit, matching `^\d*\.?\d+[dhms]$`.
 * The template literal stops `'soon'` in the editor; `emit` re-checks the value,
 * because the literal type also admits `-1d` and `1e3d`.
 */
export type Duration = `${number}d` | `${number}h` | `${number}m` | `${number}s`

export type PropertyType = 'event' | 'person' | 'group'

export type PropertyOperator =
    | 'exact'
    | 'is_not'
    | 'icontains'
    | 'not_icontains'
    | 'is_set'
    | 'is_not_set'
    | 'gt'
    | 'lt'

/** One property condition. `bytecode` is compiled server-side and is never sent. */
export interface PropertyCondition {
    readonly key: string
    readonly value?: readonly (string | number | boolean)[]
    readonly operator: PropertyOperator
    readonly type: PropertyType
}

export interface EventFilter {
    readonly id: string
    readonly name: string
    readonly type: 'events'
    readonly order: number
    readonly properties: readonly PropertyCondition[]
}

export interface ActionFilters {
    readonly events: readonly EventFilter[]
    readonly properties: readonly PropertyCondition[]
    readonly filter_test_accounts: boolean
}

export type TriggerConfig = { readonly type: 'event'; readonly filters: ActionFilters } | { readonly type: 'schedule' }

export interface BranchCondition {
    readonly name: string
    readonly filters: { readonly properties: readonly PropertyCondition[] }
}

/** Function input values are wrapped so hog templating (`{person.x}`) resolves. */
export type FunctionInputs = Readonly<Record<string, { readonly value: unknown }>>

/** The inline email message: `template-email`'s single input, at `config.inputs.email.value`. */
export interface EmailMessage {
    readonly from: { readonly integrationId?: number }
    readonly to: { readonly email: string }
    readonly subject: string
    readonly text: string
    readonly html: string
    readonly preheader?: string
}

interface ActionBase {
    readonly id: string
    readonly name: string
}

export type Action =
    | (ActionBase & { readonly type: 'trigger'; readonly config: TriggerConfig })
    | (ActionBase & { readonly type: 'delay'; readonly config: { readonly delay_duration: Duration } })
    | (ActionBase & {
          readonly type: 'conditional_branch'
          readonly config: { readonly conditions: readonly BranchCondition[] }
      })
    | (ActionBase & {
          readonly type: 'function'
          readonly config: { readonly template_id: string; readonly inputs: FunctionInputs }
      })
    | (ActionBase & {
          readonly type: 'function_email'
          // The server coerces `template_id` to `template-email` whatever the client sends,
          // so the SDK sends that literal and has no route to a saved template UUID.
          readonly config: {
              readonly template_id: 'template-email'
              readonly inputs: { readonly email: { readonly value: EmailMessage } }
          }
      })
    | (ActionBase & { readonly type: 'exit'; readonly config: { readonly reason: string } })

export type Edge =
    | { readonly from: string; readonly to: string; readonly type: 'continue' }
    | { readonly from: string; readonly to: string; readonly type: 'branch'; readonly index: number }

export type ExitCondition =
    | 'exit_only_at_end'
    | 'exit_on_conversion'
    | 'exit_on_trigger_not_matched'
    | 'exit_on_trigger_not_matched_or_conversion'

export type WorkflowStatus = 'draft' | 'active' | 'archived'

export interface WorkflowVariable {
    readonly key: string
    readonly type: 'string' | 'number' | 'boolean'
    readonly default: string
}

/**
 * The create/update request body. Deliberately narrow: `trigger`, `version`,
 * `billable_action_types`, `abort_action`, `action_redirects` and the `draft*`
 * fields are read-only on the serializer and must never be sent.
 */
export interface WorkflowDefinition {
    /**
     * The workflow's identity in the source file. `HogFlowSerializer` does not accept it
     * yet, and ignores it as an unknown field until the backend change lands.
     */
    readonly key: string
    readonly name: string
    readonly description: string
    readonly status: WorkflowStatus
    readonly exit_condition: ExitCondition
    readonly variables: readonly WorkflowVariable[]
    readonly actions: readonly Action[]
    readonly edges: readonly Edge[]
}
