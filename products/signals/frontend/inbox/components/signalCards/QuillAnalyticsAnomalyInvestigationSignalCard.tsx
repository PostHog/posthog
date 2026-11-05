import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { isAnalyticsAnomalyInvestigationExtra } from './signalCardMatchers'
import { anomalyInsightLabel } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** Quill sibling of `AnalyticsAnomalyInvestigationSignalCard`: an anomaly alert firing on an insight. */
export function QuillAnalyticsAnomalyInvestigationSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!isAnalyticsAnomalyInvestigationExtra(signal.extra)) {
        return <QuillSignalCardShell signal={signal}>{null}</QuillSignalCardShell>
    }
    const extra = signal.extra
    const insightLabel = anomalyInsightLabel(extra)

    return (
        <QuillSignalCardShell signal={signal} label={extra.alert_name}>
            <div className="flex flex-col gap-1">
                <Text size="xs" className="m-0">
                    Anomaly detected on{' '}
                    {extra.insight_short_id ? (
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.insightView(extra.insight_short_id as InsightShortId)} />}
                            className="font-medium"
                        >
                            {insightLabel}
                        </Button>
                    ) : (
                        <span className="font-medium">{insightLabel}</span>
                    )}
                </Text>
                {extra.detector_type && (
                    <Text size="xs" variant="muted" className="m-0">
                        Detector {extra.detector_type}
                    </Text>
                )}
            </div>

            {signal.content && <QuillSignalCardMarkdown>{signal.content}</QuillSignalCardMarkdown>}

            <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
                {extra.notebook_short_id && (
                    <QuillSignalCardLink to={urls.notebook(extra.notebook_short_id)}>
                        View investigation
                    </QuillSignalCardLink>
                )}
                <QuillSignalCardLink to={urls.alert(extra.alert_id)}>View alert</QuillSignalCardLink>
            </div>
        </QuillSignalCardShell>
    )
}
