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

    it('buildActionBody maps the form to the API body, including a Slack delivery target', () => {
        const form: VisionActionForm = {
            name: '  Daily digest  ',
            cadence: { weekdays: [0, 2], hour: 14, minute: 30 },
            timezone: 'Europe/Prague',
            prompt_guide: 'focus on checkout',
            integration_id: 5,
            channel: 'C123|#general',
        }
        expect(buildActionBody(form, 's1')).toEqual({
            name: 'Daily digest', // trimmed
            scanner: 's1',
            trigger_config: { rrule: 'FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=14;BYMINUTE=30', timezone: 'Europe/Prague' },
            synthesis_config: { prompt_guide: 'focus on checkout' },
            // The full `${id}|#${name}` composite is stored so the actions table can show the channel
            // name; the backend strips it to the bare id for the Slack destination.
            delivery_config: [{ type: DeliveryTargetTypeEnumApi.Slack, integration_id: 5, channel: 'C123|#general' }],
        })
    })

    it('buildActionBody emits an empty delivery_config when no integration/channel is set', () => {
        const form: VisionActionForm = {
            name: 'No delivery',
            cadence: { weekdays: [0, 1, 2, 3, 4, 5, 6], hour: 9, minute: 0 },
            timezone: 'UTC',
            prompt_guide: '',
            integration_id: null,
            channel: '',
        }
        expect(buildActionBody(form, 's1').delivery_config).toEqual([])
    })
})
