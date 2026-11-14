import { BAND_LABEL } from './ToolIntentProfile'

describe('ToolIntentProfile band tags', () => {
    it('labels every focus band and avoids the unfilled success and warning tag types', () => {
        expect(Object.keys(BAND_LABEL).sort()).toEqual(['consolidated', 'mixed', 'spread'])
        // Those two render faint text with no fill, which reads as nearly invisible on a light card.
        const types = Object.values(BAND_LABEL).map(({ tagType }) => tagType)
        expect(types).not.toContain('success')
        expect(types).not.toContain('warning')
    })
})
