import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { clusteringJobsLogicType } from './clusteringJobsLogicType'
import type { ClusteringJob } from './types'

export const clusteringJobsLogic = kea<clusteringJobsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clusteringJobsLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamIdStrict']] })),

    actions({
        openJobsPanel: true,
        closeJobsPanel: true,
        setEditingJob: (job: Partial<ClusteringJob> | null) => ({ job }),
        deleteJob: (jobId: number) => ({ jobId }),
    }),

    loaders(({ values }) => ({
        jobs: [
            [] as ClusteringJob[],
            {
                loadJobs: async () => {
                    const response = await api.get(
                        `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_jobs/`
                    )
                    return (response.results ?? response) as ClusteringJob[]
                },
                createJob: async (payload: Partial<ClusteringJob>) => {
                    await api.create(
                        `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_jobs/`,
                        payload
                    )
                    lemonToast.success('Clustering job created')
                    // Reload to get server-assigned fields
                    const response = await api.get(
                        `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_jobs/`
                    )
                    return (response.results ?? response) as ClusteringJob[]
                },
                updateJob: async (payload: Partial<ClusteringJob> & { id: number }) => {
                    const { id, ...data } = payload
                    await api.update(
                        `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_jobs/${id}/`,
                        data
                    )
                    lemonToast.success('Clustering job updated')
                    const response = await api.get(
                        `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_jobs/`
                    )
                    return (response.results ?? response) as ClusteringJob[]
                },
            },
        ],
    })),

    reducers({
        isJobsPanelOpen: [
            false,
            {
                openJobsPanel: () => true,
                closeJobsPanel: () => false,
            },
        ],
        editingJob: [
            null as Partial<ClusteringJob> | null,
            {
                setEditingJob: (_, { job }) => job,
                closeJobsPanel: () => null,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openJobsPanel: () => {
            posthog.capture('llma clustering jobs panel opened')
        },
        deleteJob: async ({ jobId }) => {
            try {
                await api.delete(
                    `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_jobs/${jobId}/`
                )
                lemonToast.success('Clustering job deleted')
                posthog.capture('llma clustering job deleted', { job_id: jobId })
                actions.loadJobs()
            } catch {
                lemonToast.error('Failed to delete clustering job')
            }
        },
        createJobSuccess: ({ jobs }) => {
            posthog.capture('llma clustering job created', { total_jobs_count: jobs.length })
            actions.setEditingJob(null)
        },
        updateJobSuccess: () => {
            posthog.capture('llma clustering job updated')
            actions.setEditingJob(null)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadJobs()
    }),
])
