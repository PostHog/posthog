// The create/update body that POST/PATCH /api/projects/{id}/hog_flows/ accepts.

import type { PassThroughActionConfig } from './steps.js'

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

/** One value a property condition compares against. */
export type PropertyValue = string | number | boolean

/** A scalar value or a list of values a property condition compares against. */
export type PropertyConditionValue = PropertyValue | readonly PropertyValue[]

/** Operators that store their own operator name as the value and need no author value. */
export type SetPropertyOperator = 'is_set' | 'is_not_set'

/** How a property condition compares. */
export type PropertyOperator =
    | 'exact'
    | 'is_not'
    | 'icontains'
    | 'not_icontains'
    | 'starts_with'
    | 'not_starts_with'
    | 'ends_with'
    | 'not_ends_with'
    | 'regex'
    | 'not_regex'
    | 'gt'
    | 'gte'
    | 'lt'
    | 'lte'
    | 'is_set'
    | 'is_not_set'
    | 'is_date_exact'
    | 'is_date_before'
    | 'is_date_after'
    | 'between'
    | 'not_between'
    | 'min'
    | 'max'
    | 'in'
    | 'not_in'
    | 'is_cleaned_path_exact'
    | 'flag_evaluates_to'
    | 'semver_eq'
    | 'semver_neq'
    | 'semver_gt'
    | 'semver_gte'
    | 'semver_lt'
    | 'semver_lte'
    | 'semver_tilde'
    | 'semver_caret'
    | 'semver_wildcard'
    | 'icontains_multi'
    | 'not_icontains_multi'

/** Operators that compare against an author-provided value. */
export type ValuePropertyOperator = Exclude<PropertyOperator, SetPropertyOperator>

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
    /** The value to compare against. `is_set` and `is_not_set` store the operator here. */
    readonly value?: PropertyConditionValue | SetPropertyOperator
    readonly operator: PropertyOperator
    readonly type: PropertyType
    /** Required when `type` is `group`, because PostHog resolves the property from its group type. */
    readonly group_type_index?: number
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
export type TriggerConfig =
    | { readonly type: 'event'; readonly filters: ActionFilters }
    | { readonly type: 'schedule' }
    | ({ readonly type: string } & JsonObject)

export interface TriggerActionOptions {
    readonly name?: string
    readonly description?: string
}

/**
 * A trigger config as a file writes it, before emit resolves each `secret` in `inputs`.
 */
export type TriggerAuthoringConfig = (TriggerConfig | ({ readonly type: string } & PassThroughActionConfig)) & {
    readonly __workflowTriggerName?: string
    readonly __workflowTriggerDescription?: string
}

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
export type JsonValue = string | number | boolean | null | JsonObject | JsonArray
export type JsonObject = { readonly [key: string]: JsonValue }
export type JsonArray = readonly JsonValue[]

export type FunctionInputs = Readonly<Record<string, { readonly value: JsonValue }>>

/**
 * The message an email step sends, at `config.inputs.email.value` in the definition.
 *
 * The content is inline. PostHog copies a referenced library template into the
 * workflow when it saves, so a referenced template would make the stored definition
 * differ from the one that was pushed, and every later push would report a change.
 */
export interface EmailMessage {
    readonly from: EmailSender
    readonly to: { readonly email: string }
    readonly subject: string
    /** The plain-text body, which every client can show. */
    readonly text: string
    readonly html: string
    /**
     * The visual editor's copy of `html`, as one custom HTML block. `email` builds it the
     * same way PostHog does for an email that arrives without one, so the stored message
     * is the pushed message and a second push reports no change.
     */
    readonly design: EmailDesign
    /** The preview line some clients show beside the subject. */
    readonly preheader?: string
}

/**
 * The sender of an email step, as PostHog stores it.
 *
 * PostHog sends from one of the email integrations in `integrationIds`, which are the
 * ids of the project's verified senders. `integrationId` is the first of them, because
 * the runtime requires it and treats the list as optional. `email` writes both from one
 * list, so they cannot disagree.
 */
