import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { issueFiltersLogic } from './issueFiltersLogic'
import { NegatedFilterWarning } from './NegatedFilterWarning'

const LOGIC_KEY = 'test'

function renderWithFilter(values: UniversalFiltersGroup['values']): void {
    const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
    logic.mount()
    logic.actions.setFilterGroup({
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values }],
    })
    render(
        <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
            <NegatedFilterWarning />
        </BindLogic>
    )
}

describe('NegatedFilterWarning', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('warns and names the property when a negated filter targets an unset property', () => {
        renderWithFilter([
            {
                type: PropertyFilterType.Event,
                key: 'error_name',
                operator: PropertyOperator.IsNot,
                value: ['AxiosError'],
            },
        ])
        expect(screen.getByText('error_name')).toBeInTheDocument()
    })
})
