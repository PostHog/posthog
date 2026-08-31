import { MakeLogicType, actions, connect, kea, key, listeners, path, props } from 'kea'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import type { HogFlow, HogFlowAction } from '../types'

const DURATION_REGEX = /^(\d*\.?\d*)([dhms])$/
const OFFSET_REGEX = /^(-?)(\d*\.?\d+)([dhms])$/
const AUTO_DESCRIPTION_REGEX = /^Wait for \d*\.?\d+ (second|minute|hour|day)s?\.$/
const LEGACY_DEFAULT_DESCRIPTION = 'Wait for a specified duration.'
const UNCONFIGURED_UNTIL_DESCRIPTION = 'Wait until a date on the person or event.'

// A property key only reads back as `person.properties.foo` when it is a bare identifier. Anything
// else (spaces, a leading $, punctuation) has to go through brackets to survive the round trip.
const BARE_IDENTIFIER_REGEX = /^[A-Za-z_][A-Za-z0-9_]*$/
// An event's own properties are `properties.foo`, with no prefix: the expression runs against the same
// globals as a filter, where `event` is the event's name rather than an object. `event.properties.foo`
// reads a field off that string, resolves to nothing, and aborts every run of the step.
const DOTTED_EXPRESSION_REGEX = /^(?:(person)\.)?properties\.([A-Za-z_][A-Za-z0-9_]*)$/
const BRACKETED_EXPRESSION_REGEX = /^(?:(person)\.)?properties\['((?:[^'\\]|\\.)*)'\]$/

const UNIT_LABELS: Record<string, string> = {
    s: 'second',
    m: 'minute',
    h: 'hour',
    d: 'day',
}

export type DelayActionConfig = Extract<HogFlowAction, { type: 'delay' }>['config']

export type DelayMode = 'duration' | 'until'
/** 'on' means no offset at all: wait for the date itself. */
export type DelayOffsetDirection = 'on' | 'before' | 'after'
export type DelayPropertySource = 'person' | 'event'

export interface DelayProperty {
    source: DelayPropertySource
    key: string
}

export interface DelayOffset {
    /** An unsigned duration string, the same shape HogFlowDuration edits. */
    duration: string
    direction: DelayOffsetDirection
}

/** Only the fields the timezone controls change, merged onto whatever else delay_until holds. */
export interface DelayTimezone {
    timezone?: string | null
    use_person_timezone?: boolean
    fallback_timezone?: string | null
}

/** Matches the executor's default when no zone is configured. */
export const DEFAULT_DELAY_TIMEZONE = 'UTC'

export const DEFAULT_DELAY_DURATION = '10m'
// Mirrors the executor's cap in nodejs/src/cdp/services/hogflows/actions/delay.ts.
export const DEFAULT_MAX_DELAY_DURATION = '30d'

export function getDelayMode(config: DelayActionConfig): DelayMode {
    return config.delay_until ? 'until' : 'duration'
}

export function buildDelayExpression({ source, key }: DelayProperty): string {
    const prefix = source === 'person' ? 'person.properties' : 'properties'
    if (BARE_IDENTIFIER_REGEX.test(key)) {
        return `${prefix}.${key}`
    }
    return `${prefix}['${key.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}']`
}

/** Null for an expression the builder did not compose, e.g. hand-written SQL saved through the API. */
export function parseDelayExpression(expression: string): DelayProperty | null {
    const dotted = expression.match(DOTTED_EXPRESSION_REGEX)
    if (dotted) {
        return { source: dotted[1] === 'person' ? 'person' : 'event', key: dotted[2] }
    }
    const bracketed = expression.match(BRACKETED_EXPRESSION_REGEX)
    if (bracketed) {
        return { source: bracketed[1] === 'person' ? 'person' : 'event', key: bracketed[2].replace(/\\(.)/g, '$1') }
    }
    return null
}

/** Undefined for direction 'on', so "wait for the date itself" saves no offset at all. */
export function buildDelayOffset({ duration, direction }: DelayOffset): string | undefined {
    if (direction === 'on' || !DURATION_REGEX.test(duration) || !Number.isFinite(parseFloat(duration))) {
        return undefined
    }
    return `${direction === 'before' ? '-' : ''}${duration}`
}

export function parseDelayOffset(offset: string | undefined): DelayOffset {
    const parts = offset?.match(OFFSET_REGEX)
    if (!parts) {
        // A day is the offset almost every reminder uses, so it is the amount to start from once
        // someone switches off 'on'.
        return { duration: '1d', direction: 'on' }
    }
    return { duration: `${parts[2]}${parts[3]}`, direction: parts[1] === '-' ? 'before' : 'after' }
}

