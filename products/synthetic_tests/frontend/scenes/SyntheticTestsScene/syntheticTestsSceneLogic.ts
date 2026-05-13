import { actions, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { SyntheticTest } from '../../types'
import type { syntheticTestsSceneLogicType } from './syntheticTestsSceneLogicType'

const baseUrl = (): string => `api/projects/${getCurrentTeamId()}/synthetic_tests/`

export const syntheticTestsSceneLogic = kea<syntheticTestsSceneLogicType>([
    path(['products', 'synthetic_tests', 'frontend', 'scenes', 'SyntheticTestsScene', 'syntheticTestsSceneLogic']),
    actions({
        deleteTest: (id: string) => ({ id }),
        runNow: (id: string) => ({ id }),
        pauseTest: (id: string) => ({ id }),
        resumeTest: (id: string) => ({ id }),
    }),
    loaders({
        tests: [
            [] as SyntheticTest[],
            {
                loadTests: async () => {
                    const response = await api.get<{ results: SyntheticTest[] }>(baseUrl())
                    return response.results
                },
            },
        ],
    }),
    listeners(({ actions }) => ({
        deleteTest: async ({ id }) => {
            await api.delete(`${baseUrl()}${id}/`)
            actions.loadTests()
        },
        runNow: async ({ id }) => {
            await api.create(`${baseUrl()}${id}/run_now/`, {})
            actions.loadTests()
        },
        pauseTest: async ({ id }) => {
            await api.create(`${baseUrl()}${id}/pause/`, {})
            actions.loadTests()
        },
        resumeTest: async ({ id }) => {
            await api.create(`${baseUrl()}${id}/resume/`, {})
            actions.loadTests()
        },
    })),
    selectors({
        passingCount: [(s) => [s.tests], (tests) => tests.filter((t) => t.last_run?.status === 'passed').length],
        failingCount: [(s) => [s.tests], (tests) => tests.filter((t) => t.last_run?.status === 'failed').length],
    }),
])
