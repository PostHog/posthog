import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@posthog/quill'

import { QuillResultDetails } from 'scenes/experiments/MetricsView/new/QuillResultDetails'

import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

export function QuillDetailsModal({
    isOpen,
    onClose,
    metric,
    result,
    experiment,
}: {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric
    result: NewExperimentQueryResponse
    experiment: Experiment
}): JSX.Element {
    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent size="wide" data-attr="experiment-metric-details-modal">
                <DialogHeader>
                    <DialogTitle>{`Metric results: ${metric.name || 'Untitled metric'}`}</DialogTitle>
                </DialogHeader>
                <DialogBody viewportClassName="px-0">
                    {isOpen && <QuillResultDetails result={result} experiment={experiment} metric={metric} />}
                </DialogBody>
                <DialogFooter showCloseButton />
            </DialogContent>
        </Dialog>
    )
}