/** "2 days" for '2d'. Null when there is no number to read, e.g. a cleared duration input. */
export function getDurationText(duration: string): string | null {
    const parts = duration.match(DURATION_REGEX)
    const number = parseFloat(parts?.[1] ?? '')
    if (!Number.isFinite(number)) {
        return null
    }
    const unitLabel = UNIT_LABELS[parts?.[2] ?? 'm'] ?? 'minute'
    return `${number} ${unitLabel}${number !== 1 ? 's' : ''}`
}

export function getDelayDescription(config: DelayActionConfig): string {
    if (config.delay_until) {
        const expression = config.delay_until.expression
        if (!expression.trim()) {
            return UNCONFIGURED_UNTIL_DESCRIPTION
        }
        // The property name alone reads better than the expression it was composed from, but an
        // expression the builder cannot read back has nothing shorter to show.
        const dateText = parseDelayExpression(expression)?.key ?? expression
        const offsetText = getDurationText(config.delay_until.offset?.replace('-', '') ?? '')
        if (!offsetText || !config.delay_until.offset) {
            return `Wait until ${dateText}.`
        }
        const direction = config.delay_until.offset.startsWith('-') ? 'before' : 'after'
        return `Wait until ${offsetText} ${direction} ${dateText}.`
    }

    // No valid number yet (e.g. the input was cleared) - keep a neutral description
    const durationText = getDurationText(config.delay_duration ?? '')
    return durationText ? `Wait for ${durationText}.` : LEGACY_DEFAULT_DESCRIPTION
}

export function shouldAutoUpdateDescription(description: string | undefined, config?: DelayActionConfig): boolean {
    return (
        // Agent-created actions can arrive with no description at all, so treat an absent one like an empty one.
        !description ||
        description.trim() === '' ||
        AUTO_DESCRIPTION_REGEX.test(description) ||
        description === LEGACY_DEFAULT_DESCRIPTION ||
        description === UNCONFIGURED_UNTIL_DESCRIPTION ||
        // An until-mode description ends in a property name, which no regex can tell apart from a
        // description someone typed. Comparing against what the step's current config generates
        // identifies the auto-written one exactly.
        (config !== undefined && description === getDelayDescription(config))
    )
}

function findDelayAction(workflow: HogFlow, actionId: string): Extract<HogFlowAction, { type: 'delay' }> | undefined {
    const action = workflow.actions.find((a) => a.id === actionId)
    return action?.type === 'delay' ? (action as Extract<HogFlowAction, { type: 'delay' }>) : undefined
}

