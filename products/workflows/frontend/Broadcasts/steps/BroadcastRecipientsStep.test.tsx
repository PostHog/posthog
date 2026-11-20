import '@testing-library/jest-dom'

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { BroadcastRecipientsStep } from './BroadcastRecipientsStep'

const included: AnyPropertyFilter = {
    type: PropertyFilterType.Cohort,
    key: 'id',
    value: 41,
    operator: PropertyOperator.In,
}
const excluded: AnyPropertyFilter = {
    type: PropertyFilterType.Cohort,
    key: 'id',
    value: 42,
    operator: PropertyOperator.NotIn,
}

describe('BroadcastRecipientsStep', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 2, total: 10 }],
            },
        })
        initKeaTests()
    })

    it('shows a cohort excluded by negation as "not in" and keeps it excluded through an unrelated edit', async () => {
        const wizard = broadcastWizardLogic({ id: 'new' })
        wizard.mount()
        wizard.actions.setAudienceProperties([
            included,
            { ...excluded, operator: PropertyOperator.In, negation: true } as AnyPropertyFilter,
        ])

        render(
            <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                <BroadcastRecipientsStep />
            </BindLogic>
        )

        const rows = await screen.findAllByTestId(/^property-filter-\d+$/)
        expect(rows.slice(0, 2).map((row) => row.textContent)).toEqual([
            expect.stringMatching(/^user in/),
            expect.stringMatching(/^user not in/),
        ])

        await userEvent.click(within(rows[0]).getAllByRole('button').at(-1)!)

        expect(wizard.values.audienceProperties).toEqual([excluded])
    })
})
