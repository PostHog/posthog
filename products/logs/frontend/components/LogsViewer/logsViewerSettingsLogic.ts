import { actions, connect, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import type { logsViewerSettingsLogicType } from './logsViewerSettingsLogicType'

// Seed the persisted timezone from the project timezone so logs match the rest of PostHog out of the box.
// Read imperatively because reducer defaults don't receive `values`; falls back to UTC when unavailable.
function projectTimezoneImperative(): string {
    return teamLogic.findMounted()?.values.currentTeam?.timezone || 'UTC'
}

// Shared logic for user preferences which should be used across all tabs+windows
export const logsViewerSettingsLogic = kea<logsViewerSettingsLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'logsViewerSettingsLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),

    actions({
        // Timezone (IANA string, e.g. "UTC", "America/New_York")
        setTimezone: (timezone: string) => ({ timezone }),

        // Display options
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
        setPrettifyJson: (prettifyJson: boolean) => ({ prettifyJson }),
    }),

    reducers(({}) => ({
        // Timezone selection (IANA string, persisted). Defaults to the project timezone; the picker overrides it.
        timezone: [
            projectTimezoneImperative(),
            { persist: true },
            {
                setTimezone: (_, { timezone }) => timezone,
            },
        ],

        wrapBody: [
            true,
            { persist: true },
            {
                setWrapBody: (_, { wrapBody }) => wrapBody,
            },
        ],

        // Not persisted: no toolbar control anymore; avoid stale localStorage. Default off — use row FAB / p to prettify per row.
        prettifyJson: [
            false,
            {
                setPrettifyJson: (_, { prettifyJson }) => prettifyJson,
            },
        ],
    })),

    listeners(() => ({
        setTimezone: ({ timezone }) => {
            posthog.capture('logs setting changed', { setting: 'timezone', value: timezone })
        },
        setWrapBody: ({ wrapBody }) => {
            posthog.capture('logs setting changed', { setting: 'wrap_body', value: wrapBody })
        },
    })),
])
