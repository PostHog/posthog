import { useState } from 'react'

import { IconChevronDown, IconClock, IconTrends } from '@posthog/icons'
import { Badge, Button, Item, ItemActions, ItemContent, ItemMedia, ItemTitle, Text, cn } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringPeriodLabel } from '../reportCheckPresentation'

type BadgeVariant = 'default' | 'info' | 'success' | 'warning' | 'destructive'

const CHECK_STATUS: Record<SignalReportCheckApi['status'], { label: string; variant: BadgeVariant }> = {
    pending: { label: 'Waiting', variant: 'default' },
    active: { label: 'Scheduled', variant: 'info' },
    passed: { label: 'Passed', variant: 'success' },
    failed: { label: 'Failed', variant: 'destructive' },
    errored: { label: 'Errored', variant: 'destructive' },
    inconclusive: { label: 'Inconclusive', variant: 'warning' },
    expired: { label: 'Expired', variant: 'default' },
    cancelled: { label: 'Canceled', variant: 'default' },
}

export function ReportCheckItem({ check }: { check: SignalReportCheckApi }): JSX.Element {
    const [rationaleOpen, setRationaleOpen] = useState(false)
    const status = CHECK_STATUS[check.status]
    const endsAt = check.monitoring_timing?.ends_at ?? null
    const rationaleId = `inbox-report-check-rationale-${check.id}`

    return (
        <Item variant="outline" size="sm" className="items-start" data-attr="inbox-report-check">
            <ItemMedia variant="icon">{check.kind === 'agent' ? <IconClock /> : <IconTrends />}</ItemMedia>
            <ItemContent className="min-w-0 gap-1">
                <ItemTitle>{check.title}</ItemTitle>
                <Text
                    size="xs"
                    variant="muted"
                    render={<div />}
                    className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5"
                >
                    <span>{check.kind === 'agent' ? 'An agent reads the evidence' : 'Compares a metric'}</span>
                    {check.soak_minutes != null && (
                        <>
                            <span aria-hidden>·</span>
                            <span>{`Observes for ${monitoringPeriodLabel(check.soak_minutes)}`}</span>
                        </>
                    )}
                    {endsAt && (
                        <>
                            <span aria-hidden>·</span>
                            <span>Runs</span>
                            <TZLabel time={endsAt} />
                        </>
                    )}
                </Text>
                {check.rationale && (
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-ms-2 self-start"
                        aria-expanded={rationaleOpen}
                        aria-controls={rationaleId}
                        onClick={() => setRationaleOpen(!rationaleOpen)}
                        data-attr="inbox-report-check-rationale"
                    >
                        Why this check
                        <IconChevronDown
                            className={cn('transition-transform duration-200', rationaleOpen && 'rotate-180')}
                        />
                    </Button>
                )}
                {rationaleOpen && (
                    <Text
                        id={rationaleId}
                        size="xs"
                        variant="muted"
                        render={<p className="m-0" />}
                        className="leading-relaxed"
                    >
                        {check.rationale}
                    </Text>
                )}
            </ItemContent>
            <ItemActions className="self-start">
                <Badge variant={status.variant}>{status.label}</Badge>
            </ItemActions>
        </Item>
    )
}
