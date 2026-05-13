import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { SCHEDULE_PRESETS, SyntheticTest, SyntheticTestDraft, SyntheticTestRun, SyntheticTestStep } from '../../types'
import type { syntheticTestSceneLogicType } from './syntheticTestSceneLogicType'

export interface SyntheticTestSceneProps {
    id: string | 'new'
}

const baseUrl = (): string => `api/projects/${getCurrentTeamId()}/synthetic_tests/`
const runsUrl = (): string => `api/projects/${getCurrentTeamId()}/synthetic_test_runs/`

const emptyDraft: SyntheticTestDraft = {
    name: '',
    target_url: '',
    steps: [{ type: 'navigate', url: '' }],
    schedule_cron: SCHEDULE_PRESETS[1].cron,
    timezone: 'UTC',
    create_issue_on_failure: true,
}

export const syntheticTestSceneLogic = kea<syntheticTestSceneLogicType>([
    path((key) => [
        'products',
        'synthetic_tests',
        'frontend',
        'scenes',
        'SyntheticTestScene',
        'syntheticTestSceneLogic',
        key,
    ]),
    props({} as SyntheticTestSceneProps),
    actions({
        setSteps: (steps: SyntheticTestStep[]) => ({ steps }),
        runNow: true,
        seedFromReplay: (sessionRecordingId: string) => ({ sessionRecordingId }),
    }),
    loaders(({ props }) => ({
        test: [
            null as SyntheticTest | null,
            {
                loadTest: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }
                    return await api.get<SyntheticTest>(`${baseUrl()}${props.id}/`)
                },
            },
        ],
        runs: [
            [] as SyntheticTestRun[],
            {
                loadRuns: async () => {
                    if (!props.id || props.id === 'new') {
                        return []
                    }
                    const response = await api.get<{ results: SyntheticTestRun[] }>(
                        `${runsUrl()}?synthetic_test=${props.id}`
                    )
                    return response.results
                },
            },
        ],
        playwrightScript: [
            '' as string,
            {
                loadPlaywrightScript: async () => {
                    if (!props.id || props.id === 'new') {
                        return ''
                    }
                    const response = await api.get<{ script: string }>(`${baseUrl()}${props.id}/playwright_script/`)
                    return response.script
                },
            },
        ],
    })),
    forms(({ props, actions }) => ({
        testForm: {
            defaults: emptyDraft as SyntheticTestDraft,
            submit: async (draft) => {
                if (!draft.name?.trim()) {
                    lemonToast.error('Name is required')
                    return
                }
                if (!draft.target_url?.trim()) {
                    lemonToast.error('Target URL is required')
                    return
                }
                const isNew = !props.id || props.id === 'new'
                const saved = isNew
                    ? await api.create<SyntheticTest>(baseUrl(), draft)
                    : await api.update<SyntheticTest>(`${baseUrl()}${props.id}/`, draft)
                lemonToast.success(isNew ? 'Synthetic test created' : 'Synthetic test saved')
                if (isNew && saved.id) {
                    router.actions.push(`/synthetic_tests/${saved.id}`)
                } else {
                    actions.loadTest()
                }
            },
        },
    })),
    reducers({
        // Mirror the form value via a dedicated reducer so the StepBuilder receives a stable array reference.
        stepsBuffer: [
            emptyDraft.steps,
            {
                setSteps: (_, { steps }) => steps,
            },
        ],
    }),
    listeners(({ values, props, actions }) => ({
        loadTestSuccess: ({ test }) => {
            if (!test) {
                return
            }
            actions.setTestFormValues({
                name: test.name,
                target_url: test.target_url,
                steps: test.steps,
                schedule_cron: test.schedule_cron,
                timezone: test.timezone,
                create_issue_on_failure: test.create_issue_on_failure,
                source_replay_id: test.source_replay_id,
            })
            actions.setSteps(test.steps)
            actions.loadRuns()
            actions.loadPlaywrightScript()
        },
        setSteps: ({ steps }) => {
            actions.setTestFormValue('steps', steps)
        },
        runNow: async () => {
            if (!props.id || props.id === 'new') {
                lemonToast.warning('Save the test before running it')
                return
            }
            await api.create(`${baseUrl()}${props.id}/run_now/`, {})
            lemonToast.success('Run queued — refreshing history')
            actions.loadRuns()
            actions.loadTest()
        },
        seedFromReplay: async ({ sessionRecordingId }) => {
            const draft = await api.create<{ name: string; target_url: string; steps: SyntheticTestStep[] }>(
                `${baseUrl()}generate_from_replay/`,
                { session_recording_id: sessionRecordingId }
            )
            actions.setTestFormValues({
                ...values.testForm,
                name: draft.name,
                target_url: draft.target_url,
                steps: draft.steps,
                source_replay_id: sessionRecordingId,
            })
            actions.setSteps(draft.steps)
            lemonToast.success('Test seeded from session replay — review and save')
        },
    })),
    urlToAction(({ actions, props }) => ({
        '/synthetic_tests/new': (_, searchParams) => {
            if (props.id !== 'new') {
                return
            }
            const sourceReplayId = searchParams?.source_replay_id
            if (sourceReplayId) {
                actions.seedFromReplay(sourceReplayId)
            }
        },
    })),
    selectors({
        isNew: [(_, p) => [p.id as any], (id) => !id || id === 'new'],
    }),
])
