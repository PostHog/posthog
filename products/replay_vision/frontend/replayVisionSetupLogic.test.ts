import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { visionScannersStatsRetrieve } from './generated/api'
import { replayVisionSetupLogic } from './replayVisionSetupLogic'

jest.mock('./generated/api')

const mockStatsRetrieve = visionScannersStatsRetrieve as jest.MockedFunction<typeof visionScannersStatsRetrieve>

function statsWithTotal(total: number): Awaited<ReturnType<typeof visionScannersStatsRetrieve>> {
    return {
        total,
        enabled: total,
        by_type: {
            monitor: { enabled: 0, total: 0 },
            classifier: { enabled: 0, total: 0 },
            scorer: { enabled: 0, total: 0 },
            summarizer: { enabled: total, total },
        },
    }
}

describe('replayVisionSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    function setupStatus(): string {
        return productSetupStatusLogic({ productKey: ProductKey.REPLAY_VISION }).values.status
    }

    // Guards the connect + mapping into the app-wide setup-status layer: if either
    // breaks, the scene empty-state gate stays on its loading spinner forever.
    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [7, 'has-data'],
    ])('pushes a %i-scanner team into productSetupStatusLogic as %s', async (total, expected) => {
        mockStatsRetrieve.mockResolvedValue(statsWithTotal(total))
        const logic = replayVisionSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus()).toBe(expected)
    })

    // Guards the fail-open path: a persistently failing stats call must publish
    // `unknown` (gate renders the scene), not leave the gate on its spinner forever.
    it('publishes unknown when the stats call fails before any answer exists', async () => {
        mockStatsRetrieve.mockRejectedValue(new Error('network down'))
        const logic = replayVisionSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus()).toBe('unknown')
    })

    it('does not downgrade an existing answer when a later poll fails', async () => {
        mockStatsRetrieve.mockResolvedValue(statsWithTotal(0))
        const logic = replayVisionSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus()).toBe('needs-setup')

        mockStatsRetrieve.mockRejectedValue(new Error('network blip'))
        logic.actions.loadSetupStats()
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus()).toBe('needs-setup')
    })
})
