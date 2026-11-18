import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { mockScoutConfigs } from '../../../__mocks__/scoutConfigs'
import { ScoutExemptionBadge } from './ScoutBadges'

describe('ScoutExemptionBadge', () => {
    const config = mockScoutConfigs[0]

    afterEach(cleanup)

    it('labels an operational scout in every roster group', () => {
        // A badge that only showed while "watching" would vanish the week the scout files a
        // report, which is exactly when someone might switch it off as an ordinary scout.
        render(<ScoutExemptionBadge config={{ ...config, scout_role: 'operational' }} group="working" />)
        expect(screen.getByText('Operational')).toBeInTheDocument()
    })

    it('labels a hand-exempted specialist as quiet by design', () => {
        render(
            <ScoutExemptionBadge
                config={{ ...config, scout_role: 'specialist', auto_pause_exempt: true }}
                group="watching"
            />
        )
        expect(screen.getByText('Quiet by design')).toBeInTheDocument()
    })

    it('renders nothing for a scout the sweep still judges', () => {
        const { container } = render(
            <ScoutExemptionBadge
                config={{ ...config, scout_role: 'specialist', auto_pause_exempt: false }}
                group="watching"
            />
        )
        expect(container).toBeEmptyDOMElement()
    })
})
