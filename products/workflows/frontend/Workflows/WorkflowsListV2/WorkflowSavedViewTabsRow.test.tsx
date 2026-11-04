import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { BUILT_IN_WORKFLOW_VIEWS } from './workflowSavedViews'
import { WorkflowSavedViewTabsRow } from './WorkflowSavedViewTabsRow'

describe('saved workflow view tabs', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('opens More with the keyboard and selects an overflow view', async () => {
        const onApplyView = jest.fn()
        const user = userEvent.setup()
        render(
            <WorkflowSavedViewTabsRow
                views={BUILT_IN_WORKFLOW_VIEWS}
                activeViewId="all"
                viewCounts={{}}
                isModified={false}
                activeViewChanges={[]}
                onApplyView={onApplyView}
                max={1}
            />
        )
        await user.tab()
        expect(screen.getAllByRole('tab')[0]).toHaveFocus()
        await user.tab()
        expect(screen.getByRole('button')).toHaveFocus()
        expect(screen.getByRole('button')).toHaveTextContent('More (2)')
        await user.keyboard('{Enter}{ArrowDown}{Enter}')
        await waitFor(() => expect(onApplyView).toHaveBeenCalledWith(BUILT_IN_WORKFLOW_VIEWS[1]))
        expect(onApplyView).toHaveBeenCalledTimes(1)
    })
    it('shows the full name in a tooltip for a long shared tab', async () => {
        const name = 'Renewal reminders for annual plans requiring follow-up before the next billing cycle'
        const view = { ...BUILT_IN_WORKFLOW_VIEWS[0], id: 'shared', name, builtIn: false }
        const user = userEvent.setup()
        render(
            <WorkflowSavedViewTabsRow
                views={[view]}
                activeViewId="shared"
                viewCounts={{ shared: 2 }}
                isModified
                activeViewChanges={['filters']}
                onApplyView={jest.fn()}
                max={3}
            />
        )
        await user.hover(screen.getByText(name))
        await waitFor(() => expect(screen.getAllByText(name)).toHaveLength(2))
        expect(screen.getByRole('tab')).toHaveAccessibleName(`${name} 2 Modified`)
    })
})
