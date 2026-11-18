import { Badge, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { QuillSectionHeading } from 'scenes/experiments/ExperimentView/QuillCardParts'

import type { SetupContextSectionStatusEnumApi } from 'products/experiments/frontend/generated/api.schemas'

import { SECTION_STATUS_LABELS } from './setupInspectorUtils'

const STATUS_TAG_TYPES: Record<Exclude<SetupContextSectionStatusEnumApi, 'ok'>, LemonTagType> = {
    skipped: 'muted',
    timed_out: 'warning',
    error: 'danger',
}

const STATUS_BADGE_VARIANTS: Record<
    Exclude<SetupContextSectionStatusEnumApi, 'ok'>,
    'default' | 'warning' | 'destructive'
> = {
    skipped: 'default',
    timed_out: 'warning',
    error: 'destructive',
}

const STATUS_MESSAGES: Record<Exclude<SetupContextSectionStatusEnumApi, 'ok'>, string> = {
    skipped: 'This section needs an input that was not passed.',
    timed_out: 'The query took too long and was stopped. Narrow the inputs, or try again later.',
    error: 'The read failed. The server logs have the details.',
}

export interface SetupContextSectionProps {
    title: string
    description: string
    status: SetupContextSectionStatusEnumApi
    /** Replaces the generic message when the section is skipped, to name the missing input. */
    skippedMessage?: string
    children?: React.ReactNode
}

export function SetupContextSection({
    title,
    description,
    status,
    skippedMessage,
    children,
}: SetupContextSectionProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    if (todayRailNav && resultsRedesign) {
        return (
            <section className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <QuillSectionHeading>{title}</QuillSectionHeading>
                    {status !== 'ok' && (
                        <Badge variant={STATUS_BADGE_VARIANTS[status]}>{SECTION_STATUS_LABELS[status]}</Badge>
                    )}
                </div>
                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                    {description}
                </Text>
                {status === 'ok' ? (
                    children
                ) : (
                    <Text size="sm" render={<p className="m-0" />}>
                        {status === 'skipped' && skippedMessage ? skippedMessage : STATUS_MESSAGES[status]}
                    </Text>
                )}
            </section>
        )
    }
    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <h3 className="mb-0">{title}</h3>
                {status !== 'ok' && (
                    <LemonTag type={STATUS_TAG_TYPES[status]}>{SECTION_STATUS_LABELS[status]}</LemonTag>
                )}
            </div>
            <p className="text-secondary text-sm mb-0">{description}</p>
            {status === 'ok' ? (
                children
            ) : (
                <p className="text-sm mb-0">
                    {status === 'skipped' && skippedMessage ? skippedMessage : STATUS_MESSAGES[status]}
                </p>
            )}
        </section>
    )
}
