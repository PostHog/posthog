import { type ReactElement, type ReactNode } from 'react'

import { Button, Card, CardContent, Switch } from '@posthog/quill'

export interface WorkflowSendingRulesData {
    project_id: number
    marketing_frequency_cap_max_messages: number | null
    marketing_frequency_cap_window_days: number | null
    email_tracking_consent_mode: 'off' | 'opt_out' | 'opt_in'
    capture_workflows_engagement_events: boolean
}

export interface WorkflowSendingRulesViewProps {
    data: WorkflowSendingRulesData
    saving?: boolean
    error?: string | null
    onApplyRecommendedCap?: () => void
    onEngagementEventsChange?: (enabled: boolean) => void
}

const CONSENT_LABELS: Record<WorkflowSendingRulesData['email_tracking_consent_mode'], string> = {
    off: 'No consent enforcement',
    opt_out: 'Track unless the recipient objected',
    opt_in: 'Track only recipients who consented',
}

function plural(count: number, noun: string): string {
    return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function Rule({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: ReactNode
}): ReactElement {
    return (
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-1 flex-col">
                <span className="font-medium">{title}</span>
                <span className="text-sm text-muted-foreground">{description}</span>
            </div>
            {children}
        </div>
    )
}

export function WorkflowSendingRulesView({
    data,
    saving = false,
    error,
    onApplyRecommendedCap,
    onEngagementEventsChange,
}: WorkflowSendingRulesViewProps): ReactElement {
    const maxMessages = data.marketing_frequency_cap_max_messages
    const windowDays = data.marketing_frequency_cap_window_days
    const capDescription =
        maxMessages !== null && windowDays !== null
            ? `At most ${plural(maxMessages, 'marketing email')} every ${plural(windowDays, 'day')} per person.`
            : null

    return (
        <div className="p-4">
            <Card>
                <CardContent className="flex flex-col gap-4">
                    <div className="flex flex-col">
                        <span className="font-semibold">Sending rules</span>
                        <span className="text-sm text-muted-foreground">
                            Every workflow and broadcast in this project follows these rules.
                        </span>
                    </div>
                    <Rule
                        title="Frequency cap"
                        description={capDescription ?? 'No cap. The recommended cap is 1 marketing email every 2 days.'}
                    >
                        {capDescription === null && onApplyRecommendedCap ? (
                            <Button size="sm" variant="primary" disabled={saving} onClick={onApplyRecommendedCap}>
                                Apply recommended cap
                            </Button>
                        ) : null}
                    </Rule>
                    <Rule title="Email tracking consent" description={CONSENT_LABELS[data.email_tracking_consent_mode]}>
                        {null}
                    </Rule>
                    <Rule
                        title="Engagement events"
                        description="Sends, opens, clicks and bounces as PostHog events. They count toward event usage."
                    >
                        <Switch
                            checked={data.capture_workflows_engagement_events}
                            disabled={saving || !onEngagementEventsChange}
                            onCheckedChange={(checked) => onEngagementEventsChange?.(checked)}
                            aria-label="Capture email engagement events"
                        />
                    </Rule>
                    {error ? <p className="m-0 text-sm text-danger">{error}</p> : null}
                </CardContent>
            </Card>
        </div>
    )
}
