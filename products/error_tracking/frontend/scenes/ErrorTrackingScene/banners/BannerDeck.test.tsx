import { cleanup, render } from '@testing-library/react'
import { useEffect } from 'react'

import { BannerDeck } from './BannerDeck'
import type { ErrorTrackingBannerKey } from './bannerQueue'

describe('BannerDeck', () => {
    afterEach(() => {
        cleanup()
    })

    test.each<[string, ErrorTrackingBannerKey[], ErrorTrackingBannerKey[]]>([
        ['grows', ['source_maps'], ['source_maps', 'alerts', 'rate_limits']],
        ['shrinks', ['source_maps', 'alerts'], ['source_maps']],
    ])('keeps the current banner mounted when the deck %s', (_, before, after) => {
        const onMount = jest.fn()
        function Banner(): JSX.Element {
            useEffect(() => onMount(), [])
            return <div>banner</div>
        }
        const deck = (banners: ErrorTrackingBannerKey[]): JSX.Element => (
            <BannerDeck
                banners={banners}
                current="source_maps"
                onPrevious={jest.fn()}
                onNext={jest.fn()}
                renderCurrent={() => <Banner />}
            />
        )

        const { rerender } = render(deck(before))
        rerender(deck(after))

        expect(onMount).toHaveBeenCalledTimes(1)
    })
})
