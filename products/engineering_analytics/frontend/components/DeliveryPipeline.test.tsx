import { render } from '@testing-library/react'

import { DeliveryPipeline } from './DeliveryPipeline'

describe('DeliveryPipeline', () => {
    it('removes placeholders when loading settles without any usable timing data', () => {
        const { container, rerender } = render(<DeliveryPipeline pipeline={null} mergeToDeploy={null} loading />)

        expect(container.firstChild).not.toBeNull()

        rerender(<DeliveryPipeline pipeline={null} mergeToDeploy={null} loading={false} />)

        expect(container.firstChild).toBeNull()
    })
})
