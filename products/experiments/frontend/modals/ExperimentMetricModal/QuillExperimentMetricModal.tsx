import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { ExperimentMetricForm } from 'scenes/experiments/ExperimentMetricForm'
import { resolveFilterTestAccounts, resolvedExposureEvent } from 'scenes/experiments/exposureContract'

import type { ExperimentExposureCriteria, ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { QuillConfirmDialog } from 'products/experiments/frontend/components/QuillConfirmDialog'

import type { MetricContext } from './experimentMetricModalLogic'
import { DELETE_METRIC_TITLE, DELETE_METRIC_WARNING, type ExperimentMetricModalModel } from './useExperimentMetricModal'

export function QuillExperimentMetricModal({
    model,
    experiment,
    exposureCriteria,
    onSave,
    onDelete,
}: {
    model: ExperimentMetricModalModel
    experiment: Experiment
    exposureCriteria: ExperimentExposureCriteria | undefined
    onSave: (metric: ExperimentMetric, context: MetricContext) => void
    onDelete: (metric: ExperimentMetric, context: MetricContext) => void
}): JSX.Element | null {
    const { isOpen, metric, context, isEditMode, title, saveLabel, close, setMetric, openExposureCriteriaModal } = model
    const { metricToSave, saveDisabledReason } = model
    const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)

    if (!metric || !metricToSave) {
        return null
    }

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent size="wide" className="max-w-3xl" data-attr="experiment-metric-modal">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Field>
                            <FieldLabel htmlFor="experiment-metric-name">Name (optional)</FieldLabel>
                            <Input
                                id="experiment-metric-name"
                                value={metric.name ?? ''}
                                onChange={(event) => setMetric({ ...metric, name: event.target.value })}
                            />
                        </Field>
                        <ExperimentMetricForm
                            metric={metric}
                            handleSetMetric={setMetric}
                            filterTestAccounts={resolveFilterTestAccounts(experiment.exposure_criteria)}
                            exposureCriteria={exposureCriteria}
                            openExposureCriteriaModal={openExposureCriteriaModal}
                            resolvedExposureEvent={resolvedExposureEvent(experiment)}
                        />
                    </div>
                </DialogBody>
                <DialogFooter className="sm:justify-between">
                    <span>
                        {isEditMode && (
                            <Button variant="destructive-outline" onClick={() => setConfirmDeleteOpen(true)}>
                                Delete
                            </Button>
                        )}
                    </span>
                    <span className="flex items-center gap-2">
                        <Button variant="outline" onClick={close}>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={() => onSave(metricToSave, context)}
                            disabledReason={saveDisabledReason ?? undefined}
                            data-attr="save-experiment-metric"
                        >
                            {saveLabel}
                        </Button>
                    </span>
                </DialogFooter>
            </DialogContent>
            <QuillConfirmDialog
                open={confirmDeleteOpen}
                onOpenChange={setConfirmDeleteOpen}
                title={DELETE_METRIC_TITLE}
                description={DELETE_METRIC_WARNING}
                confirmLabel="Delete"
                destructive
                onConfirm={() => onDelete(metric, context)}
            />
        </Dialog>
    )
}
