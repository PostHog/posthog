import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { calibrationActivationLogic } from './calibrationActivationLogic'

const stats = (up: number, down: number, succeeded = 12): Record<string, any> => ({
    labels: { up_total: up, down_total: down, by_day: [], by_rating_day: [], version_markers: [] },
    status_counts: { succeeded },
})

describe('calibrationActivationLogic', () => {
    let statsRequests: number
    let ratings: { up: number; down: number; succeeded: number }
    let logic: ReturnType<typeof calibrationActivationLogic.build>

    const setFlag = (value: string | boolean): void => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_ACTIVATION], {
            [FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_ACTIVATION]: value,
        })
    }

    beforeEach(() => {
        statsRequests = 0
        ratings = { up: 0, down: 0, succeeded: 12 }
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/observations/stats/': () => {
                    statsRequests += 1
                    return [200, stats(ratings.up, ratings.down, ratings.succeeded)]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('resolves the variant from a flag that arrives after mount', async () => {
        // The flag resolves client-side, so it is routinely absent at mount.
        logic = calibrationActivationLogic({ scannerId: 'sid' })
        logic.mount()
        await expectLogic(logic).toMatchValues({ variant: 'control' })
        expect(statsRequests).toBe(0)

        setFlag('badge')

        await expectLogic(logic).toMatchValues({ variant: 'badge' })
        await expectLogic(logic).toFinishAllListeners()
        expect(statsRequests).toBe(1)
    })

    it('does not fetch the rating count for the control arm', async () => {
        setFlag(false)
        logic = calibrationActivationLogic({ scannerId: 'sid' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ variant: 'control', neverRated: false })
        expect(statsRequests).toBe(0)
    })

    it('marks a scanner never rated only once the count is known to be zero', async () => {
        setFlag('prompt')
        logic = calibrationActivationLogic({ scannerId: 'sid' })
        logic.mount()

        // Null while the count is in flight, so the nudge cannot flash on an already-rated scanner.
        expect(logic.values.neverRated).toBe(false)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ neverRated: true })
    })

    it('leaves a rated scanner alone', async () => {
        ratings = { up: 3, down: 1, succeeded: 12 }
        setFlag('badge')
        logic = calibrationActivationLogic({ scannerId: 'sid' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ neverRated: false })
    })

    it('fetches the count once when the flag is already resolved at mount', async () => {
        // `subscriptions` fires at mount when the flag is already in hand, so this pins that the one
        // mount costs one request rather than none.
        setFlag('badge')
        logic = calibrationActivationLogic({ scannerId: 'sid' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(statsRequests).toBe(1)
    })

    it('does not refetch when the variant changes again', async () => {
        // A flag payload can resolve more than once in a session, and the count does not change with
        // the arm, so a second variant only costs a request without the guard.
        setFlag('badge')
        logic = calibrationActivationLogic({ scannerId: 'sid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        setFlag('prompt')

        await expectLogic(logic).toMatchValues({ variant: 'prompt' }).toFinishAllListeners()
        expect(statsRequests).toBe(1)
    })

    it('leaves a scanner with no results alone', async () => {
        // A scanner that has never produced a result has nothing to rate, so an unrated count of zero
        // is not a calibration problem. Gating on the all-time succeeded count keeps the arm stable
        // across billing periods.
        ratings = { up: 0, down: 0, succeeded: 0 }
        setFlag('prompt')
        logic = calibrationActivationLogic({ scannerId: 'sid' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ neverRated: false })
    })
})
