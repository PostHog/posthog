import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import {
    metricsDashboardTemplatesList,
    metricsDashboardTemplatesPreviewCreate,
} from 'products/metrics/frontend/generated/api'

import { metricsDashboardReviewSceneLogic } from './metricsDashboardReviewSceneLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsDashboardTemplatesList: jest.fn(),
    metricsDashboardTemplatesPreviewCreate: jest.fn(),
}))

describe('metricsDashboardReviewSceneLogic', () => {
    let logic: ReturnType<typeof metricsDashboardReviewSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(metricsDashboardTemplatesList).mockResolvedValue([])
        logic = metricsDashboardReviewSceneLogic()
        logic.mount()
        logic.actions.setTemplateId('template-1')
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it.each([
        {
            name: 'shows a 4xx detail without a loader failure',
            error: new ApiError('Bad request', 400, undefined, { detail: 'No matching metrics.' }),
            dispatched: ['setPreviewError', 'openPreviewSuccess'],
            notDispatched: 'openPreviewFailure',
            previewError: 'No matching metrics.',
        },
        {
            name: 'fails the loader on a 5xx',
            error: new ApiError('Server error', 500),
            dispatched: ['openPreviewFailure', 'setPreviewError'],
            notDispatched: 'openPreviewSuccess',
            previewError: 'Could not build the preview dashboard.',
        },
    ])('$name', async ({ error, dispatched, notDispatched, previewError }) => {
        jest.mocked(metricsDashboardTemplatesPreviewCreate).mockRejectedValue(error)

        await expectLogic(logic, () => {
            logic.actions.openPreview({ templateId: 'template-1' })
        })
            .toDispatchActions(dispatched)
            .toNotHaveDispatchedActions([notDispatched])
            .toMatchValues({ previewError, previewLoading: false })
    })
})
