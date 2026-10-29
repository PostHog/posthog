import type { ComponentType } from 'react'

import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { DashboardIcon } from '@/ui/icons/DashboardIcon'
import { DatabaseIcon } from '@/ui/icons/DatabaseIcon'
import { DocumentIcon } from '@/ui/icons/DocumentIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { GitBranchIcon } from '@/ui/icons/GitBranchIcon'
import { LineChartIcon } from '@/ui/icons/LineChartIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import type { IconProps } from '@/ui/icons/types'
import { WarningIcon } from '@/ui/icons/WarningIcon'

import type { SourceProduct } from './types'

export interface SourceInfo {
    label: string
    Icon: ComponentType<IconProps>
}

const SOURCES: Record<SourceProduct, SourceInfo> = {
    error_tracking: { label: 'Error', Icon: ErrorTriangleIcon },
    github: { label: 'GitHub', Icon: GitBranchIcon },
    gitlab: { label: 'GitLab', Icon: GitBranchIcon },
    pganalyze: { label: 'pganalyze', Icon: DatabaseIcon },
    analytics: { label: 'Product analytics', Icon: LineChartIcon },
    session_replay: { label: 'Session replay', Icon: PlayIcon },
    replay_vision: { label: 'Session replay', Icon: PlayIcon },
    llm_analytics: { label: 'AI observability', Icon: LineChartIcon },
    logs: { label: 'Logs', Icon: DocumentIcon },
    health_checks: { label: 'Health check', Icon: WarningIcon },
    signals_scout: { label: 'Report', Icon: DocumentIcon },
    signals_check: { label: 'Report', Icon: DocumentIcon },
    endpoints: { label: 'Endpoints', Icon: WarningIcon },
    conversations: { label: 'Support', Icon: ChatBubbleIcon },
    zendesk: { label: 'Zendesk', Icon: ChatBubbleIcon },
    intercom: { label: 'Intercom', Icon: ChatBubbleIcon },
    linear: { label: 'Linear', Icon: DocumentIcon },
    jira: { label: 'Jira', Icon: DocumentIcon },
    sentry: { label: 'Sentry', Icon: ErrorTriangleIcon },
    engineering_analytics: { label: 'Engineering', Icon: GitBranchIcon },
    dashboard: { label: 'Dashboards', Icon: DashboardIcon },
    other: { label: 'Report', Icon: DocumentIcon },
}

export function sourceInfo(source: SourceProduct): SourceInfo {
    return SOURCES[source]
}

export function toSourceProduct(value: string | null | undefined): SourceProduct {
    if (value && Object.hasOwn(SOURCES, value)) {
        return value as SourceProduct
    }
    return 'other'
}

// Raw strings, because most of these source products map to `other` in the app.
const FEEDBACK_SOURCES: ReadonlySet<string> = new Set([
    'conversations',
    'zendesk',
    'intercom',
    'freshdesk',
    'freshservice',
    'front',
    'gorgias',
    'kustomer',
    'dixa',
    'plain',
    'featurebase',
    'frill',
    'aha',
    'uservoice',
    'productboard',
    'canny',
    'asknicely',
    'retently',
    'appfigures',
    'appfollow',
])

const ERROR_SOURCES: ReadonlySet<string> = new Set([
    'error_tracking',
    'sentry',
    'rollbar',
    'bugsnag',
    'honeybadger',
    'raygun',
])

/** Source products that say who wrote a report, not what it is about. */
const AUTHOR_SOURCES: ReadonlySet<string> = new Set(['signals_scout', 'signals_check'])

export function isFeedbackSource(value: string): boolean {
    return FEEDBACK_SOURCES.has(value)
}

export function isErrorSource(value: string): boolean {
    return ERROR_SOURCES.has(value)
}

export function primarySource(sources: readonly string[]): SourceProduct {
    const subject = sources.find((source) => !AUTHOR_SOURCES.has(source))
    return toSourceProduct(subject ?? sources[0])
}
