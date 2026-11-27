import {
    Button,
    Checkbox,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Heading,
    Text,
} from '@posthog/quill'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { MetricSourceBadge } from '../components/MetricSourceBadge'
import { MAX_OVERVIEW_METRICS, OVERVIEW_METRIC_SOURCES, overviewMetricSource } from './overviewMetricConfiguration'

export function QuillOverviewMetricConfigModal({
    isOpen,
    onClose,
    items,
    draft,
    full,
    onReset,
    onApply,
    onMove,
    onToggle,
}: {
    isOpen: boolean
    onClose: () => void
    items: OverviewMetricCardItem[]
    draft: string[]
    full: boolean
    onReset: () => void
    onApply: () => void
    onMove: (key: string, direction: -1 | 1) => void
    onToggle: (key: string) => void
}): JSX.Element {
    return (
        <Credenza open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <CredenzaContent className="md:max-w-150">
                <CredenzaHeader>
                    <CredenzaTitle>Edit top-line metrics</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody>
                    <div className="flex flex-col gap-6">
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Choose up to {MAX_OVERVIEW_METRICS} metrics to show above the chart. Table columns stay
                            unchanged.
                        </Text>
                        <section aria-label="Shown metrics" className="flex flex-col gap-2">
                            <Heading size="sm" render={<h4 className="m-0" />}>
                                {`Shown (${draft.length} of ${MAX_OVERVIEW_METRICS})`}
                            </Heading>
                            {draft.length === 0 ? (
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    No metrics chosen. Pick at least one below.
                                </Text>
                            ) : (
                                <div className="flex flex-col divide-y divide-border">
                                    {draft.map((key, index) => (
                                        <div key={key} className="flex items-center gap-2 py-1">
                                            <MetricSourceBadge source={overviewMetricSource(key)} />
                                            <Text
                                                size="xs"
                                                render={<span className="m-0 min-w-0 flex-1 break-words" />}
                                            >
                                                {key}
                                            </Text>
                                            {([-1, 1] as const).map((direction) => (
                                                <Button
                                                    key={direction}
                                                    size="icon"
                                                    aria-label={`Move ${key} ${direction === -1 ? 'up' : 'down'}`}
                                                    tooltip={direction === -1 ? 'Move up' : 'Move down'}
                                                    disabledReason={
                                                        (direction === -1 ? index === 0 : index === draft.length - 1)
                                                            ? 'Already at the end'
                                                            : undefined
                                                    }
                                                    onClick={() => onMove(key, direction)}
                                                >
                                                    {direction === -1 ? <IconArrowUp /> : <IconArrowDown />}
                                                </Button>
                                            ))}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </section>
                        {OVERVIEW_METRIC_SOURCES.map(({ key: source, label }) => {
                            const metrics = items.filter((item) => overviewMetricSource(item.key) === source)
                            return (
                                <section key={source} aria-label={label} className="flex flex-col gap-2">
                                    <Heading size="sm" render={<h4 className="m-0 flex items-center gap-2" />}>
                                        <MetricSourceBadge source={source} />
                                        {label}
                                    </Heading>
                                    {metrics.length === 0 ? (
                                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                            No metrics available from this source.
                                        </Text>
                                    ) : (
                                        <div className="flex flex-col divide-y divide-border">
                                            {metrics.map((item) => {
                                                const checked = draft.includes(item.key)
                                                return (
                                                    <div key={item.key} className="py-2">
                                                        <Checkbox
                                                            checked={checked}
                                                            onCheckedChange={() => onToggle(item.key)}
                                                            disabledReason={
                                                                !checked && full
                                                                    ? `You can show up to ${MAX_OVERVIEW_METRICS} metrics. Remove one to add another.`
                                                                    : undefined
                                                            }
                                                        >
                                                            <span className="break-words">{item.key}</span>
                                                        </Checkbox>
                                                    </div>
                                                )
                                            })}
                                        </div>
                                    )}
                                </section>
                            )
                        })}
                    </div>
                </CredenzaBody>
                <CredenzaFooter className="sm:justify-between">
                    <Button variant="outline" onClick={onReset} data-attr="marketing-metrics-reset">
                        Reset to defaults
                    </Button>
                    <div className="flex flex-col-reverse gap-2 sm:flex-row">
                        {/* Default focus is the first metric's source badge, which opens its tooltip and scrolls the body. */}
                        <Button variant="outline" onClick={onClose} autoFocus>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={onApply}
                            disabledReason={draft.length === 0 ? 'Choose at least one metric' : undefined}
                            data-attr="marketing-metrics-apply"
                        >
                            Apply
                        </Button>
                    </div>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
