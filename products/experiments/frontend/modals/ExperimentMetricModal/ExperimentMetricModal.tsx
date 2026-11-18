import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ExperimentMetricForm } from 'scenes/experiments/ExperimentMetricForm'
import { resolveFilterTestAccounts, resolvedExposureEvent } from 'scenes/experiments/exposureContract'

import type { ExperimentExposureCriteria, ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { type MetricContext } from './experimentMetricModalLogic'
import { QuillExperimentMetricModal } from './QuillExperimentMetricModal'
import { DELETE_METRIC_TITLE, DELETE_METRIC_WARNING, useExperimentMetricModal } from './useExperimentMetricModal'

export function ExperimentMetricModal({
    experiment,
    exposureCriteria,
    onSave,
    onDelete,
}: {
    experiment: Experiment
    exposureCriteria: ExperimentExposureCriteria | undefined
    onSave: (metric: ExperimentMetric, context: MetricContext) => void
    onDelete: (metric: ExperimentMetric, context: MetricContext) => void
}): JSX.Element | null {
    const model = useExperimentMetricModal(exposureCriteria)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const {
        isOpen: isModalOpen,
        metric,
        context,
        isCreateMode,
        isEditMode,
        close: closeExperimentMetricModal,
        setMetric: setModalMetric,
        openExposureCriteriaModal,
        metricToSave,
        saveDisabledReason,
    } = model

    if (!isModalOpen || !metric || !metricToSave) {
        return null
    }

    if (todayRailNav && resultsRedesign) {
        return (
            <QuillExperimentMetricModal
                model={model}
                experiment={experiment}
                exposureCriteria={exposureCriteria}
                onSave={onSave}
                onDelete={onDelete}
            />
        )
    }

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeExperimentMetricModal}
            title={isCreateMode ? 'Create experiment metric' : 'Edit experiment metric'}
            footer={
                <div className="flex items-center w-full">
                    {isEditMode && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => {
                                LemonDialog.open({
                                    title: DELETE_METRIC_TITLE,
                                    content: <div className="text-sm text-muted">{DELETE_METRIC_WARNING}</div>,
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        onClick: () => onDelete(metric, context),
                                        size: 'small',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'tertiary',
                                        size: 'small',
                                    },
                                })
                            }}
                        >
                            Delete
                        </LemonButton>
                    )}
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton
                            form="edit-experiment-metric-form"
                            type="secondary"
                            onClick={closeExperimentMetricModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-metric-form"
                            onClick={() => onSave(metricToSave, context)}
                            disabledReason={saveDisabledReason}
                            type="primary"
                            data-attr="save-experiment-metric"
                        >
                            {isCreateMode ? 'Create' : 'Save'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="mb-4">
                <LemonLabel className="mb-1">Name (optional)</LemonLabel>
                <LemonInput
                    value={metric.name}
                    onChange={(newName) => {
                        setModalMetric({
                            ...metric,
                            name: newName,
                        })
                    }}
                />
            </div>
            <ExperimentMetricForm
                metric={metric}
                handleSetMetric={setModalMetric}
                filterTestAccounts={resolveFilterTestAccounts(experiment.exposure_criteria)}
                exposureCriteria={exposureCriteria}
                openExposureCriteriaModal={openExposureCriteriaModal}
                resolvedExposureEvent={resolvedExposureEvent(experiment)}
            />
        </LemonModal>
    )
}
