import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import type { ToolStreamEvent } from '../types/streamTypes'
import type { persistCreateToastLogicType } from './persistCreateToastLogicType'
import { toolStreamEventsLogic } from './toolStreamEventsLogic'

/** Per-tool copy + URL builder for a foreground create that just persisted an entity. */
interface CreateToastConfig {
    /** Sentence-case entity noun, used mid-sentence ('dashboard', 'feature flag'). */
    entity: string
    /** Approve-card action label, e.g. 'Open dashboard'. */
    openLabel: string
    /** In-app URL for the created entity, via `scenes/urls` builders. */
    url: (id: string | number) => string
}

// Only the create-family persist tools that produce a directly-openable entity. `cdp-functions-create`
// and `workflows-create-email-template` are intentionally excluded here — CDP create gets an agent-side
// chat follow-up in a later PR, and the email-template create has no single entity landing page.
const CREATE_TOAST_CONFIG: Record<string, CreateToastConfig> = {
    'dashboard-create': { entity: 'dashboard', openLabel: 'Open dashboard', url: (id) => urls.dashboard(id) },
    'create-feature-flag': {
        entity: 'feature flag',
        openLabel: 'Open feature flag',
        url: (id) => urls.featureFlag(id),
    },
    'survey-create': { entity: 'survey', openLabel: 'Open survey', url: (id) => urls.survey(String(id)) },
}

const PERSIST_CREATE_TOAST_TOOLS = Object.keys(CREATE_TOAST_CONFIG)

// Stable id: the logic is global + unkeyed, so mounting it from both sidebar surfaces registers a single
// listener that fires once per completion regardless of how many hosts mounted the logic.
const LISTENER_ID = 'persist-create-toasts'

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

/**
 * Best-effort id + name from a create tool's output. Sandbox create tools return the REST payload as
 * `invocation.output` (an object with `id`/`name`); some transports deliver it as a JSON string. Parses
 * defensively and returns null when no usable id can be read — the caller then toasts without a link.
 */
export function parseCreatedEntity(output: unknown): { id: string | number; name?: string } | null {
    let record = asRecord(output)
    if (!record && typeof output === 'string') {
        try {
            record = asRecord(JSON.parse(output))
        } catch {
            record = null
        }
    }
    if (!record) {
        return null
    }
    const id = record.id ?? record.dashboard_id ?? record.flag_id ?? record.survey_id
    if (id == null || (typeof id !== 'string' && typeof id !== 'number')) {
        return null
    }
    return { id, name: typeof record.name === 'string' ? record.name : undefined }
}

/**
 * Foreground toast reactions for create-family persist tools. When the run rendered in the side panel
 * finishes a `dashboard-create` / `create-feature-flag` / `survey-create` call (post-approval), pop a
 * success toast with an "Open" action linking to the created entity. Reuses the tool-event bus's
 * foreground gate + replay exclusion (`foregroundOnly` / `includeReplay: false`) so background runs and
 * reloads never toast. Global + unkeyed: mount it from every foreground surface (both register via
 * `useForegroundStream`); kea reference-counts to a single instance, so the listener is registered once.
 */
export const persistCreateToastLogic = kea<persistCreateToastLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'persistCreateToastLogic']),

    connect(() => ({
        actions: [toolStreamEventsLogic, ['registerToolListener', 'deregisterToolListener']],
    })),

    actions({
        notifyCreated: (event: ToolStreamEvent) => ({ event }),
    }),

    listeners(() => ({
        notifyCreated: ({ event }) => {
            const config = CREATE_TOAST_CONFIG[event.toolName]
            if (!config) {
                return
            }
            const parsed = parseCreatedEntity(event.invocation.output)
            const message = parsed?.name
                ? `Created ${config.entity} "${parsed.name}"`
                : `${capitalize(config.entity)} created`
            const to = parsed ? config.url(parsed.id) : null
            lemonToast.success(
                message,
                to ? { button: { label: config.openLabel, action: () => router.actions.push(to) } } : {}
            )
        },
    })),

    afterMount(({ actions, cache }) => {
        // pauseOnPageHidden: false — a foreground run keeps streaming while the tab is hidden, and a
        // paused subscription would silently drop the toast for anything that completed meanwhile.
        cache.disposables.add(
            () => {
                actions.registerToolListener(LISTENER_ID, {
                    tools: PERSIST_CREATE_TOAST_TOOLS,
                    foregroundOnly: true,
                    includeReplay: false,
                    onEvent: (event: ToolStreamEvent) => {
                        // Exec-wrapped tools resolve their inner name late — match only at completion.
                        if (event.phase === 'completed') {
                            actions.notifyCreated(event)
                        }
                    },
                })
                return () => actions.deregisterToolListener(LISTENER_ID)
            },
            LISTENER_ID,
            { pauseOnPageHidden: false }
        )
    }),
])
