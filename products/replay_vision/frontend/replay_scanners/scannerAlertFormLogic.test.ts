import type { VisionAlertConfigurationApi } from '../generated/api.schemas'
import { buildFormDefaults, buildSelection } from './scannerAlertFormLogic'

describe('scannerAlertFormLogic selection mapping', () => {
    it('round-trips an alert selection through form defaults and back', () => {
        const alert = {
            id: 'a1',
            name: 'Failed checkouts',
            kind: 'match',
            selection: { verdict: ['yes'], tags: ['checkout'], min_score: 2 },
            metric: 'count',
            direction: 'above',
            threshold: null,
            window_days: 1,
            evaluation_periods: 1,
            datapoints_to_alarm: 1,
            cooldown_minutes: 0,
            schedule_restriction: null,
        } as unknown as VisionAlertConfigurationApi

        const form = buildFormDefaults(alert)
        expect(buildSelection(form)).toEqual({ verdict: ['yes'], tags: ['checkout'], min_score: 2 })
    })

    it('empty selection stays empty', () => {
        const alert = { selection: {} } as unknown as VisionAlertConfigurationApi
        expect(buildSelection(buildFormDefaults(alert))).toEqual({})
    })
})
