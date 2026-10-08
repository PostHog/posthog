import { renderToStaticMarkup } from 'react-dom/server'

import { MarketingMetricCard } from './MarketingMetricCard'

describe('MarketingMetricCard', () => {
    it.each([
        { loading: true, expected: /Loading…/ },
        { loading: false, expected: /^$/ },
    ])('renders a missing specification with loading=$loading', ({ loading, expected }) => {
        const markup = renderToStaticMarkup(<MarketingMetricCard loading={loading} labelFromKey={(key) => key} />)

        expect(markup).toMatch(expected)
    })
})
