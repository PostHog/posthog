/**
 * Adapter: dock-context → `<AgentChat />`, driven by `useFakeRunner`.
 *
 * Owns:
 *   - the in-flight `ChatSession` (via the fake runner)
 *   - the registered `@posthog/ui/*` handlers — the `focus` handler
 *     pushes a target into `focus-context` and navigates the route
 *     when needed, so the dock actually drives the read panel
 *
 * When the script's tool calls declare `mutations[]`, the dock POSTs
 * the patches against the real REST surface (via `apiClient`). The
 * downstream effect — overlay update + SSE event — flows through the
 * same network seam regardless of whether the runner is the fake
 * in-process one (v0) or the real agent runner (v0.2+).
 */

'use client'

import { useRouter } from 'next/navigation'
import { useMemo } from 'react'

import { AgentChat, useFakeRunner, type ClientToolHandler, type ResolvedMutation } from '@posthog/agent-chat'
import type { FocusArgs, FocusResult, ToastArgs, ToastResult } from '@posthog/agent-chat'
import {
    conciergeScripts,
    fallbackScript,
    playgroundScripts,
    playgroundSession,
    waitingSession,
} from '@posthog/agent-chat/fixtures'

import { patchRevisionSpec, writeBundleFile } from '@/lib/apiClient'

import { useDockStore } from './dock-context'
import { useFocusStore, type FocusTarget } from './focus-context'

function isBundleFilePayload(payload: unknown): payload is { newContent: string } {
    return (
        typeof payload === 'object' &&
        payload !== null &&
        'newContent' in payload &&
        typeof (payload as { newContent: unknown }).newContent === 'string'
    )
}

function isSpecPatchPayload(payload: unknown): payload is { patch: Record<string, unknown> } {
    return (
        typeof payload === 'object' &&
        payload !== null &&
        'patch' in payload &&
        typeof (payload as { patch: unknown }).patch === 'object' &&
        (payload as { patch: unknown }).patch !== null
    )
}

async function applyMutation(m: ResolvedMutation): Promise<void> {
    if (m.entityKey.startsWith('bundle-file:') && isBundleFilePayload(m.payload)) {
        const [, slug, ...rest] = m.entityKey.split(':')
        const path = rest.join(':')
        await writeBundleFile(slug, path, { newContent: m.payload.newContent, mutationId: m.mutationId })
        return
    }
    if (m.entityKey.startsWith('revision-spec:') && isSpecPatchPayload(m.payload)) {
        const [, slug, revisionId] = m.entityKey.split(':')
        await patchRevisionSpec(revisionId, {
            applicationSlug: slug,
            patch: m.payload.patch,
            mutationId: m.mutationId,
        })
        return
    }
    // Unknown entity kind / missing payload — swallow so playback keeps going.
    // eslint-disable-next-line no-console
    console.warn('[dock] ignoring unsupported tool mutation', m.entityKey)
}

export function Dock(): React.ReactElement {
    const { context, exitPlayground } = useDockStore()
    const focus = useFocusStore()
    const router = useRouter()

    /**
     * `@posthog/ui/focus` — pushes a target into focus-context so the
     * agent-detail page (or whichever surface is mounted) can react.
     * Also routes the URL when navigation across pages is required.
     *
     * When focus mode is paused, returns `{ focused: false }` so the
     * agent's prompt — which is written defensively — falls back to
     * narrating in text instead of expecting the UI to follow.
     */
    const focusHandler: ClientToolHandler<FocusArgs, FocusResult> = useMemo(
        () => ({
            id: '@posthog/ui/focus',
            handle: (args) => {
                if (!focus.enabled) {
                    return { focused: false, reason: 'user_paused_follow' }
                }

                // Resolve the agent slug — explicit on the args, falling back to
                // the current context's agent if any.
                const contextSlug =
                    context.mode === 'concierge' && 'agent' in context.page
                        ? context.page.agent.slug
                        : context.mode === 'playground'
                          ? context.agent.slug
                          : undefined

                let target: FocusTarget
                let routeTarget: string | null = null
                const mutationId = args.mutationId

                if (args.kind === 'file') {
                    target = { kind: 'file', agentSlug: contextSlug, path: args.path, mutationId }
                    if (contextSlug) {
                        routeTarget = `/agents/${contextSlug}`
                    }
                } else if (args.kind === 'revision') {
                    target = { kind: 'revision', agentSlug: contextSlug, revisionId: args.revisionId, mutationId }
                    if (contextSlug) {
                        routeTarget = `/agents/${contextSlug}`
                    }
                } else if (args.kind === 'session') {
                    target = { kind: 'session', agentSlug: contextSlug, sessionId: args.sessionId, mutationId }
                    if (contextSlug) {
                        // Sessions get their own page — route there directly.
                        routeTarget = `/agents/${contextSlug}/sessions/${args.sessionId}`
                    }
                } else if (args.kind === 'spec_section') {
                    target = { kind: 'spec_section', agentSlug: contextSlug, section: args.section, mutationId }
                    if (contextSlug) {
                        routeTarget = `/agents/${contextSlug}`
                    }
                } else {
                    // Exhaustive — but defensive.
                    return { focused: false, reason: 'unknown_focus_kind' }
                }

                focus.setTarget(target)
                if (routeTarget) {
                    router.push(routeTarget)
                }

                return { focused: true, kind: args.kind, mutationId }
            },
        }),
        [context, focus, router]
    )

    const toastHandler: ClientToolHandler<ToastArgs, ToastResult> = useMemo(
        () => ({
            id: '@posthog/ui/toast',
            handle: (args) => {
                // eslint-disable-next-line no-console
                console.info('[dock toast]', args)
                return { shown: true }
            },
        }),
        []
    )

    // Cast to the loose array type so the strict per-handler generics
    // (FocusArgs / ToastArgs) survive the contravariant flattening
    // useFakeRunner / AgentChat do via `ClientToolHandler[]`.
    const handlers = useMemo<ClientToolHandler[]>(
        () => [focusHandler, toastHandler] as unknown as ClientToolHandler[],
        [focusHandler, toastHandler]
    )

    // Mode-aware script set + starting session.
    const initialSession = context.mode === 'playground' ? playgroundSession : waitingSession
    const scripts = context.mode === 'playground' ? playgroundScripts : conciergeScripts

    const handleToolMutate = useMemo(
        () =>
            (mutations: ResolvedMutation[]): void => {
                // Fire-and-forget — runner doesn't block on side effects.
                // Errors get logged inside `applyMutation`.
                for (const m of mutations) {
                    void applyMutation(m).catch((err) => {
                        // eslint-disable-next-line no-console
                        console.error('[dock] tool mutation failed', m.entityKey, err)
                    })
                }
            },
        []
    )

    const runner = useFakeRunner({
        initialSession,
        scripts,
        fallbackScript,
        handlers,
        onToolMutate: handleToolMutate,
    })

    return (
        <AgentChat
            context={context}
            session={runner.session}
            handlers={handlers}
            followingEnabled={focus.enabled}
            onFollowingChange={focus.setEnabled}
            onExitPlayground={() => {
                exitPlayground()
                runner.reset()
                focus.clear()
            }}
            onNewSession={() => {
                runner.reset()
                focus.clear()
            }}
            onSend={runner.send}
        />
    )
}
