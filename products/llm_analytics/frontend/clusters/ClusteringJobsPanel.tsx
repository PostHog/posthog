import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { AnyPropertyFilter } from '~/types'

import { clusteringJobsLogic } from './clusteringJobsLogic'
import type { ClusteringJob, ClusteringLevel } from './types'

// Per-team cap. Must stay in sync with MAX_JOBS_PER_TEAM in
// products/llm_analytics/backend/api/clustering_job.py — the backend enforces
// the real limit and returns 400 past it; this only drives the "Add job" disable
// state. Raised to 10 to give teams headroom for per-evaluator clustering jobs
// once the third analysis level lands.
const MAX_JOBS = 10

function JobEditor({
    job,
    onSave,
    onCancel,
    saving,
}: {
    job: Partial<ClusteringJob>
    onSave: (data: Partial<ClusteringJob>) => void
    onCancel: () => void
    saving: boolean
}): JSX.Element {
    const [name, setName] = useState(job.name ?? '')
    const [analysisLevel, setAnalysisLevel] = useState<ClusteringLevel>(job.analysis_level ?? 'trace')
    const [eventFilters, setEventFilters] = useState<AnyPropertyFilter[]>(
        (job.event_filters as AnyPropertyFilter[] | undefined) ?? []
    )
    const [enabled, setEnabled] = useState(job.enabled ?? true)

    return (
        <div className="space-y-4">
            <div>
                <label className="font-semibold text-sm mb-1 block">Name</label>
                <LemonInput value={name} onChange={setName} placeholder="e.g. Production GPT-4o" fullWidth />
            </div>
            <div>
                <label className="font-semibold text-sm mb-1 block">Analysis level</label>
                <LemonSegmentedButton
                    value={analysisLevel}
                    onChange={(value) => setAnalysisLevel(value as ClusteringLevel)}
                    options={[
                        { value: 'trace', label: 'Traces' },
                        { value: 'generation', label: 'Generations' },
                    ]}
                    size="small"
                />
            </div>
            <div>
                <label className="font-semibold text-sm mb-1 block">Event filters</label>
                <div className="text-xs text-muted mb-2">
                    Only include items matching these criteria. Leave empty to include all.
                </div>
                <PropertyFilters
                    propertyFilters={eventFilters}
                    onChange={(properties) => setEventFilters(properties)}
                    pageKey={`llma-clustering-job-editor-${job.id ?? 'new'}`}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.EventMetadata,
                    ]}
                    addText="Add filter"
                    hasRowOperator={false}
                    sendAllKeyUpdates
                    allowRelativeDateOptions={false}
                />
            </div>
            <div className="flex items-center gap-2">
                <LemonSwitch checked={enabled} onChange={setEnabled} />
                <span className="text-sm">Enabled</span>
            </div>
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" data-attr="llma-clustering-job-cancel" onClick={onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    data-attr="llma-clustering-job-save"
                    disabled={!name.trim()}
                    loading={saving}
                    onClick={() =>
                        onSave({
                            ...(job.id ? { id: job.id } : {}),
                            name: name.trim(),
                            analysis_level: analysisLevel,
                            event_filters: eventFilters as Record<string, unknown>[],
                            enabled,
                        })
                    }
                >
                    {job.id ? 'Save' : 'Create'}
                </LemonButton>
            </div>
        </div>
    )
}

export function ClusteringJobsPanel(): JSX.Element {
    const { isJobsPanelOpen, jobs, jobsLoading, editingJob } = useValues(clusteringJobsLogic)
    const { closeJobsPanel, setEditingJob, createJob, updateJob, deleteJob } = useActions(clusteringJobsLogic)

    return (
        <LemonModal
            isOpen={isJobsPanelOpen}
            onClose={closeJobsPanel}
            title="Clustering jobs"
            description="Define independent clustering configurations for different subpopulations."
            width={600}
        >
            {editingJob ? (
                <JobEditor
                    job={editingJob}
                    saving={jobsLoading}
                    onCancel={() => setEditingJob(null)}
                    onSave={(data) => {
                        if (data.id) {
                            updateJob(data as Partial<ClusteringJob> & { id: number })
                        } else {
                            createJob(data)
                        }
                    }}
                />
            ) : (
                <div className="space-y-3">
                    {jobs.map((job: ClusteringJob) => (
                        <div
                            key={job.id}
                            className="flex items-center justify-between border rounded p-3 hover:bg-surface-secondary transition-colors"
                        >
                            <div className="flex items-center gap-2 min-w-0">
                                <span className="font-medium truncate">{job.name}</span>
                                <LemonBadge.Number count={job.event_filters.length} />
                                <LemonBadge
                                    content={job.analysis_level === 'generation' ? 'Gen' : 'Trace'}
                                    size="small"
                                />
                                {!job.enabled && <span className="text-xs text-muted">Disabled</span>}
                            </div>
                            <div className="flex items-center gap-1">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    data-attr="llma-clustering-job-edit"
                                    onClick={() => setEditingJob(job)}
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    status="danger"
                                    icon={<IconTrash />}
                                    data-attr="llma-clustering-job-delete"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete clustering job?',
                                            description: `Are you sure you want to delete "${job.name}"? This cannot be undone.`,
                                            primaryButton: {
                                                children: 'Delete',
                                                type: 'primary',
                                                status: 'danger',
                                                onClick: () => deleteJob(job.id),
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'secondary',
                                            },
                                        })
                                    }}
                                    tooltip="Delete job"
                                />
                            </div>
                        </div>
                    ))}

                    {jobs.length === 0 && !jobsLoading && (
                        <div className="text-center text-muted p-4">No clustering jobs configured yet.</div>
                    )}

                    <LemonBanner type="info">
                        Jobs run automatically during the next scheduled clustering and summarization cycle.
                    </LemonBanner>

                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        data-attr="llma-clustering-job-add"
                        onClick={() => setEditingJob({})}
                        disabled={jobs.length >= MAX_JOBS}
                        tooltip={jobs.length >= MAX_JOBS ? `Maximum of ${MAX_JOBS} jobs` : undefined}
                        fullWidth
                        center
                    >
                        Add job
                    </LemonButton>
                </div>
            )}
        </LemonModal>
    )
}
