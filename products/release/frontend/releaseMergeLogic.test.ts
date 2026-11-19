import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { releasesList, releasesMergeCreate } from './generated/api'
import { releaseLogic } from './releaseLogic'
import { releaseMergeLogic } from './releaseMergeLogic'

const EMPTY_PAGE = { results: [], count: 0, next: null }

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))
jest.mock('./generated/api', () => ({
    releasesList: jest.fn(),
    releasesMergeCreate: jest.fn(),
}))
jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsList: jest.fn(async () => EMPTY_PAGE),
    featureFlagsRetrieve: jest.fn(),
    scheduledChangesList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsList: jest.fn(async () => EMPTY_PAGE),
    hogFlowsSendCalendarRetrieve: jest.fn(async () => ({ flows: [] })),
}))
jest.mock('products/early_access_features/frontend/generated/api', () => ({
    earlyAccessFeatureList: jest.fn(async () => EMPTY_PAGE),
    earlyAccessFeatureRetrieve: jest.fn(),
}))

const release = (id: string, name: string): Record<string, unknown> => ({
    id,
    name,
    description: '',
    feature_flag_ids: [],
    broadcast_ids: [],
    broadcasts: [],
    survey_ids: [],
    surveys: [],
    insight_ids: [],
    metric_insight_ids: [],
    metric_goals: [],
    insights: [],
    has_hidden_flags: false,
    created_at: '2026-11-01T00:00:00Z',
})

const mockedMerge = jest.mocked(releasesMergeCreate)

describe('releaseMergeLogic', () => {
    let logic: ReturnType<typeof releaseMergeLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.mocked(releasesList).mockResolvedValue({
            results: [release('r1', 'Checkout'), release('r2', 'Checkout copy'), release('r3', 'Checkout form')],
            count: 3,
            next: null,
        } as never)
        mockedMerge.mockReset()
        mockedMerge.mockResolvedValue(release('r1', 'Checkout v2') as never)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASE_OBJECTS], {
            [FEATURE_FLAGS.RELEASE_OBJECTS]: true,
        })
        releaseLogic.mount()
        logic = releaseMergeLogic()
        logic.mount()
        await expectLogic(releaseLogic).toFinishAllListeners()
    })

    it('merges the picked releases into the open one, never sending the open one itself', async () => {
        logic.actions.openMergeInto('r1')
        logic.actions.setMergeSources(['r2', 'r3'])
        logic.actions.editMergeName('Checkout v2')
        logic.actions.mergeReleases('r1')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedMerge).toHaveBeenCalledWith(expect.any(String), 'r1', {
            release_ids: ['r2', 'r3'],
            name: 'Checkout v2',
        })
        expect(logic.values.selection).toEqual({})
    })

    it.each([
        ['search', (): void => releaseLogic.actions.setSearch('copy')],
        ['stage filter', (): void => releaseLogic.actions.setStageFilter('flag')],
        ['decision filter', (): void => releaseLogic.actions.setDecisionOnly(true)],
    ])('clears the list selection when the %s changes', (_name, changeFilter) => {
        logic.actions.setSelection({ r1: true, r2: true })
        changeFilter()

        expect(logic.values.selection).toEqual({})
    })

    it('clears the selection when the release page dialog closes without merging', () => {
        logic.actions.openMergeInto('r1')
        logic.actions.setMergeSources(['r2'])
        logic.actions.setMergeOpen(false)

        expect([logic.values.selection, logic.values.mergeTargetId]).toEqual([{}, null])
    })
})
