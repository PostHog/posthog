import { DeliveryPipeline } from './DeliveryPipeline'

describe('DeliveryPipeline', () => {
    it('removes placeholders when loading settles without any usable timing data', () => {
        expect(DeliveryPipeline({ pipeline: null, mergeToDeploy: null, loading: true })).not.toBeNull()
        expect(DeliveryPipeline({ pipeline: null, mergeToDeploy: null, loading: false })).toBeNull()
    })
})
