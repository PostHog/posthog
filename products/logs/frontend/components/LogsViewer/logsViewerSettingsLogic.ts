import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { logsViewerSettingsLogicType } from './logsViewerSettingsLogicType'

// Shared logic for user preferences which should be used across all tabs+windows
export const logsViewerSettingsLogic = kea<logsViewerSettingsLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'logsViewerSettingsLogic']),

    actions({
        // Timezone (IANA string, e.g. "UTC", "America/New_York")
        setTimezone: (timezone: string) => ({ timezone }),

        // Display options
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
        setPrettifyJson: (prettifyJson: boolean) => ({ prettifyJson }),
    }),

    reducers(({}) => ({
        // Timezone selection (IANA string, persisted)
        timezone: [
            'UTC',
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

        prettifyJson: [
            true,
            { persist: true },
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
        setPrettifyJson: ({ prettifyJson }) => {
            posthog.capture('logs setting changed', { setting: 'prettify_json', value: prettifyJson })
        },
    })),
])
