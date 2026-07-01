import { connect, kea, key, path, props, selectors } from 'kea'

import { resolveToolCall } from '../components/tool/toolResolver'
import type { ToolInvocation } from '../types/streamTypes'
import { runStreamLogic } from './runStreamLogic'
import type { toolStreamLogicType } from './toolStreamLogicType'

export interface ToolStreamLogicProps {
    /** Same key `runStreamLogic` uses — conversation id for Max, run/task id for a task viewer. */
    streamKey: string
}

/** A tool invocation paired with its resolved registry key (the inner sub-tool for PostHog's exec MCP). */
export interface ResolvedInvocation {
    invocation: ToolInvocation
    resolvedKey: string
}

/**
 * Selector view over `runStreamLogic`'s streamed tool invocations, keyed by resolved registry key and
 * raw tool name, for a *non-React* consumer (e.g. a logic that reacts to a `create_insight` completing).
 * The projection stays pure — no push events here; a logic subscribes with `kea-subscriptions` on its
 * own side, or a component uses `useToolStream`. Keyed by `streamKey` so it shares `runStreamLogic`'s
 * per-stream instance.
 */
export const toolStreamLogic = kea<toolStreamLogicType>([
    props({} as ToolStreamLogicProps),
    key((props) => props.streamKey),
    path((key) => ['products', 'posthog_ai', 'frontend', 'logics', 'toolStreamLogic', key]),

    connect((props: ToolStreamLogicProps) => ({
        values: [runStreamLogic({ streamKey: props.streamKey }), ['toolInvocations']],
    })),

    selectors({
        resolvedInvocations: [
            (s) => [s.toolInvocations],
            (toolInvocations: Map<string, ToolInvocation>): ResolvedInvocation[] =>
                Array.from(toolInvocations.values()).map((invocation) => ({
                    invocation,
                    resolvedKey: resolveToolCall(invocation).resolvedKey,
                })),
        ],
        // resolvedKey → invocations. A consumer indexes the tool set it cares about.
        toolsByResolvedKey: [
            (s) => [s.resolvedInvocations],
            (resolved: ResolvedInvocation[]): Record<string, ToolInvocation[]> => {
                const byKey: Record<string, ToolInvocation[]> = {}
                for (const { invocation, resolvedKey } of resolved) {
                    ;(byKey[resolvedKey] ??= []).push(invocation)
                }
                return byKey
            },
        ],
        // rawToolName → invocations, so a consumer can also address tools by their wire name.
        toolsByRawName: [
            (s) => [s.toolInvocations],
            (toolInvocations: Map<string, ToolInvocation>): Record<string, ToolInvocation[]> => {
                const byName: Record<string, ToolInvocation[]> = {}
                for (const invocation of toolInvocations.values()) {
                    ;(byName[invocation.rawToolName] ??= []).push(invocation)
                }
                return byName
            },
        ],
    }),
])