export type StepDelayLogicProps = {
    workflowLogicProps: WorkflowLogicProps
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface stepDelayLogicValues {
    workflow: HogFlow // workflowLogic
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface stepDelayLogicActions {
    setWorkflowAction: (
        actionId: string,
        action: HogFlowAction
    ) => {
        action: HogFlowAction
        actionId: string
    } // workflowLogic
    setWorkflowActionConfig: (
        actionId: string,
        config:
            | {
                  cohorts: {
                      name?: string | undefined
                      percentage: number
                  }[]
              }
            | {
                  reason?: string | undefined
              }
            | {
                  type: 'schedule'
              }
            | {
                  conditions: {
                      filters: {
                          actions?: any[] | undefined
                          events?: any[] | undefined
                          properties?: any[] | undefined
                      }
                      name?: string | undefined
                  }[]
                  delay_duration?: string | undefined
              }
            | {
                  filters: {
                      all_roles_unassigned?: boolean | undefined
                      assigned_to_user_ids?: number[] | undefined
                      audience_type?: 'accounts' | 'persons' | undefined
                      properties: any[]
                      tag_names?: string[] | undefined
                  }
                  type: 'batch'
              }
            | {
                  filters: {
                      actions?: any[] | undefined
                      events?: any[] | undefined
                      filter_test_accounts?: boolean | undefined
                      properties?: any[] | undefined
                  }
                  type: 'event'
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  type: 'slack-message'
              }
            | {
                  condition: {
                      filters?:
                          | {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                properties?: any[] | undefined
                            }
                          | null
                          | undefined
                      name?: string | undefined
                  }
                  events?:
                      | {
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            name?: string | undefined
                        }[]
                      | undefined
                  max_wait_duration: string
              }
            | {
                  delay_duration?: string | undefined
                  delay_until?:
                      | {
                            bytecode?: any
                            bytecode_error?: string | undefined
                            expression: string
                            fallback_timezone?: string | null | undefined
                            offset?: string | undefined
                            timezone?: string | null | undefined
                            use_person_timezone?: boolean | undefined
                        }
                      | undefined
                  max_delay_duration?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  mappings?:
                      | {
                            disabled?: boolean | undefined
                            filters?: any
                            inputs?:
                                | Record<
                                      string,
                                      {
                                          bytecode?: any
                                          order?: number | undefined
                                          secret?: boolean | undefined
                                          templating?: 'hog' | 'liquid' | undefined
                                          value: any
                                      }
                                  >
                                | null
                                | undefined
                            inputs_schema?:
                                | {
                                      choices?:
                                          | {
                                                label: string
                                                value: string
                                            }[]
                                          | undefined
                                      default?: any
                                      description?: string | undefined
                                      hidden?: boolean | undefined
                                      integration?: string | undefined
                                      integration_field?: string | undefined
                                      integration_key?: string | undefined
                                      key: string
                                      label: string
                                      required?: boolean | undefined
                                      requiredScopes?: string | undefined
                                      requires_field?: string | undefined
                                      secret?: boolean | undefined
                                      templating?: boolean | undefined
                                      type:
                                          | 'boolean'
                                          | 'choice'
                                          | 'customer_analytics_account_properties'
                                          | 'customer_analytics_account_relationships'
                                          | 'dictionary'
                                          | 'email'
                                          | 'integration'
                                          | 'integration_field'
                                          | 'integration_multi'
                                          | 'json'
                                          | 'native_email'
                                          | 'non_failure_status_codes'
                                          | 'number'
                                          | 'posthog_assignee'
                                          | 'posthog_business_hours'
                                          | 'posthog_ticket_tags'
                                          | 'string'
                                          | 'task_mcp_installations'
                                          | 'task_model'
                                          | 'task_repository'
                                  }[]
                                | undefined
                            name: string
                        }[]
                      | undefined
                  template_id: string
                  template_uuid?: string | undefined
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-table'
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-view'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'manual'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'tracking_pixel'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'webhook'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-native-push'
                  template_uuid?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-twilio'
                  template_uuid?: string | undefined
              }
            | {
                  day:
                      | ('friday' | 'monday' | 'saturday' | 'sunday' | 'thursday' | 'tuesday' | 'wednesday')[]
                      | 'any'
                      | 'weekday'
                      | 'weekend'
                  fallback_timezone?: string | null | undefined
                  time: [string, string] | 'any'
                  timezone: string | null
                  use_person_timezone?: boolean | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-email'
                  template_uuid?: string | undefined
                  tracking_enabled?: boolean | undefined
              }
    ) => {
        actionId: string
        config:
            | {
                  cohorts: {
                      name?: string | undefined
                      percentage: number
                  }[]
              }
            | {
                  reason?: string | undefined
              }
            | {
                  type: 'schedule'
              }
            | {
                  conditions: {
                      filters: {
                          actions?: any[] | undefined
                          events?: any[] | undefined
                          properties?: any[] | undefined
                      }
                      name?: string | undefined
                  }[]
                  delay_duration?: string | undefined
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  type: 'slack-message'
              }
            | {
                  filters: {
                      actions?: any[] | undefined
                      events?: any[] | undefined
                      filter_test_accounts?: boolean | undefined
                      properties?: any[] | undefined
                  }
                  type: 'event'
              }
            | {
                  filters: {
                      all_roles_unassigned?: boolean | undefined
                      assigned_to_user_ids?: number[] | undefined
                      audience_type?: 'accounts' | 'persons' | undefined
                      properties: any[]
                      tag_names?: string[] | undefined
                  }
                  type: 'batch'
              }
            | {
                  condition: {
                      filters?:
                          | {
                                actions?: any[] | undefined
                                events?: any[] | undefined
                                properties?: any[] | undefined
                            }
                          | null
                          | undefined
                      name?: string | undefined
                  }
                  events?:
                      | {
                            filters?:
                                | {
                                      actions?: any[] | undefined
                                      events?: any[] | undefined
                                      properties?: any[] | undefined
                                  }
                                | null
                                | undefined
                            name?: string | undefined
                        }[]
                      | undefined
                  max_wait_duration: string
              }
            | {
                  delay_duration?: string | undefined
                  delay_until?:
                      | {
                            bytecode?: any
                            bytecode_error?: string | undefined
                            expression: string
                            fallback_timezone?: string | null | undefined
                            offset?: string | undefined
                            timezone?: string | null | undefined
                            use_person_timezone?: boolean | undefined
                        }
                      | undefined
                  max_delay_duration?: string | undefined
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-table'
              }
            | {
                  filters: {
                      properties?: any[] | undefined
                  }
                  key_property?: string | undefined
                  table_name: string
                  type: 'data-warehouse-view'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  mappings?:
                      | {
                            disabled?: boolean | undefined
                            filters?: any
                            inputs?:
                                | Record<
                                      string,
                                      {
                                          bytecode?: any
                                          order?: number | undefined
                                          secret?: boolean | undefined
                                          templating?: 'hog' | 'liquid' | undefined
                                          value: any
                                      }
                                  >
                                | null
                                | undefined
                            inputs_schema?:
                                | {
                                      choices?:
                                          | {
                                                label: string
                                                value: string
                                            }[]
                                          | undefined
                                      default?: any
                                      description?: string | undefined
                                      hidden?: boolean | undefined
                                      integration?: string | undefined
                                      integration_field?: string | undefined
                                      integration_key?: string | undefined
                                      key: string
                                      label: string
                                      required?: boolean | undefined
                                      requiredScopes?: string | undefined
                                      requires_field?: string | undefined
                                      secret?: boolean | undefined
                                      templating?: boolean | undefined
                                      type:
                                          | 'boolean'
                                          | 'choice'
                                          | 'customer_analytics_account_properties'
                                          | 'customer_analytics_account_relationships'
                                          | 'dictionary'
                                          | 'email'
                                          | 'integration'
                                          | 'integration_field'
                                          | 'integration_multi'
                                          | 'json'
                                          | 'native_email'
                                          | 'non_failure_status_codes'
                                          | 'number'
                                          | 'posthog_assignee'
                                          | 'posthog_business_hours'
                                          | 'posthog_ticket_tags'
                                          | 'string'
                                          | 'task_mcp_installations'
                                          | 'task_model'
                                          | 'task_repository'
                                  }[]
                                | undefined
                            name: string
                        }[]
                      | undefined
                  template_id: string
                  template_uuid?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'manual'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'tracking_pixel'
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  template_id: string
                  template_uuid?: string | undefined
                  type: 'webhook'
              }
            | {
                  day:
                      | ('friday' | 'monday' | 'saturday' | 'sunday' | 'thursday' | 'tuesday' | 'wednesday')[]
                      | 'any'
                      | 'weekday'
                      | 'weekend'
                  fallback_timezone?: string | null | undefined
                  time: [string, string] | 'any'
                  timezone: string | null
                  use_person_timezone?: boolean | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-native-push'
                  template_uuid?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-twilio'
                  template_uuid?: string | undefined
              }
            | {
                  inputs: Record<
                      string,
                      {
                          bytecode?: any
                          order?: number | undefined
                          secret?: boolean | undefined
                          templating?: 'hog' | 'liquid' | undefined
                          value: any
                      }
                  >
                  message_category_id?: string | undefined
                  message_category_type?: 'marketing' | 'transactional' | undefined
                  template_id: 'template-email'
                  template_uuid?: string | undefined
                  tracking_enabled?: boolean | undefined
              }
    } // workflowLogic
    setDelayMode: (
        actionId: string,
        mode: DelayMode
    ) => {
        actionId: string
        mode: DelayMode
    }
    setDelayOffset: (
        actionId: string,
        offset: DelayOffset
    ) => {
        actionId: string
        offset: DelayOffset
    }
    setDelayProperty: (
        actionId: string,
        property: DelayProperty
    ) => {
        actionId: string
        property: DelayProperty
    }
    setDelayTimezone: (
        actionId: string,
        timezone: DelayTimezone
    ) => {
        actionId: string
        timezone: DelayTimezone
    }
    setDelayWorkflowActionConfig: (
        actionId: string,
        config: DelayActionConfig
    ) => {
        actionId: string
        config: {
            delay_duration?: string | undefined
            delay_until?:
                | {
                      bytecode?: any
                      bytecode_error?: string | undefined
                      expression: string
                      fallback_timezone?: string | null | undefined
                      offset?: string | undefined
                      timezone?: string | null | undefined
                      use_person_timezone?: boolean | undefined
                  }
                | undefined
            max_delay_duration?: string | undefined
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface stepDelayLogicMeta {
    key: string
}

export type stepDelayLogicType = MakeLogicType<
    stepDelayLogicValues,
    stepDelayLogicActions,
    StepDelayLogicProps,
    stepDelayLogicMeta
>

export const stepDelayLogic = kea<stepDelayLogicType>([
    path((key) => ['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'stepDelayLogic', key]),
    props({} as StepDelayLogicProps),
    key(({ workflowLogicProps }: StepDelayLogicProps) => workflowLogicProps.id || 'new'),
    connect(({ workflowLogicProps }: StepDelayLogicProps) => ({
        values: [workflowLogic(workflowLogicProps), ['workflow']],
        actions: [workflowLogic(workflowLogicProps), ['setWorkflowActionConfig', 'setWorkflowAction']],
    })),
    actions({
        setDelayWorkflowActionConfig: (actionId: string, config: DelayActionConfig) => ({ actionId, config }),
        setDelayMode: (actionId: string, mode: DelayMode) => ({ actionId, mode }),
        setDelayProperty: (actionId: string, property: DelayProperty) => ({ actionId, property }),
        setDelayOffset: (actionId: string, offset: DelayOffset) => ({ actionId, offset }),
        setDelayTimezone: (actionId: string, timezone: DelayTimezone) => ({ actionId, timezone }),
    }),
    listeners(({ values, actions, cache }) => ({
        setDelayWorkflowActionConfig: ({ actionId, config }) => {
            // Read before the write: whether the description was auto-written is a question about the
            // config it was generated from, which the dispatch below replaces.
            const previous = findDelayAction(values.workflow, actionId)

            actions.setWorkflowActionConfig(actionId, config)

            if (!previous || !shouldAutoUpdateDescription(previous.description, previous.config)) {
                return
            }
            const action = findDelayAction(values.workflow, actionId)
            if (action) {
                actions.setWorkflowAction(actionId, { ...action, description: getDelayDescription(config) })
            }
        },

        setDelayMode: ({ actionId, mode }) => {
            const action = findDelayAction(values.workflow, actionId)
            const leaving = action ? getDelayMode(action.config) : undefined
            if (!action || leaving === mode) {
                return
            }
            // The config is replaced rather than merged, because the backend accepts exactly one of the
            // two modes and rejects a config carrying both. So the mode being left is remembered here for
            // as long as the editor is open: switching across and back otherwise resets a configured
            // duration to the default, and drops the chosen date, its offset and its timezone.
            const remembered: Record<string, DelayActionConfig> = (cache.configByMode ??= {})
            const restored = remembered[`${actionId}:${mode}`]
            remembered[`${actionId}:${leaving}`] = action.config

            if (mode === 'duration') {
                actions.setDelayWorkflowActionConfig(actionId, {
                    delay_duration: restored?.delay_duration ?? DEFAULT_DELAY_DURATION,
                })
                return
            }
            // max_delay_duration is only meaningful alongside delay_until, so it comes across from
            // whichever side of the switch still carries it, and never stays on a duration delay.
            const maxDelayDuration = action.config.max_delay_duration ?? restored?.max_delay_duration
            actions.setDelayWorkflowActionConfig(actionId, {
                delay_until: restored?.delay_until ?? { expression: '' },
                ...(maxDelayDuration ? { max_delay_duration: maxDelayDuration } : {}),
            })
        },

        setDelayProperty: ({ actionId, property }) => {
            const action = findDelayAction(values.workflow, actionId)
            if (!action?.config.delay_until) {
                return
            }
            actions.setDelayWorkflowActionConfig(actionId, {
                ...action.config,
                delay_until: {
                    ...action.config.delay_until,
                    expression: buildDelayExpression(property),
                },
            })
        },

        setDelayOffset: ({ actionId, offset }) => {
            const action = findDelayAction(values.workflow, actionId)
            if (!action?.config.delay_until) {
                return
            }
            const serialized = buildDelayOffset(offset)
            // Only direction 'on' truly means "no offset". A cleared amount also serializes to undefined,
            // but writing it reads back as 'on' and unmounts the amount field mid-edit. Keep the last
            // stored offset in that case, so the author can type a replacement into the field they cleared.
            if (serialized === undefined && offset.direction !== 'on') {
                return
            }
            actions.setDelayWorkflowActionConfig(actionId, {
                ...action.config,
                delay_until: {
                    ...action.config.delay_until,
                    offset: serialized,
                },
            })
        },

        setDelayTimezone: ({ actionId, timezone }) => {
            const action = findDelayAction(values.workflow, actionId)
            if (!action?.config.delay_until) {
                return
            }
            actions.setDelayWorkflowActionConfig(actionId, {
                ...action.config,
                delay_until: { ...action.config.delay_until, ...timezone },
            })
        },
    })),
])
