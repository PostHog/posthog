// A step is a frozen value with no id and no position, so one value can sit at two
// places in one graph and `emit` derives the ids and the edges.

import type { Duration, EmailMessage, PropertyCondition, PropertyOperator, PropertyType } from './definition.js'

/**
 * A named environment variable. The name travels in the source, the value never
 * does: `emit` reads the variable from the deployer's environment and always sends
 * the value, so PostHog never has to recover a secret it was not sent.
 */
export interface SecretRef {
    readonly __secret: string
}

export function secret(envName: string): SecretRef {
    return Object.freeze({ __secret: envName })
}

export function isSecretRef(value: unknown): value is SecretRef {
    return typeof value === 'object' && value !== null && typeof (value as SecretRef).__secret === 'string'
}

export type Conditions = readonly [PropertyCondition, ...PropertyCondition[]]

/**
 * A sub-path is a non-empty tuple of step values. `readonly Step[]` would accept
 * `[]`, and an empty branch path emits a branch edge aimed at the no-match target,
 * which silently makes the branch decide nothing.
 */
export type Path = readonly [Step, ...Step[]]

export interface BranchSpec {
    readonly name: string
    readonly when: Conditions
    readonly then: Path
}

/** `id` pins the action id, so a rename does not move it. */
interface StepBase {
    readonly name: string
    readonly id?: string
}

export type Step =
    | Readonly<StepBase & { kind: 'delay'; duration: Duration }>
    | Readonly<StepBase & { kind: 'function'; templateId: string; inputs: Readonly<Record<string, unknown>> }>
    | Readonly<StepBase & { kind: 'email'; email: EmailMessage }>
    | Readonly<StepBase & { kind: 'branch'; branches: readonly [BranchSpec, ...BranchSpec[]] }>

function withId<T extends object>(options: { readonly id?: string }, step: T): Readonly<T & { id?: string }> {
    return Object.freeze(options.id === undefined ? step : { ...step, id: options.id })
}

export function delay(duration: Duration, options: { name: string; id?: string }): Step {
    return withId(options, { kind: 'delay' as const, name: options.name, duration })
}

/**
 * The escape hatch: any CDP template by id. The compiler does not know the
 * template's input schema, so PostHog validates the inputs when the push lands.
 */
export function fn(options: {
    name: string
    id?: string
    templateId: string
    inputs: Readonly<Record<string, unknown>>
}): Step {
    return withId(options, {
        kind: 'function' as const,
        name: options.name,
        templateId: options.templateId,
        inputs: options.inputs,
    })
}

/** Its signing secret is the one secret in the v1 surface. */
export function webhook(options: {
    name: string
    id?: string
    url: string
    method?: 'POST' | 'PUT' | 'PATCH' | 'GET' | 'DELETE'
    body?: Record<string, unknown>
    headers?: Record<string, string>
    signingSecret?: SecretRef
}): Step {
    const inputs: Record<string, unknown> = {
        url: options.url,
        method: options.method ?? 'POST',
        body: options.body ?? {},
    }
    if (options.headers !== undefined) {
        inputs.headers = options.headers
    }
    if (options.signingSecret !== undefined) {
        inputs.signing_secret = options.signingSecret
    }
    return fn({
        ...(options.id === undefined ? {} : { id: options.id }),
        name: options.name,
        templateId: 'template-webhook',
        inputs,
    })
}

/**
 * A typed email step. The content is inline, because PostHog materializes a
 * referenced library template when it writes, and the stored definition would then
 * never match the one the push sent.
 */
export function email(options: {
    name: string
    id?: string
    to: string
    subject: string
    text: string
    html: string
    preheader?: string
    fromIntegrationId?: number
}): Step {
    const message: EmailMessage = {
        from: options.fromIntegrationId === undefined ? {} : { integrationId: options.fromIntegrationId },
        to: { email: options.to },
        subject: options.subject,
        text: options.text,
        html: options.html,
        ...(options.preheader === undefined ? {} : { preheader: options.preheader }),
    }
    return withId(options, { kind: 'email' as const, name: options.name, email: message })
}

export function branch(options: { name: string; id?: string; branches: readonly [BranchSpec, ...BranchSpec[]] }): Step {
    return withId(options, { kind: 'branch' as const, name: options.name, branches: options.branches })
}

/** Names a reusable sub-path. Identity is the tuple, so a path is a value like a step. */
export function path(...steps: Path): Path {
    return steps
}

function condition(type: PropertyType) {
    return (
        key: string,
        operator: PropertyOperator,
        value?: readonly (string | number | boolean)[]
    ): PropertyCondition => (value === undefined ? { key, operator, type } : { key, operator, value, type })
}

export const person = condition('person')
export const eventProperty = condition('event')
export const group = condition('group')
