import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { apiHostOrigin } from 'lib/utils/apiHost'
import { getBackendHost } from 'lib/utils/oauthClient'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

import { TracingSetupPlatform, buildTracingSnippet, normalizeEnvironment } from './tracingOtlpSnippets'

const TOKEN_PLACEHOLDER = '<your project token>'

export interface tracingOtlpSetupLogicValues {
    currentTeam: TeamType | null // teamLogic
    platform: TracingSetupPlatform
    environment: string
    snippet: string
}

export interface tracingOtlpSetupLogicActions {
    setPlatform: (platform: TracingSetupPlatform) => { platform: TracingSetupPlatform }
    setEnvironment: (environment: string) => { environment: string }
    snippetCopied: () => { value: true }
}

export type tracingOtlpSetupLogicType = MakeLogicType<tracingOtlpSetupLogicValues, tracingOtlpSetupLogicActions>

export const tracingOtlpSetupLogic = kea<tracingOtlpSetupLogicType>([
    path(['products', 'tracing', 'frontend', 'emptyState', 'tracingOtlpSetupLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),

    actions({
        setPlatform: (platform: TracingSetupPlatform) => ({ platform }),
        setEnvironment: (environment: string) => ({ environment }),
        snippetCopied: true,
    }),

    reducers({
        platform: ['sdk' as TracingSetupPlatform, { setPlatform: (_, { platform }) => platform }],
        environment: ['', { setEnvironment: (_, { environment }) => normalizeEnvironment(environment) }],
    }),

    selectors({
        snippet: [
            (s) => [s.platform, s.environment, s.currentTeam],
            (platform, environment, currentTeam): string =>
                buildTracingSnippet(platform, {
                    token: currentTeam?.api_token || TOKEN_PLACEHOLDER,
                    host: apiHostOrigin(getBackendHost()?.replace(/\/+$/, '') || window.location.origin),
                    environment,
                }),
        ],
    }),

    listeners(({ values }) => ({
        snippetCopied: () => {
            // pinned: analytics event and property names - renaming breaks onboarding insights
            posthog.capture('tracing setup snippet copied', {
                platform: values.platform,
                has_environment: values.environment !== '',
            })
        },
    })),
])
