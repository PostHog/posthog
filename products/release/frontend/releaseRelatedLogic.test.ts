import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { surveysCreate } from 'products/surveys/frontend/generated/api'

import { releasesList, releasesPartialUpdate } from './generated/api'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import type { ReleaseRow } from './releaseUtils'

const EMPTY_PAGE = { results: [], count: 0, next: null }

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))
jest.mock('./generated/api', () => ({
    releasesList: jest.fn(),
    releasesCreate: jest.fn(),
    releasesPartialUpdate: jest.fn(),
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
jest.mock('products/surveys/frontend/generated/api', () => ({
    surveysCreate: jest.fn(),
    surveysList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/product_analytics/frontend/generated/api', () => ({
    insightsList: jest.fn(async () => EMPTY_PAGE),
}))

const RELEASE = {
    id: 'r1',
    name: 'Quiet theme',
    feature_flag_ids: [],
    broadcast_ids: [],
    broadcasts: [],
    survey_ids: ['s1'],
    surveys: [
        {
            id: 's1',
            name: 'Quiet theme feedback',
            created_at: '2026-11-02T00:00:00Z',
            start_date: '2026-11-03T00:00:00Z',
            end_date: null,
            linked_flag_id: null,
            archived: false,
        },
    ],
    insight_ids: [4],
    insights: [],
    has_hidden_flags: false,
    created_at: '2026-11-01T00:00:00Z',
}

const mockedPartialUpdate = jest.mocked(releasesPartialUpdate)
const mockedSurveysCreate = jest.mocked(surveysCreate)

describe('releaseRelatedLogic', () => {
    let logic: ReturnType<typeof releaseRelatedLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.mocked(releasesList).mockResolvedValue({ results: [RELEASE], count: 1, next: null } as never)
        mockedPartialUpdate.mockReset()
        mockedPartialUpdate.mockImplementation(async (_project, _id, changes) => ({ ...RELEASE, ...changes }) as never)
        mockedSurveysCreate.mockReset()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASES_AREA], { [FEATURE_FLAGS.RELEASES_AREA]: true })
        releaseLogic.mount()
        logic = releaseRelatedLogic()
        logic.mount()
        await expectLogic(releaseLogic).toFinishAllListeners()
    })

    it.each([
        ['links a survey', 'linkRelated', 'survey', 's2', { survey_ids: ['s1', 's2'] }],
        ['links an insight', 'linkRelated', 'insight', '5', { insight_ids: [4, 5] }],
        ['unlinks a survey', 'unlinkRelated', 'survey', 's1', { survey_ids: [] }],
        ['unlinks an insight', 'unlinkRelated', 'insight', '4', { insight_ids: [] }],
    ] as const)('%s', async (_name, action, kind, id, payload) => {
        logic.actions[action]('r1', kind, id)
        await expectLogic(releaseLogic).toFinishAllListeners()

        expect(mockedPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'r1', payload)
    })

    it('passes the linked survey summaries from the release to the calendar', () => {
        expect(logic.values.relatedByRelease['r1'].surveys.map((survey) => survey.id)).toEqual(['s1'])
    })

    it('creates one survey when New survey is clicked twice', async () => {
        let resolve: (survey: { id: string }) => void = () => {}
        mockedSurveysCreate.mockImplementation(() => new Promise((done) => (resolve = done)) as never)
        const row = { id: 'r1', name: 'Quiet theme', flags: [] } as unknown as ReleaseRow

        logic.actions.createReleaseSurvey(row)
        logic.actions.createReleaseSurvey(row)
        expect(logic.values.creatingSurvey).toBe(true)
        resolve({ id: 's2' })
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(releaseLogic).toFinishAllListeners()

        expect(mockedSurveysCreate).toHaveBeenCalledTimes(1)
        expect(mockedPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'r1', { survey_ids: ['s1', 's2'] })
        expect(logic.values.creatingSurvey).toBe(false)
    })
})
