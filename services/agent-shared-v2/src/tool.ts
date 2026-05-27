/**
 * Native tool contract. Every tool in the agent-tools package exports these three:
 *   - id    : "posthog.query.v1" — versioned id; bumping creates a parallel tool
 *   - schema: declarative args/returns + requirements (description, cost hint)
 *   - run   : the actual call
 *
 * The runner imports tools by id, validates args with schema.args (a zod
 * schema), and calls run() in-process. No sandbox for native tools.
 *
 * The authoring layer reads `schema` to know what tools exist and what each
 * one needs, so the wizard can compose a spec.
 */

import { z, ZodTypeAny } from 'zod'

export interface NativeToolSchema {
    description: string
    args: ZodTypeAny
    returns: ZodTypeAny
    /** Required integrations / scopes the team must have to use this tool. */
    requires: {
        integrations: string[]
        scopes: string[]
    }
    /** Hint for runner timeout selection + authoring UI cost annotations. */
    cost_hint: 'cheap' | 'medium' | 'expensive'
}

export interface ToolContext {
    teamId: number
    sessionId: string
    /** Resolved integration tokens, keyed by integration id ("slack:T01..."). */
    integrations: Record<string, IntegrationCredentials>
    /** Fetch resolved secret value for a name from spec.secrets. */
    secret(name: string): string | undefined
    /** Structured log out of the tool — surfaces in the session log. */
    log(level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void
}

export interface IntegrationCredentials {
    kind: string
    access_token: string
    refresh_token?: string
    metadata?: Record<string, unknown>
}

export interface NativeTool<TArgs = unknown, TReturn = unknown> {
    id: string
    schema: NativeToolSchema
    run(args: TArgs, ctx: ToolContext): Promise<TReturn>
}

/** Helper to author a tool with type-safe args/returns inferred from zod. */
export function defineNativeTool<TArgsSchema extends ZodTypeAny, TReturnSchema extends ZodTypeAny>(def: {
    id: string
    description: string
    args: TArgsSchema
    returns: TReturnSchema
    requires?: Partial<NativeToolSchema['requires']>
    cost_hint?: NativeToolSchema['cost_hint']
    run: (args: z.infer<TArgsSchema>, ctx: ToolContext) => Promise<z.infer<TReturnSchema>>
}): NativeTool<z.infer<TArgsSchema>, z.infer<TReturnSchema>> {
    return {
        id: def.id,
        schema: {
            description: def.description,
            args: def.args,
            returns: def.returns,
            requires: {
                integrations: def.requires?.integrations ?? [],
                scopes: def.requires?.scopes ?? [],
            },
            cost_hint: def.cost_hint ?? 'medium',
        },
        run: def.run,
    }
}
