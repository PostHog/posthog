import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import type { WorkflowViewApi } from '../../generated/api.schemas'
import { WorkflowSavedViewActions } from './WorkflowSavedViewActions'
import { SavedViewAction } from './workflowSavedViews'
import { FIXTURE_METRICS, FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'
import { workflowsListV2Logic } from './workflowsListV2Logic'
import { workflowsSavedViewsLogic } from './workflowsSavedViewsLogic'

const VIEW_ID = '00000000-0000-4000-8000-000000000001'
const savedView: WorkflowViewApi = {
    id: VIEW_ID,
    name: 'Active flows',
    state: { filters: [{ facet: 'status', value: 'active', negated: false }], text: '', columns: ['health'] },
    version: 1,
    default_key: null,
    deleted: false,
    created_at: '2026-10-07T00:00:00Z',
    updated_at: '2026-10-07T00:00:00Z',
    user_access_level: 'editor',
}

describe('saved workflow view actions', () => {
    let logic: ReturnType<typeof workflowsSavedViewsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => [200, paginated(FIXTURE_WORKFLOWS)],
                '/api/projects/:team_id/hog_flows/metrics/global/': () => [200, FIXTURE_METRICS],
                '/api/projects/:team_id/workflow_views/': () => [200, paginated([savedView])],
            },
            post: {
                '/api/projects/:team_id/workflow_views/initialize/': () => [403, {}],
            },
        })
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                hog_flow: AccessControlLevel.Editor,
            },
        }
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        router.actions.push(urls.workflows(), { view: VIEW_ID })
        logic = workflowsSavedViewsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSavedViewsSuccess'])
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each<[SavedViewAction, string]>([
        ['reset', 'workflows-combined-reset-view'],
        ['update', 'workflows-combined-update-view'],
        ['save-as', 'workflows-combined-save-as-new'],
    ])('spins only the button that started a pending %s', (pendingAction, startedBy) => {
        workflowsListV2Logic.actions.setValue({ filters: [], text: '' })
        logic.actions.setPendingAction(pendingAction)
        const { container } = render(<WorkflowSavedViewActions />)
        const spinning = [...container.querySelectorAll('.LemonButton--loading')].map((button) =>
            button.getAttribute('data-attr')
        )
        expect(spinning).toEqual([startedBy])
    })

    it.each([
        [
            'a teammate changed, so a failed rename or delete can be retried',
            () => logic.actions.setConflictedViewIds([VIEW_ID]),
            'Load the latest version of Active flows',
        ],
        [
            'carries search text from another view',
            () => logic.actions.setAddedText('renewal'),
            'Discard your changes and go back to Active flows',
        ],
    ])('offers reset on an unchanged view that %s', async (_, arrange, label) => {
        arrange()
        expect(logic.values.isModified).toBe(false)
        render(<WorkflowSavedViewActions />)
        await expectLogic(logic, async () => {
            await userEvent.click(screen.getByLabelText(label))
        }).toDispatchActions(['resetView'])
    })
})
