import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { projectLogic } from 'scenes/projectLogic'

import { wizardRunsPartialUpdate, wizardRunsRetrieve } from './generated/api'
import type { WizardRunApi, WizardRunArtifactApi, WizardRunGitDiffArtifactApi } from './generated/api.schemas'
import { loadWizardRunArtifactContent, loadWizardRunArtifacts } from './wizardApi'
import { wizardRunDiffCanRender, wizardRunIsActive } from './wizardRunDisplay'
import { wizardRunsLogic } from './wizardRunsLogic'

const RUN_DETAIL_POLL_INTERVAL_MS = 10_000

type WizardRunDiffContent = {
    artifactId: string
    content: string
}

function requestError(error: unknown, fallback: string): string {
    return error instanceof ApiError && error.detail ? error.detail : fallback
}

export interface wizardRunDetailsLogicValues {
    currentProjectId: number | null
    artifactRunIdsLoaded: string[]
    cancelRunRequest: WizardRunApi | null
    cancelRunRequestLoading: boolean
    runArtifacts: WizardRunArtifactApi[]
    runArtifactsError: string | null
    runArtifactsLoading: boolean
    runDetails: WizardRunApi | null
    runDetailsLoading: boolean
    runDiff: WizardRunDiffContent | null
    runDiffError: string | null
    runDiffLoading: boolean
    selectedRun: WizardRunApi | null
    selectedRunArtifacts: WizardRunArtifactApi[]
    selectedRunArtifactsInitialLoading: boolean
    selectedRunDiffArtifactId: string | null
    selectedRunDiffContent: string | null
    selectedRunId: string | null
    selectedRunSummary: WizardRunApi | null
}

export interface wizardRunDetailsLogicActions {
    cancelRun: (run: WizardRunApi) => { run: WizardRunApi }
    cancelRunRequest: ({ runId }: { runId: string }) => { runId: string }
    cancelRunRequestFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    cancelRunRequestSuccess: (
        cancelRunRequest: WizardRunApi | null,
        payload?: { runId: string }
    ) => {
        cancelRunRequest: WizardRunApi | null
        payload?: { runId: string }
    }
    closeRunDiff: () => { value: true }
    copyRunId: (runId: string) => { runId: string }
    loadRunArtifacts: ({ runId }: { runId: string }) => { runId: string }
    loadRunArtifactsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadRunArtifactsSuccess: (
        runArtifacts: WizardRunArtifactApi[],
        payload?: { runId: string }
    ) => {
        runArtifacts: WizardRunArtifactApi[]
        payload?: { runId: string }
    }
    loadRunDetails: ({ runId }: { runId: string }) => { runId: string }
    loadRunDetailsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadRunDetailsSuccess: (
        runDetails: WizardRunApi | null,
        payload?: { runId: string }
    ) => {
        runDetails: WizardRunApi | null
        payload?: { runId: string }
    }
    loadRunDiff: ({ artifactId, runId }: { artifactId: string; runId: string }) => {
        artifactId: string
        runId: string
    }
    loadRunDiffFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadRunDiffSuccess: (
        runDiff: WizardRunDiffContent | null,
        payload?: { artifactId: string; runId: string }
    ) => {
        runDiff: WizardRunDiffContent | null
        payload?: { artifactId: string; runId: string }
    }
    openRunDiff: (artifact: WizardRunGitDiffArtifactApi) => { artifact: WizardRunGitDiffArtifactApi }
    refreshRuns: () => { value: true }
    refreshSelectedRun: () => { value: true }
    selectRun: (run: WizardRunApi | null) => { run: WizardRunApi | null }
}

export interface wizardRunDetailsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        selectedRun: (runDetails: WizardRunApi | null, selectedRunSummary: WizardRunApi | null) => WizardRunApi | null
        selectedRunArtifacts: (
            selectedRunId: string | null,
            runArtifacts: WizardRunArtifactApi[]
        ) => WizardRunArtifactApi[]
        selectedRunArtifactsInitialLoading: (
            selectedRunId: string | null,
            runArtifactsLoading: boolean,
            artifactRunIdsLoaded: string[]
        ) => boolean
        selectedRunDiffContent: (
            selectedRunDiffArtifactId: string | null,
            runDiff: WizardRunDiffContent | null
        ) => string | null
        selectedRunId: (selectedRunSummary: WizardRunApi | null) => string | null
    }
}

