import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionActionApi } from '../generated/api.schemas'
import { DeliveryTargetTypeEnumApi } from '../generated/api.schemas'
import { buildActionBody, type VisionActionForm, visionActionsLogic } from './visionActionsLogic'

const action = (id: string, enabled = true): VisionActionApi => ({
    id,
    name: `action-${id}`,
    scanner: 's1',
    enabled,
    trigger_config: { rrule: 'FREQ=DAILY' },
    delivery_config: [],
    next_run_at: null,
    last_run_at: null,
    hog_flow_id: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: '2026-01-01T00:00:00Z',
})

describe('visionActionsLogic', () => {
    let logic: ReturnType<typeof visionActionsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/': { results: [action('a'), action('b')], count: 2 },
            },
            post: {
                '/api/projects/:team/vision/actions/': () => [201, action('new')],
            },
            patch: {
                '/api/projects/:team/vision/actions/:id/': () => [200, {}],
            },
            delete: {
                '/api/projects/:team/vision/actions/:id/': () => [204, null],
            },
        })
        initKeaTests()
        logic = visionActionsLogic({ scannerId: 's1' })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it("loads the scanner's actions on mount", async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadActions', 'loadActionsSuccess'])
            .toMatchValues({
                visionActions: expect.arrayContaining([
                    expect.objectContaining({ id: 'a' }),
                    expect.objectContaining({ id: 'b' }),
                ]),
            })
    })

    it('toggleActionEnabled optimistically flips the row and marks it in-flight', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadActionsSuccess([action('a', true)])
            logic.actions.toggleActionEnabled('a')
        }).toMatchValues({
            visionActions: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
            togglingIds: ['a'],
        })
    })

    it('revertActionEnabled flips the row back and clears the in-flight id', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadActionsSuccess([action('a', true)])
            logic.actions.toggleActionEnabled('a')
            logic.actions.revertActionEnabled('a')
        }).toMatchValues({
            visionActions: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: true })]),
            togglingIds: [],
        })
    })

    it('deleteActionSuccess removes the row', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadActionsSuccess([action('a'), action('b')])
            logic.actions.deleteActionSuccess('a')
        }).toMatchValues({
            visionActions: [expect.objectContaining({ id: 'b' })],
        })
    })

    it('buildActionBody maps the form to the API body, including a Slack delivery target and targeting', () => {
        const form: VisionActionForm = {
            name: '  Daily digest  ',
            cadence: { weekdays: [0, 2], hour: 14, minute: 30 },
            timezone: 'Europe/Prague',
            prompt_guide: 'focus on checkout',
            integration_id: 5,
            channel: 'C123|#general',
            verdict: ['yes'],
            tags: ['bug'],
            min_score: 1,
            max_score: 5,
            mode: 'group_summary',
            alert_frequency: 'on_breach',
            alert_metric: 'count',
            alert_threshold: 1,
            alert_window_days: 1,
        }
        expect(buildActionBody(form, 's1')).toEqual({
            name: 'Daily digest', // trimmed
            scanner: 's1',
            mode: 'group_summary',
            trigger_config: { rrule: 'FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=14;BYMINUTE=30', timezone: 'Europe/Prague' },
            selection: { verdict: ['yes'], tags: ['bug'], min_score: 1, max_score: 5 },
            synthesis_config: { prompt_guide: 'focus on checkout' },
            // The full `${id}|#${name}` composite is stored so the actions table can show the channel
            // name; the backend strips it to the bare id for the Slack destination.
            delivery_config: [{ type: DeliveryTargetTypeEnumApi.Slack, integration_id: 5, channel: 'C123|#general' }],
        })
    })

    it('buildActionBody emits empty delivery_config and selection when nothing is set', () => {
        const form: VisionActionForm = {
            name: 'No delivery',
            cadence: { weekdays: [0, 1, 2, 3, 4, 5, 6], hour: 9, minute: 0 },
            timezone: 'UTC',
            prompt_guide: '',
            integration_id: null,
            channel: '',
            verdict: [],
            tags: [],
            min_score: null,
            max_score: null,
            mode: 'group_summary',
            alert_frequency: 'on_breach',
            alert_metric: 'count',
            alert_threshold: 1,
            alert_window_days: 1,
        }
        const body = buildActionBody(form, 's1')
        expect(body.delivery_config).toEqual([])
        // Empty selection is sent explicitly so clearing targeting on edit persists as "run on everything".
        expect(body.selection).toEqual({})
        // A summary must not carry an alert condition even though the form holds the defaults.
        expect(body.alert_config).toBeUndefined()
    })

    it('buildActionBody sends the alert condition and drops the prompt guide for alert mode', () => {
        const form: VisionActionForm = {
            name: 'Rage click alert',
            cadence: { weekdays: [0, 1, 2, 3, 4, 5, 6], hour: 9, minute: 0 },
            timezone: 'UTC',
            prompt_guide: 'leftover from summary mode',
            integration_id: null,
            channel: '',
            verdict: [],
            tags: ['rage-click'],
            min_score: null,
            max_score: null,
            mode: 'alert',
            alert_frequency: 'on_breach',
            alert_metric: 'count',
            alert_threshold: 1,
            alert_window_days: 1,
        }
        const body = buildActionBody(form, 's1')
        expect(body.mode).toEqual('alert')
        expect(body.alert_config).toEqual({
            frequency: 'on_breach',
            metric: 'count',
            threshold: 1,
            window_days: 1,
        })
        expect(body.selection).toEqual({ tags: ['rage-click'] })
        // Alerts have no user-facing schedule; the stored rrule keeps the trigger well-formed while
        // the engine checks them on every sweep.
        expect(body.trigger_config).toEqual({ rrule: 'FREQ=HOURLY', timezone: 'UTC' })
        // Alerts never synthesize, so a stale guide from a mode switch must not persist.
        expect(body.synthesis_config).toEqual({ prompt_guide: '' })

        // Every-match alerts carry no threshold machinery — just the frequency and the count metric.
        const everyMatch = buildActionBody({ ...form, alert_frequency: 'every_match' }, 's1')
        expect(everyMatch.alert_config).toEqual({ frequency: 'every_match', metric: 'count' })
    })
})
