import { ICONS } from 'lib/integrations/utils'

import { IntegrationKind, IntegrationType } from '~/types'

export const ERROR_TRACKING_INTEGRATIONS = [
    'linear',
    'github',
    'gitlab',
    'jira',
] as const satisfies readonly IntegrationKind[]

export type ErrorTrackingIntegrationKind = (typeof ERROR_TRACKING_INTEGRATIONS)[number]
export type ErrorTrackingIntegration = IntegrationType & { kind: ErrorTrackingIntegrationKind }

export const PROVIDER_LABELS: Record<ErrorTrackingIntegrationKind, string> = {
    github: 'GitHub',
    gitlab: 'GitLab',
    linear: 'Linear',
    jira: 'Jira',
}

export const IntegrationIcon = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    return <img src={ICONS[kind]} className="w-5 h-5 rounded-sm" />
}
