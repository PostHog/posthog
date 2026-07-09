import { actions, afterMount, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { objectsEqual } from 'lib/utils/objects'

import { BlastRadiusApi } from 'products/workflows/frontend/generated/api.schemas'

import { HogFlowAction } from '../types'
import type { batchTriggerLogicType } from './batchTriggerLogicType'

// Matches the default email template's `to.email` value: `{{ person.properties.email }}`, whitespace-tolerant.
// Anything else (custom property, computed Liquid, static address) makes the dedupe key diverge from the
// actual send target, so dedupe is skipped rather than applied wrongly.
const DEFAULT_EMAIL_TO_TEMPLATE_RE = /^\s*\{\{\s*person\.properties\.email\s*\}\}\s*$/

export function getAudienceDedupeKey(workflow?: { actions?: HogFlowAction[] } | null): 'email' | undefined {
    // Mirrors the backend (`canDedupeByEmail` in `nodejs/src/cdp/cdp-api.ts`): batch sends dedupe by
    // email only when every email action sends to the default `{{ person.properties.email }}` recipient.
    const emailActions = workflow?.actions?.filter((action) => action.type === 'function_email') ?? []
    if (emailActions.length === 0) {
        return undefined
    }
    const allDefault = emailActions.every((action) => {
        const toEmail = (action as any)?.config?.inputs?.email?.value?.to?.email
        return typeof toEmail === 'string' && DEFAULT_EMAIL_TO_TEMPLATE_RE.test(toEmail)
    })
    return allDefault ? 'email' : undefined
}

export interface BatchTriggerLogicProps {
    id?: string | 'new'
    filters?: Extract<HogFlowAction['config'], { type: 'batch' }>['filters']
    /** When 'email', the count reflects unique email addresses, matching batch send dedup. */
    dedupeKey?: 'email'
}

export const batchTriggerLogic = kea<batchTriggerLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'batchTriggerLogic']),
    props({} as BatchTriggerLogicProps),
    key(({ id }) => `batch-trigger-logic-${id || 'new'}`),
    actions({
        loadBlastRadius: true,
        setBlastRadiusError: (error: string | null) => ({ error }),
    }),
    reducers(() => ({
        filters: {
            setFilters: (_, { filters }) => filters,
        },
        blastRadiusError: [
            null as string | null,
            {
                loadBlastRadius: () => null,
                setBlastRadiusError: (_, { error }) => error,
            },
        ],
    })),
    loaders(({ props }) => ({
        blastRadius: [
            null as BlastRadiusApi | null,
            {
                loadBlastRadius: async () => {
                    if (!props.filters) {
                        return null
                    }
                    return await api.hogFlows.getBatchTriggerBlastRadius(props.filters, props.dedupeKey)
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadBlastRadiusFailure: ({ errorObject }) => {
            const apiError = errorObject as ApiError | undefined
            const message =
                apiError?.detail ||
                (errorObject as Error | undefined)?.message ||
                "Couldn't validate audience size. Your filters may not be supported."
            actions.setBlastRadiusError(message)
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps || !objectsEqual(props.filters, oldProps.filters) || props.dedupeKey !== oldProps.dedupeKey) {
            actions.loadBlastRadius()
        }
    }),
    afterMount(({ actions }) => {
        actions.loadBlastRadius()
    }),
])
