// The create/update body that POST/PATCH /api/projects/{id}/hog_flows/ accepts.

/**
 * A wait, written as a number and a unit: `s`, `m`, `h` or `d`.
 *
 * The template literal type refuses a word such as `'soon'` in the editor. `emit`
 * checks the value again, because the type also admits `-1d`, `1e3d` and `0m`, and
 * because the PostHog runtime caps the amount per unit at 60s, 60m, 24h and 30d. Write
 * `1.5h` rather than `90m`.
 *
 * @example
 * ```ts
 * import type { Duration } from '@posthog/workflows'
 *
 * const oneDay: Duration = '1d'
 * const halfHour: Duration = '30m'
 * const dayAndAHalf: Duration = '1.5d'
 * ```
 */
export type Duration = `${number}d` | `${number}h` | `${number}m` | `${number}s`

/** Where a property condition reads its value: the event, the person, or a group. */
export type PropertyType = 'event' | 'person' | 'group'

/** How a property condition compares. `is_set` and `is_not_set` take no value. */
export type PropertyOperator =
    | 'exact'
    | 'is_not'
    | 'icontains'
    | 'not_icontains'
    | 'is_set'
    | 'is_not_set'
    | 'gt'
    | 'lt'

/**
 * One property condition in the definition.
 *
 * Build one with `person`, `eventProperty` or `group` rather than by hand. PostHog
 * compiles the condition to bytecode when it saves, so the definition carries no
 * `bytecode` field.
 */
export interface PropertyCondition {
    /** The property name, for example `plan` or `$current_url`. */
    readonly key: string
    /** The values to compare against. Omitted for `is_set` and `is_not_set`. */
    readonly value?: readonly (string | number | boolean)[]
    readonly operator: PropertyOperator
    readonly type: PropertyType
}

/** One event an event trigger fires on, inside the trigger's filters. */
export interface EventFilter {
    /** The event name, which PostHog uses as both the id and the label. */
    readonly id: string
    readonly name: string
    readonly type: 'events'
    readonly order: number
    /** Conditions the event must also meet. Empty means every occurrence matches. */
    readonly properties: readonly PropertyCondition[]
}

/** The filter block of an event trigger. Build it with `onEvent`. */
export interface ActionFilters {
    readonly events: readonly EventFilter[]
    readonly properties: readonly PropertyCondition[]
    readonly filter_test_accounts: boolean
}

/**
 * The config of the trigger action, discriminated on `type`.
 *
 * Build one with `onEvent` or `onSchedule` and pass it as the workflow's `on`.
 */
export type TriggerConfig = { readonly type: 'event'; readonly filters: ActionFilters } | { readonly type: 'schedule' }

/**
 * One condition of a `conditional_branch` action in the definition.
 *
 * The `filters` wrapper is required. PostHog saves a bare `properties` object without
 * complaint and then compiles the branch to a constant, so the condition never runs.
 * `branch` writes the wrapper, so an author never builds this shape by hand.
 */
export interface BranchCondition {
    readonly name: string
    readonly filters: { readonly properties: readonly PropertyCondition[] }
}

/**
 * The inputs of a `function` or `function_email` action.
 *
 * Every value is wrapped in `{ value: ... }`, which is what makes hog templating such
 * as `{person.properties.email}` resolve at run time. `fn`, `webhook` and `email`
 * write the wrapper.
 */
export type FunctionInputs = Readonly<Record<string, { readonly value: unknown }>>

/**
 * The message an email step sends, at `config.inputs.email.value` in the definition.
 *
 * The content is inline. PostHog copies a referenced library template into the
 * workflow when it saves, so a referenced template would make the stored definition
 * differ from the one that was pushed, and every later push would report a change.
 */
export interface EmailMessage {
    /** Pins one sender by integration id. Empty lets PostHog resolve the project's verified sender. */
    readonly from: { readonly integrationId?: number }
    readonly to: { readonly email: string }
    readonly subject: string
    /** The plain-text body, which every client can show. */
    readonly text: string
    readonly html: string
    /** The preview line some clients show beside the subject. */
    readonly preheader?: string
}

interface ActionBase {
    readonly id: string
    readonly name: string
}

/**
 * One node of the definition, discriminated on `type`.
 *
 * `emit` builds these from the step values a file declares. Read them to inspect what
 * a push will send. The `type` values here are the whole set this package emits.
 */
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
          // PostHog coerces `template_id` to `template-email` whatever the client sends,
          // so the SDK sends that literal and has no route to a saved template UUID.
          readonly config: {
              readonly template_id: 'template-email'
              readonly inputs: { readonly email: { readonly value: EmailMessage } }
          }
      })
    | (ActionBase & { readonly type: 'exit'; readonly config: { readonly reason: string } })

/**
 * One link between two actions of the definition.
 *
 * A `continue` edge is the fall-through, which out of a branch is the no-match path. A
 * `branch` edge carries the `index` of the condition that takes it. `emit` derives
 * every edge from placement, so an index and its edge always agree.
 */
export type Edge =
    | { readonly from: string; readonly to: string; readonly type: 'continue' }
    | { readonly from: string; readonly to: string; readonly type: 'branch'; readonly index: number }

/**
 * When a person leaves the workflow early.
 *
 * `exit_only_at_end` is the default and needs nothing else. The `conversion` variants
 * need a conversion goal, which this package does not yet emit, so a workflow that
 * picks one has no goal and the early exit never fires.
 */
export type ExitCondition =
    | 'exit_only_at_end'
    | 'exit_on_conversion'
    | 'exit_on_trigger_not_matched'
    | 'exit_on_trigger_not_matched_or_conversion'

/**
 * Whether the workflow runs.
 *
 * `draft` accepts no one and sends nothing, `active` runs, and `archived` is retired.
 * A workflow with no `status` is a `draft`.
 */
export type WorkflowStatus = 'draft' | 'active' | 'archived'

/**
 * One variable of the workflow and its default value.
 *
 * Every value is a string on the wire, including a number and a boolean, so write
 * `{ key: 'retries', type: 'number', default: '3' }`. Keys are unique. The whole list is
 * capped at 5120 bytes, measured as the length of each entry serialized to JSON with a
 * space after every separator and every non-ASCII character escaped, added together.
 */
export interface WorkflowVariable {
    readonly key: string
    readonly type: 'string' | 'number' | 'boolean'
    /** The default, as a string. A run can override it. */
    readonly default: string
}

/**
 * The definition: the JSON body a push sends to the PostHog API.
 *
 * `emit` produces it and nothing else writes it. It is deliberately narrow, because
 * `trigger`, `version`, `billable_action_types`, `abort_action`, `action_redirects` and
 * the `draft` fields are read-only on the serializer, and PostHog computes the trigger
 * from the trigger action in `actions`.
 */
export interface WorkflowDefinition {
    /**
     * The workflow's identity in the source file, unique for each team.
     *
     * The PostHog API accepts it from a later backend change on, and ignores it as an
     * unknown field until then.
     */
    readonly key: string
    readonly name: string
    /** Empty when the file sets no description. */
    readonly description: string
    readonly status: WorkflowStatus
    readonly exit_condition: ExitCondition
    /** Empty when the file declares no variables. */
    readonly variables: readonly WorkflowVariable[]
    /** The trigger action first, then one action per placement, then the exit action. */
    readonly actions: readonly Action[]
    readonly edges: readonly Edge[]
}