export interface EmailSender {
    readonly integrationId: number
    /** One to ten sender ids. With several, PostHog picks one per run. */
    readonly integrationIds: readonly number[]
    /** A sender address on the verified domain, or hog templating that resolves to one. */
    readonly email?: string
    /** The sender name shown beside the address. */
    readonly name?: string
}

/**
 * An Unlayer design, which is what the visual email editor opens.
 *
 * The SDK never lays an email out visually, so the only design it writes is the one
 * `email` builds around the `html` body.
 */
export type EmailDesign = Readonly<Record<string, unknown>>

export interface ActionOutputVariable {
    readonly key: string
    readonly result_path?: string | null
    readonly spread?: boolean | null
    readonly label?: string | null
}

export type ActionOutputVariables = ActionOutputVariable | readonly ActionOutputVariable[]

export interface StepFilters {
    readonly events?: readonly JsonValue[]
    readonly properties?: readonly JsonValue[]
    readonly actions?: readonly JsonValue[]
    readonly [key: string]: JsonValue | readonly JsonValue[] | undefined
}

interface ActionBase {
    readonly id: string
    readonly name: string
    /**
     * What the step is for, from the step's `description`.
     *
     * Absent when the step sets none, which PostHog stores as an empty string.
     */
    readonly description?: string
    readonly filters?: StepFilters | null
    readonly on_error?: 'continue' | 'abort' | null
    readonly output_variable?: ActionOutputVariables | null
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
    | (ActionBase & { readonly type: 'function_sms'; readonly config: JsonObject })
    | (ActionBase & { readonly type: 'function_push'; readonly config: JsonObject })
    | (ActionBase & { readonly type: 'wait_until_condition'; readonly config: JsonObject })
    | (ActionBase & { readonly type: 'wait_until_time_window'; readonly config: JsonObject })
    | (ActionBase & { readonly type: 'random_cohort_branch'; readonly config: JsonObject })
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
 * `exit_only_at_end` is the default and needs nothing else. PostHog also knows the two
 * `conversion` variants, which need a conversion goal this package does not emit; without
 * the goal the early exit never fires, so they arrive together with it.
 */
export type ExitCondition = 'exit_only_at_end' | 'exit_on_trigger_not_matched'

/**
 * Whether the workflow runs.
 *
 * `draft` accepts no one and sends nothing, `active` runs, and `archived` is retired.
 * A definition includes this field only when the file sets it. When a new workflow is
 * created without it, PostHog creates the workflow as a draft.
 */
export type WorkflowStatus = 'draft' | 'active' | 'archived'

/**
 * One variable of the workflow and its default value.
 *
 * Every value is a string on the wire, including a number and a boolean, so write
 * `{ key: 'retries', type: 'number', default: '3' }`. Keys are unique. The whole list is
 * capped at 5120 bytes, measured as the length of the serialized JSON array with a
 * space after every separator and every non-ASCII character escaped.
 */
export interface WorkflowVariable {
    readonly key: string
    readonly type: 'string' | 'number' | 'boolean'
    /** The default, as a string. A run can override it. */
    readonly default: string
    /** The label the editor shows for the variable. */
    readonly label?: string
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
     * The workflow's identity in source and push tooling.
     *
     * This package emits it in the definition. PostHog stores it as the workflow's
     * source identity, and push tooling uses it to create or update the same workflow.
     */
    readonly key: string
    readonly name: string
    /** Empty when the file sets no description. */
    readonly description: string
    readonly status?: WorkflowStatus
    readonly exit_condition: ExitCondition
    /** Empty when the file declares no variables. */
    readonly variables: readonly WorkflowVariable[]
    /** The trigger action first, then one action per placement, then the exit action. */
    readonly actions: readonly Action[]
    readonly edges: readonly Edge[]
}
