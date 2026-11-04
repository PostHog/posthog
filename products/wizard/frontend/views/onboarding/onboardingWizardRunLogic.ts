import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import type { WizardRunApi, WizardRunArtifactApi } from '../../generated/api.schemas'
import { wizardRunEventProperties } from '../../lib/wizardAnalytics'
import { loadWizardOnboardingStartTime } from '../../lib/wizardApi'
import { selectWizardInstallRun } from '../../lib/wizardRunDisplay'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'

interface OnboardingWizardRunProps {
    projectId: string
    userId: number
}

type SavedOnboardingWizardRun = Pick<WizardRunApi, 'id' | 'created_at'>
export type WizardOnboardingArtifactClickSource = 'artifact_list' | 'review_button'

export interface onboardingWizardRunLogicValues {
    userRuns: WizardRunApi[]
    onboardingStartedAt: string | null
    savedRun: SavedOnboardingWizardRun | null
    run: WizardRunApi | null
}

export interface onboardingWizardRunLogicActions {
    initializeOnboarding: () => { value: true }
    syncRun: () => { value: true }
    startOnboarding: (timestamp: string) => { timestamp: string }
    saveRun: (run: SavedOnboardingWizardRun) => { run: SavedOnboardingWizardRun }
    loadRunData: (run: WizardRunApi) => { run: WizardRunApi }
    watchRuns: (source: string, runIds: string[]) => { source: string; runIds: string[] }
    clickArtifact: (
        artifact: WizardRunArtifactApi,
        clickSource: WizardOnboardingArtifactClickSource
    ) => { artifact: WizardRunArtifactApi; clickSource: WizardOnboardingArtifactClickSource }
}

export type onboardingWizardRunLogicType = MakeLogicType<
    onboardingWizardRunLogicValues,
    onboardingWizardRunLogicActions,
    OnboardingWizardRunProps
>

export const onboardingWizardRunLogic: LogicWrapper<onboardingWizardRunLogicType> = kea<onboardingWizardRunLogicType>([
    props({} as OnboardingWizardRunProps),
    key(({ projectId, userId }) => `${projectId}.${userId}`),
    path((key) => ['products', 'wizard', 'onboardingWizardRunLogic', key]),
    connect(({ projectId }: OnboardingWizardRunProps) => ({
        values: [wizardRunSyncLogic({ projectId }), ['userRuns']],
        actions: [wizardRunSyncLogic({ projectId }), ['loadRunData', 'watchRuns']],
    })),
    actions({
        initializeOnboarding: true,
        syncRun: true,
        startOnboarding: (timestamp: string) => ({ timestamp }),
        saveRun: (run: SavedOnboardingWizardRun) => ({ run }),
        clickArtifact: (artifact: WizardRunArtifactApi, clickSource: WizardOnboardingArtifactClickSource) => ({
            artifact,
            clickSource,
        }),
    }),
    reducers(({ props: { projectId, userId } }) => ({
        onboardingStartedAt: [
            null as string | null,
            // The scope prevents one user's installation from being restored in another project or account.
            { persist: true, storageKey: `${projectId}.${userId}.onboarding_wizard_started_at` },
            {
                startOnboarding: (state, { timestamp }) =>
                    Number.isFinite(Date.parse(state ?? '')) ? state : timestamp,
            },
        ],
        savedRun: [
            null as SavedOnboardingWizardRun | null,
            { persist: true, storageKey: `${projectId}.${userId}.onboarding_wizard_run_id` },
            { saveRun: (_, { run }) => run },
        ],
    })),
    selectors(({ props }) => ({
        run: [
            (s) => [s.userRuns, s.onboardingStartedAt, s.savedRun],
            (
                runs: WizardRunApi[],
                startedAt: string | null,
                savedRun: SavedOnboardingWizardRun | null
            ): WizardRunApi | null =>
                startedAt && props.projectId && props.userId
                    ? selectWizardInstallRun(
                          runs.filter((run) => run.created_by_id === props.userId),
                          startedAt,
                          savedRun
                      )
                    : null,
        ],
    })),
    listeners(({ actions, values, props: { projectId }, cache }) => ({
        initializeOnboarding: async (_, breakpoint) => {
            const timestamp = await loadWizardOnboardingStartTime(projectId)
            await breakpoint()
            actions.startOnboarding(timestamp)
            actions.syncRun()
        },
        clickArtifact: ({ artifact, clickSource }) => {
            if (values.run) {
                posthog.capture('wizard onboarding state artifact clicked', {
                    ...wizardRunEventProperties(values.run),
                    artifact_type: artifact.artifact_type,
                    artifact_id: artifact.id,
                    click_source: clickSource,
                })
            }
        },
        [wizardRunSyncLogic({ projectId }).actionTypes.runsLoaded]: () => actions.syncRun(),
        [wizardRunSyncLogic({ projectId }).actionTypes.runUpdated]: () => actions.syncRun(),
        syncRun: () => {
            const run = values.run
            actions.watchRuns('onboarding', run ? [run.id] : [])
            if (!run) {
                return
            }
            if (run.id !== values.savedRun?.id) {
                actions.saveRun({ id: run.id, created_at: run.created_at })
            }
            if (cache.shownState !== `${run.id}:${run.status}`) {
                cache.shownState = `${run.id}:${run.status}`
                posthog.capture('wizard onboarding run shown', wizardRunEventProperties(run))
            }
            actions.loadRunData(run)
        },
    })),
    afterMount(({ actions, values, props, cache }) => {
        if (!props.projectId || !props.userId) {
            return
        }
        if (!values.onboardingStartedAt || !Number.isFinite(Date.parse(values.onboardingStartedAt))) {
            actions.initializeOnboarding()
        }
        cache.disposables.add(() => {
            actions.syncRun()
            return () => actions.watchRuns('onboarding', [])
        }, 'onboarding-run-watch')
    }),
])