export type wizardRunDetailsLogicType = MakeLogicType<
    wizardRunDetailsLogicValues,
    wizardRunDetailsLogicActions,
    Record<string, never>,
    wizardRunDetailsLogicMeta
>

export const wizardRunDetailsLogic = kea<wizardRunDetailsLogicType>([
    path(['products', 'wizard', 'wizardRunDetailsLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
        actions: [wizardRunsLogic, ['refreshRuns']],
    })),
    actions({
        selectRun: (run: WizardRunApi | null) => ({ run }),
        openRunDiff: (artifact: WizardRunGitDiffArtifactApi) => ({ artifact }),
        closeRunDiff: true,
        refreshSelectedRun: true,
        cancelRun: (run: WizardRunApi) => ({ run }),
        copyRunId: (runId: string) => ({ runId }),
    }),
    reducers({
        selectedRunSummary: [
            null as WizardRunApi | null,
            {
                selectRun: (_, { run }) => run,
                cancelRunRequestSuccess: (state, { cancelRunRequest }) =>
                    state?.id === cancelRunRequest?.id ? cancelRunRequest : state,
            },
        ],
        artifactRunIdsLoaded: [
            [] as string[],
            {
                loadRunArtifactsSuccess: (state, { payload }) => {
                    const runId = payload?.runId

                    return runId && !state.includes(runId) ? [...state, runId] : state
                },
            },
        ],
        runArtifactsError: [
            null as string | null,
            {
                loadRunArtifacts: () => null,
                loadRunArtifactsSuccess: () => null,
                loadRunArtifactsFailure: (_, { errorObject }) => requestError(errorObject, "Couldn't load artifacts."),
            },
        ],
        selectedRunDiffArtifactId: [
            null as string | null,
            {
                openRunDiff: (_, { artifact }) => artifact.id,
                closeRunDiff: () => null,
                selectRun: () => null,
            },
        ],
        runDiffError: [
            null as string | null,
            {
                openRunDiff: () => null,
                closeRunDiff: () => null,
                loadRunDiffSuccess: () => null,
                loadRunDiffFailure: (_, { errorObject }) =>
                    requestError(errorObject, "Couldn't load this diff. Try again."),
            },
        ],
    }),
    loaders(({ values }) => ({
        runDetails: [
            null as WizardRunApi | null,
            {
                loadRunDetails: async ({ runId }: { runId: string }, breakpoint) => {
                    if (!values.currentProjectId) {
                        return null
                    }

                    const run = await wizardRunsRetrieve(String(values.currentProjectId), runId)

                    await breakpoint()

                    return run
                },
            },
        ],
        runArtifacts: [
            [] as WizardRunArtifactApi[],
            {
                loadRunArtifacts: async ({ runId }: { runId: string }, breakpoint) => {
                    if (!values.currentProjectId) {
                        return []
                    }

                    const artifacts = await loadWizardRunArtifacts(String(values.currentProjectId), runId)

                    await breakpoint()

                    return [...values.runArtifacts.filter((artifact) => artifact.run_id !== runId), ...artifacts]
                },
            },
        ],
        runDiff: [
            null as WizardRunDiffContent | null,
            {
                loadRunDiff: async ({ artifactId, runId }: { artifactId: string; runId: string }, breakpoint) => {
                    if (!values.currentProjectId) {
                        return null
                    }

                    const content = await loadWizardRunArtifactContent(
                        String(values.currentProjectId),
                        runId,
                        artifactId
                    )

                    await breakpoint()

                    return { artifactId, content }
                },
            },
        ],
        cancelRunRequest: [
            null as WizardRunApi | null,
            {
                cancelRunRequest: async ({ runId }: { runId: string }) => {
                    if (!values.currentProjectId) {
                        return null
                    }

                    return wizardRunsPartialUpdate(String(values.currentProjectId), runId, { status: 'cancelled' })
                },
            },
        ],
    })),
    selectors({
        selectedRunId: [
            (s) => [s.selectedRunSummary],
            (selectedRunSummary: WizardRunApi | null): string | null => selectedRunSummary?.id ?? null,
        ],
        selectedRun: [
            (s) => [s.runDetails, s.selectedRunSummary],
            (runDetails: WizardRunApi | null, selectedRunSummary: WizardRunApi | null): WizardRunApi | null => {
                if (!runDetails || runDetails.id !== selectedRunSummary?.id) {
                    return selectedRunSummary
                }

                // Details cached from an earlier drawer session can be older than a fresh table
                // summary or a cancellation response, so defer to whichever changed more recently.
                const detailsTime = runDetails.updated_at ? dayjs(runDetails.updated_at).valueOf() : 0
                const summaryTime = selectedRunSummary.updated_at ? dayjs(selectedRunSummary.updated_at).valueOf() : 0

                return summaryTime > detailsTime ? selectedRunSummary : runDetails
            },
        ],
        selectedRunArtifacts: [
            (s) => [s.selectedRunId, s.runArtifacts],
            (selectedRunId: string | null, runArtifacts: WizardRunArtifactApi[]): WizardRunArtifactApi[] =>
                selectedRunId ? runArtifacts.filter((artifact) => artifact.run_id === selectedRunId) : [],
        ],
        selectedRunArtifactsInitialLoading: [
            (s) => [s.selectedRunId, s.runArtifactsLoading, s.artifactRunIdsLoaded],
            (selectedRunId: string | null, runArtifactsLoading: boolean, artifactRunIdsLoaded: string[]): boolean =>
                !!selectedRunId && runArtifactsLoading && !artifactRunIdsLoaded.includes(selectedRunId),
        ],
        selectedRunDiffContent: [
            (s) => [s.selectedRunDiffArtifactId, s.runDiff],
            (selectedRunDiffArtifactId: string | null, runDiff: WizardRunDiffContent | null): string | null =>
                selectedRunDiffArtifactId && runDiff?.artifactId === selectedRunDiffArtifactId ? runDiff.content : null,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        selectRun: ({ run }) => {
            cache.disposables.dispose('wizardRunDetailPolling')

            if (!run) {
                return
            }

            actions.loadRunDetails({ runId: run.id })
            actions.loadRunArtifacts({ runId: run.id })

            if (wizardRunIsActive(run)) {
                cache.disposables.add(() => {
                    const timerId = window.setInterval(() => {
                        actions.loadRunDetails({ runId: run.id })
                        actions.loadRunArtifacts({ runId: run.id })
                    }, RUN_DETAIL_POLL_INTERVAL_MS)

                    return () => window.clearInterval(timerId)
                }, 'wizardRunDetailPolling')
            }
        },
        openRunDiff: ({ artifact }) => {
            if (wizardRunDiffCanRender(artifact.size_bytes)) {
                actions.loadRunDiff({ runId: artifact.run_id, artifactId: artifact.id })
            }
        },
        refreshSelectedRun: () => {
            if (values.selectedRunId) {
                actions.loadRunDetails({ runId: values.selectedRunId })
                actions.loadRunArtifacts({ runId: values.selectedRunId })
            }
        },
        loadRunDetailsSuccess: ({ runDetails }) => {
            if (runDetails && !wizardRunIsActive(runDetails)) {
                cache.disposables.dispose('wizardRunDetailPolling')
            }
        },
        cancelRun: ({ run }) => {
            LemonDialog.open({
                title: 'Cancel Wizard run?',
                description: 'The agent stops this run. You cannot resume it.',
                primaryButton: {
                    children: 'Cancel run',
                    status: 'danger',
                    onClick: () => actions.cancelRunRequest({ runId: run.id }),
                },
                secondaryButton: { children: 'Keep running' },
            })
        },
        cancelRunRequestSuccess: ({ cancelRunRequest }) => {
            lemonToast.success('Wizard run canceled.')

            actions.refreshRuns()
            if (cancelRunRequest?.id === values.selectedRunId) {
                actions.loadRunDetails({ runId: cancelRunRequest.id })
                actions.loadRunArtifacts({ runId: cancelRunRequest.id })
            }
        },
        cancelRunRequestFailure: ({ errorObject }) => {
            lemonToast.error(requestError(errorObject, "Couldn't cancel the Wizard run. Try again."))
        },
        copyRunId: ({ runId }) => {
            void copyToClipboard(runId, 'Wizard run ID')
        },
    })),
])
