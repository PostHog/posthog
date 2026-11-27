import { expectLogic } from 'kea-test-utils'

import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Survey, SurveyType } from '~/types'

import { surveysActivityRetrieve } from 'products/surveys/frontend/generated/api'
import type {
    ActivityLogEntryApi,
    ActivityLogPaginatedResponseApi,
} from 'products/surveys/frontend/generated/api.schemas'

import { surveyProvenanceLogic } from './surveyProvenanceLogic'

jest.mock('products/surveys/frontend/generated/api', () => ({
    ...jest.requireActual('products/surveys/frontend/generated/api'),
    surveysActivityRetrieve: jest.fn(),
}))

const SURVEY_ID = 'survey-id'
const SURVEY = {
    id: SURVEY_ID,
    name: 'Draft survey',
    type: SurveyType.Popover,
    questions: [],
    created_at: '2026-03-01T09:00:00Z',
    created_by: null,
} as unknown as Survey

const mockActivity = surveysActivityRetrieve as jest.MockedFunction<typeof surveysActivityRetrieve>

function entry(activity: 'created' | 'updated', client: string | null): ActivityLogEntryApi {
    return {
        id: `${activity}-${client}`,
        user: null,
        activity,
        scope: 'Survey',
        item_id: SURVEY_ID,
        created_at: '2026-03-01T09:00:00Z',
        is_system: false,
        was_impersonated: false,
        client,
        detail: { id: SURVEY_ID, name: 'Draft survey', short_id: '', type: '' },
    }
}

function page(results: ActivityLogEntryApi[], next: string | null = null): ActivityLogPaginatedResponseApi {
    return { results, next, previous: null, total_count: results.length }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => (resolve = r))
    return { promise, resolve }
}

describe('surveyProvenanceLogic', () => {
    let logic: ReturnType<typeof surveyProvenanceLogic.build>

    beforeEach(() => {
        mockActivity.mockReset()
        useMocks({ get: { '/api/projects/:team/surveys/:id/': SURVEY } })
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    // The survey loads first so its own load-success doesn't add a refetch the tests would have to count.
    async function mount(): Promise<void> {
        const surveyLoaded = surveyLogic({ id: SURVEY_ID })
        surveyLoaded.mount()
        await expectLogic(surveyLoaded).toDispatchActions(['loadSurveySuccess'])
        logic = surveyProvenanceLogic({ surveyId: SURVEY_ID })
        logic.mount()
    }

    it('finds the created row on a later page when edits push it past the first one', async () => {
        const edits = Array.from({ length: 100 }, () => entry('updated', null))
        mockActivity
            .mockResolvedValueOnce(page(edits, 'next-url'))
            .mockResolvedValueOnce(page([entry('created', 'mcp')]))

        await mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockActivity.mock.calls.map(([, , params]) => params)).toEqual([
            { limit: 100, page: 1 },
            { limit: 100, page: 2 },
        ])
        expect(logic.values.provenance?.channel).toBe('mcp')
    })

    it.each(['loadSurveySuccess', 'updateSurveySuccess'] as const)('refetches after %s', async (action) => {
        mockActivity.mockResolvedValue(page([entry('created', null)]))
        await mount()
        await expectLogic(logic).toFinishAllListeners()
        mockActivity.mockClear()

        surveyLogic({ id: SURVEY_ID }).actions[action](SURVEY)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockActivity).toHaveBeenCalledTimes(1)
    })

    it('keeps the newest response when an older request resolves last', async () => {
        const older = deferred<ActivityLogPaginatedResponseApi>()
        const newer = deferred<ActivityLogPaginatedResponseApi>()
        mockActivity.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)

        await mount()
        logic.actions.loadActivity()
        newer.resolve(page([entry('created', 'mcp')]))
        await expectLogic(logic).toDispatchActions(['loadActivitySuccess'])
        older.resolve(page([entry('created', null)]))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.provenance?.channel).toBe('mcp')
    })
})
