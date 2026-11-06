import { LABEL_HEIGHT, resolveLabelTop } from './spendTrajectoryCaptionLayout'

describe('spendTrajectoryCaptionLayout', () => {
    it('keeps a top-edge marker label clear of its reference line', () => {
        const referenceY = 16
        const top = resolveLabelTop(referenceY, [referenceY])

        expect(top - LABEL_HEIGHT / 2).toBeGreaterThanOrEqual(0)
        expect(top + LABEL_HEIGHT / 2).toBeLessThan(referenceY)
    })
})
