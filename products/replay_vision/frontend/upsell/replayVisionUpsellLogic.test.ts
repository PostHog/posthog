import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { environmentVisionQuotaRetrieve, visionScannersStatsRetrieve } from '../generated/api'
import { ReplayVisionPlayerCard, replayVisionUpsellLogic } from './replayVisionUpsellLogic'

jest.mock('../generated/api')

const mockStatsRetrieve = visionScannersStatsRetrieve as jest.MockedFunction<typeof visionScannersStatsRetrieve>
const mockQuotaRetrieve = environmentVisionQuotaRetrieve as jest.MockedFunction<typeof environmentVisionQuotaRetrieve>

function statsWithTotal(total: number): Awaited<ReturnType<typeof visionScannersStatsRetrieve>> {
    return {
        total,
        enabled: total,
        by_type: {
            monitor: { enabled: 0, total: 0 },
            classifier: { enabled: 0, total: 0 },
            scorer: { enabled: 0, total: 0 },
            summarizer: { enabled: total, total },
            experiment: { enabled: 0, total: 0 },
        },
    }
}

describe('replayVisionUpsellLogic', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        jest.clearAllMocks()
        localStorage.clear()
        mockQuotaRetrieve.mockResolvedValue(
            null as unknown as Awaited<ReturnType<typeof environmentVisionQuotaRetrieve>>
        )
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation()
    })

    function mountWithVariant(variant: string | undefined): ReturnType<typeof replayVisionUpsellLogic.build> {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.REPLAY_VISION_HEAVY_VIEWER_UPSELL]: variant as string,
        })
        const logic = replayVisionUpsellLogic()
        logic.mount()
        return logic
    }

    // Guards the experiment arms: each variant must show only its own card, the player card must
    // pick the team copy only when scanners exist, and only the player variant pays for the stats call.
    it.each<[string | undefined, number, ReplayVisionPlayerCard | null, boolean, boolean]>([
        [undefined, 0, null, false, false],
        ['control', 0, null, false, false],
        ['player-card', 0, 'starter', false, true],
        ['player-card', 3, 'team', false, true],
        ['list-card', 0, null, true, true],
    ])(
        'with variant %s and %i scanners shows player card %s and list card %s',
        async (variant, total, expectedPlayerCard, expectedListCard, expectedReplacesLaunchBanner) => {
            mockStatsRetrieve.mockResolvedValue(statsWithTotal(total))
            const logic = mountWithVariant(variant)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.playerCard).toBe(expectedPlayerCard)
            expect(logic.values.showListCard).toBe(expectedListCard)
            expect(logic.values.replacesLaunchBanner).toBe(expectedReplacesLaunchBanner)
            expect(mockStatsRetrieve).toHaveBeenCalledTimes(variant === 'player-card' ? 1 : 0)
        }
    )

    // Guards the fail-closed path: without stats the logic cannot pick the right copy, so no card shows.
    it('hides the player card when the scanner stats fail to load', async () => {
        mockStatsRetrieve.mockRejectedValue(new Error('network down'))
        const logic = mountWithVariant('player-card')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.playerCard).toBeNull()
    })

    // Guards the dismissal contract: the weekly cohort refresh removes people by this event, so a
    // dismissal that only writes localStorage keeps the card on the person's other browsers.
    it('hides the card and captures the dismissal', async () => {
        mockStatsRetrieve.mockResolvedValue(statsWithTotal(0))
        const logic = mountWithVariant('player-card')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.dismiss('player')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.playerCard).toBeNull()
        const dismissals = captureSpy.mock.calls.filter(([name]) => name === 'replay_vision_upsell_dismissed')
        expect(dismissals.map((call) => call[1])).toEqual([
            { placement: 'player', variant: 'player-card', team_has_scanners: false },
        ])
    })
})
