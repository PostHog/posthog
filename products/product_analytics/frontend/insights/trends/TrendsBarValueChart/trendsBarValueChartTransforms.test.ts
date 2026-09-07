import { AGGREGATED_MAX_BAND_SIZE, buildTrendsBarValueConfig } from './trendsBarValueChartTransforms'

describe('buildTrendsBarValueConfig', () => {
    it('caps row thickness so a one-row breakdown does not fill the plot', () => {
        expect(buildTrendsBarValueConfig().bars?.maxBandSize).toBe(AGGREGATED_MAX_BAND_SIZE)
    })
})
