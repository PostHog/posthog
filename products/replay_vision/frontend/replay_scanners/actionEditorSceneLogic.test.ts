import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionActionApi } from '../generated/api.schemas'
import { actionEditorSceneLogic } from './actionEditorSceneLogic'

const existingAction: VisionActionApi = {
    id: 'e',
    name: 'action-e',
    scanner: 's1',
    enabled: true,
    trigger_config: { rrule: 'FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=14;BYMINUTE=30', timezone: 'Europe/Prague' },
    synthesis_config: { prompt_guide: 'focus on checkout' },
    delivery_config: [{ type: 'slack', integration_id: 5, channel: 'C123' }],
    next_run_at: null,
    last_run_at: null,
    hog_flow_id: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: '2026-01-01T00:00:00Z',
}

describe('actionEditorSceneLogic', () => {
    let logic: ReturnType<typeof actionEditorSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/:id/': existingAction,
            },
            post: {
                '/api/projects/:team/vision/actions/': () => [201, { ...existingAction, id: 'created' }],
            },
        })
        initKeaTests()
        logic = actionEditorSceneLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('the new-action route sets create mode, the scanner, and a fresh form', async () => {
        router.actions.push(urls.replayVisionActionNew('s1'))
        await expectLogic(logic).toMatchValues({
            isNew: true,
            scannerId: 's1',
            effectiveScannerId: 's1',
            actionForm: expect.objectContaining({ name: '', prompt_guide: '', integration_id: null }),
        })
    })

    it('the edit route switches to edit mode and loads the action', async () => {
        await expectLogic(logic, () => {
            router.actions.push(urls.replayVisionActionEdit('e'))
        }).toDispatchActions(['setActionId', 'loadAction'])
        expect(logic.values.isNew).toEqual(false)
    })

    it('loading an action seeds the form from it', async () => {
        logic.actions.loadAction('e')
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                effectiveScannerId: 's1',
                actionForm: {
                    name: 'action-e',
                    cadence: { weekdays: [0, 2], hour: 14, minute: 30 },
                    timezone: 'Europe/Prague',
                    prompt_guide: 'focus on checkout',
                    integration_id: 5,
                    channel: 'C123',
                },
            })
    })

    it('creating an action submits and navigates to the new action page', async () => {
        await expectLogic(logic, () => {
            router.actions.push(urls.replayVisionActionNew('s1'))
        }).toDispatchActions(['setActionId'])
        logic.actions.setActionFormValue('name', 'My action')
        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        }).toDispatchActions(['submitActionFormSuccess'])
        // The location carries a /project/:id prefix in tests; assert the action path is present.
        expect(router.values.location.pathname).toContain(urls.replayVisionAction('created'))
    })

    it('surfaces the API error detail when the submit fails', async () => {
        useMocks({
            post: {
                '/api/projects/:team/vision/actions/': () => [400, { detail: 'nope' }],
            },
        })
        const errorToast = jest.spyOn(lemonToast, 'error')
        router.actions.push(urls.replayVisionActionNew('s1'))
        await expectLogic(logic).toDispatchActions(['setActionId'])
        logic.actions.setActionFormValue('name', 'My action')
        await expectLogic(logic, () => {
            logic.actions.submitActionForm()
        }).toDispatchActions(['submitActionFormFailure'])
        // The toast must surface the API's `detail` so the user sees why it failed, not a generic message.
        expect(errorToast).toHaveBeenCalledWith(expect.stringContaining('nope'))
    })
})
