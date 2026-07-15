import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionActionApi } from '../generated/api.schemas'
import { actionEditorSceneLogic } from './actionEditorSceneLogic'

const existingAction = {
    id: 'e',
    name: 'action-e',
    scanner: 's1',
    enabled: true,
    trigger_config: { rrule: 'FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=14;BYMINUTE=30', timezone: 'Europe/Prague' },
    selection: { verdict: ['yes'], min_score: 2 },
    synthesis_config: { prompt_guide: 'focus on checkout' },
    delivery_config: [{ type: 'slack', integration_id: 5, channel: 'C123' }],
} as unknown as VisionActionApi

const existingAlert = {
    ...existingAction,
    id: 'al1',
    name: 'alert-a',
    mode: 'alert',
    selection: { tags: ['rage-click'] },
    alert_config: { frequency: 'on_breach', metric: 'count', operator: 'gte', threshold: 3, window_days: 7 },
} as unknown as VisionActionApi

const summarizerAlert = {
    ...existingAlert,
    id: 'al2',
    scanner: 's2',
    selection: {},
} as unknown as VisionActionApi

describe('actionEditorSceneLogic', () => {
    let logic: ReturnType<typeof actionEditorSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/:id/': ({ params }) =>
                    params.id === 'al1' ? existingAlert : params.id === 'al2' ? summarizerAlert : existingAction,
                '/api/projects/:team/vision/scanners/:id/': ({ params }) =>
                    params.id === 's2'
                        ? { id: 's2', name: 'Digest scanner', scanner_type: 'summarizer' }
                        : { id: 's1', name: 'Checkout scanner', scanner_type: 'monitor' },
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
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                isNew: true,
                scannerId: 's1',
                effectiveScannerId: 's1',
                scannerName: 'Checkout scanner',
                actionForm: expect.objectContaining({ name: '', prompt_guide: '', integration_id: null }),
            })
    })

    it('the edit route loads the action and seeds the form from it', async () => {
        router.actions.push(urls.replayVisionActionEdit('e'))
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                isNew: false,
                effectiveScannerId: 's1',
                // The stored selection must surface as the "only matching" state, not hide behind "all".
                targetingMode: 'filtered',
                actionForm: {
                    name: 'action-e',
                    cadence: { weekdays: [0, 2], hour: 14, minute: 30 },
                    timezone: 'Europe/Prague',
                    prompt_guide: 'focus on checkout',
                    integration_id: 5,
                    channel: 'C123',
                    verdict: ['yes'],
                    tags: [],
                    min_score: 2,
                    max_score: null,
                    mode: 'group_summary',
                    alert_frequency: 'every_match',
                    alert_metric: 'count',
                    alert_threshold: 1,
                    alert_window_days: 1,
                },
            })

        // Switching back to "all" must clear the filter values — otherwise a hidden filter would
        // silently keep narrowing the summary after save.
        logic.actions.setTargetingMode('all')
        await expectLogic(logic).toMatchValues({
            actionForm: expect.objectContaining({ verdict: [], tags: [], min_score: null, max_score: null }),
        })
    })

    it('editing an alert seeds the mode and condition instead of flipping to summary', async () => {
        router.actions.push(urls.replayVisionActionEdit('al1'))
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                targetingMode: 'filtered',
                actionForm: expect.objectContaining({
                    mode: 'alert',
                    alert_frequency: 'on_breach',
                    alert_metric: 'count',
                    alert_threshold: 3,
                    alert_window_days: 7,
                    tags: ['rage-click'],
                }),
            })
    })

    it('summarizer scanners force alerts to every-match', async () => {
        // Summarizer observations have no verdict/tags/score, so a stored on_breach threshold config
        // must normalize to every_match — otherwise the editor shows "every new summary" while the
        // submit would silently keep the threshold condition.
        router.actions.push(urls.replayVisionActionEdit('al2'))
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                scannerType: 'summarizer',
                actionForm: expect.objectContaining({
                    mode: 'alert',
                    alert_frequency: 'every_match',
                    alert_metric: 'count',
                }),
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
