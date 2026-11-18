import { useState } from 'react'

import { IconClock, IconEllipsis, IconWarning } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    IconStack,
    IconStackItem,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Separator,
    Spinner,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillHelpTooltip } from 'scenes/experiments/ExperimentView/QuillCardParts'
import { QuillVariantTag } from 'scenes/experiments/ExperimentView/QuillVariantTag'
import { ElapsedTime } from 'scenes/experiments/MetricsView/new/ElapsedTime'
import { VariantTimeseriesChart } from 'scenes/experiments/MetricsView/new/VariantTimeseriesChart'
import { getDefaultMetricTitle } from 'scenes/experiments/MetricsView/shared/utils'
import { urls } from 'scenes/urls'

import { ExperimentMetric, isExperimentRatioMetric } from '~/queries/schema/schema-general'

import { QuillConfirmDialog } from 'products/experiments/frontend/components/QuillConfirmDialog'

import {
    TIMESERIES_PROGRESS_HELP,
    TIMESERIES_RECALCULATE_TITLE,
    TIMESERIES_RECALCULATE_WARNING,
    TIMESERIES_STALE_NOTE,
    TimeseriesModalModel,
} from './useTimeseriesModal'

export function QuillTimeseriesModal({
    isOpen,
    onClose,
    metric,
    variantKey,
    model,
}: {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric
    variantKey: string
    model: TimeseriesModalModel
}): JSX.Element {
    const {
        chartData,
        progressMessage,
        hasTimeseriesData,
        timeseriesLoading,
        isRecalculating,
        recalculationCreatedAt,
        isStaleExperiment,
        recalculate,
        refresh,
    } = model
    const [confirmOpen, setConfirmOpen] = useState(false)

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent size="wide" className="max-w-4xl" data-attr="experiment-timeseries-modal">
                <DialogHeader>
                    <DialogTitle className="flex min-w-0 items-center gap-2">
                        <span className="shrink-0">Time series</span>
                        <Separator orientation="vertical" className="h-4" />
                        <span className="min-w-0 truncate">{metric.name || getDefaultMetricTitle(metric)}</span>
                        <Separator orientation="vertical" className="h-4" />
                        <QuillVariantTag variantKey={variantKey} />
                    </DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-3">
                        {timeseriesLoading ? (
                            <div className="flex h-50 items-center justify-center gap-2">
                                <Spinner />
                                <Text size="xs" render={<span />}>
                                    Loading timeseries&hellip;
                                </Text>
                            </div>
                        ) : (
                            <>
                                {isStaleExperiment && !isRecalculating && (
                                    <Item variant="outline" size="sm" tone="warning">
                                        <ItemMedia variant="icon" aria-hidden>
                                            <IconWarning />
                                        </ItemMedia>
                                        <ItemContent className="min-w-0">
                                            <ItemDescription className="line-clamp-none">
                                                {TIMESERIES_STALE_NOTE}
                                            </ItemDescription>
                                        </ItemContent>
                                        <ItemActions>
                                            <Button variant="outline" onClick={() => setConfirmOpen(true)}>
                                                Recalculate
                                            </Button>
                                        </ItemActions>
                                    </Item>
                                )}
                                {isRecalculating && (
                                    <Item variant="outline" size="sm" tone="info">
                                        <ItemMedia variant="icon" aria-hidden>
                                            <Spinner />
                                        </ItemMedia>
                                        <ItemContent className="min-w-0">
                                            <ItemDescription className="line-clamp-none">
                                                Recalculating • <ElapsedTime startTime={recalculationCreatedAt} />{' '}
                                                elapsed •{' '}
                                                <Button variant="link" size="inline" onClick={refresh}>
                                                    Refresh
                                                </Button>
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                )}
                                <div className="flex items-center justify-between">
                                    <span className="flex items-center gap-1">
                                        <Text size="xs" variant="muted" render={<span />}>
                                            {progressMessage || ''}
                                        </Text>
                                        {progressMessage && (
                                            <QuillHelpTooltip label="the time series" help={TIMESERIES_PROGRESS_HELP} />
                                        )}
                                    </span>
                                    <DropdownMenu>
                                        <DropdownMenuTrigger
                                            render={
                                                <Button
                                                    size="icon-sm"
                                                    aria-label="More actions"
                                                    tooltip="More actions"
                                                />
                                            }
                                        >
                                            <IconEllipsis />
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="end">
                                            <DropdownMenuItem onClick={() => setConfirmOpen(true)}>
                                                Recalculate
                                            </DropdownMenuItem>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </div>
                                {hasTimeseriesData && chartData ? (
                                    <VariantTimeseriesChart
                                        chartData={chartData}
                                        isRatioMetric={isExperimentRatioMetric(metric)}
                                    />
                                ) : (
                                    <Empty className="border-none">
                                        <EmptyHeader>
                                            <IconStack>
                                                <IconStackItem color="var(--color-product-experiments-light)">
                                                    <IconClock />
                                                </IconStackItem>
                                            </IconStack>
                                            <EmptyDescription>
                                                Timeseries data is calculated once per day. Check your calculation time
                                                in{' '}
                                                <Button
                                                    variant="link"
                                                    size="inline"
                                                    nativeButton={false}
                                                    render={
                                                        <LinkPrimitive
                                                            to={`${urls.experiments()}?tab=settings`}
                                                            target="_blank"
                                                        />
                                                    }
                                                >
                                                    settings
                                                </Button>
                                                .
                                            </EmptyDescription>
                                        </EmptyHeader>
                                    </Empty>
                                )}
                            </>
                        )}
                    </div>
                </DialogBody>
                <DialogFooter showCloseButton />
            </DialogContent>
            <QuillConfirmDialog
                open={confirmOpen}
                onOpenChange={setConfirmOpen}
                title={TIMESERIES_RECALCULATE_TITLE}
                description={TIMESERIES_RECALCULATE_WARNING}
                confirmLabel="Recalculate"
                onConfirm={recalculate}
                dataAttr="experiment-timeseries-recalculate-confirm"
            />
        </Dialog>
    )
}
