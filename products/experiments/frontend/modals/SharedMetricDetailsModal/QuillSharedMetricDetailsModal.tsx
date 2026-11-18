import {
    Badge,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Separator,
    Text,
} from '@posthog/quill'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { MetricConversionWindow } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricConversionWindow'
import { MetricEventDetails } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricEventDetails'
import { MetricGoal } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricGoal'
import { MetricOutlierHandling } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricOutlierHandling'
import { MetricStepOrder } from 'scenes/experiments/ExperimentForm/MetricsPanel/MetricStepOrder'
import { getDefaultMetricTitle, getMetricTag } from 'scenes/experiments/MetricsView/shared/utils'
import { urls } from 'scenes/urls'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

export function QuillSharedMetricDetailsModal({
    sharedMetric,
    isOpen,
    close,
    remove,
}: {
    sharedMetric: ExperimentMetric
    isOpen: boolean
    close: () => void
    remove: () => void
}): JSX.Element {
    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent size="wide" className="max-w-2xl" data-attr="experiment-shared-metric-details-modal">
                <DialogHeader>
                    <DialogTitle>Shared metric</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-3">
                        <div className="flex flex-col gap-1">
                            <span className="flex items-center gap-1">
                                <Text size="sm" weight="semibold" render={<span className="break-words" />}>
                                    {sharedMetric.name || getDefaultMetricTitle(sharedMetric)}
                                </Text>
                                {sharedMetric.sharedMetricId && (
                                    <Button
                                        size="icon-xs"
                                        aria-label="Open shared metric"
                                        tooltip="Open shared metric"
                                        nativeButton={false}
                                        render={
                                            <LinkPrimitive
                                                to={urls.experimentsSharedMetric(sharedMetric.sharedMetricId)}
                                                target="_blank"
                                            />
                                        }
                                    >
                                        <IconOpenInNew />
                                    </Button>
                                )}
                            </span>
                            <MetricEventDetails metric={sharedMetric} />
                            <span className="mt-1 flex items-center gap-1">
                                <Badge>{getMetricTag(sharedMetric)}</Badge>
                                <Badge>Shared metric</Badge>
                            </span>
                        </div>
                        <Separator />
                        <div className="flex flex-col gap-1 text-xs">
                            <MetricGoal metric={sharedMetric} />
                            <MetricConversionWindow metric={sharedMetric} />
                            <MetricStepOrder metric={sharedMetric} />
                            <MetricOutlierHandling metric={sharedMetric} />
                        </div>
                    </div>
                </DialogBody>
                <DialogFooter className="sm:justify-between">
                    <Button variant="destructive-outline" onClick={remove}>
                        Remove from experiment
                    </Button>
                    <Button variant="outline" onClick={close}>
                        Close
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
