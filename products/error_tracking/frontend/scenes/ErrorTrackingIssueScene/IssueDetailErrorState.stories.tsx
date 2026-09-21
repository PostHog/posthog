import type { Meta, StoryObj } from '@storybook/react'

import { IssueDetailErrorState } from './IssueDetailErrorState'

// What the right pane shows when the query for the linked exception fails. The two states worth a
// snapshot are the failure itself and the retry in flight, since the retry button is the only way
// out of it.

const meta: Meta<typeof IssueDetailErrorState> = {
    title: 'Scenes-App/ErrorTracking/IssueDetailErrorState',
    component: IssueDetailErrorState,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof IssueDetailErrorState>

// The pane is narrow when the nav sidebar and a side panel are both open, which is the width the
// copy and the button have to survive.
function Pane({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="w-[375px] border">{children}</div>
}

export const Failed: Story = {
    render: () => (
        <Pane>
            <IssueDetailErrorState loading={false} onRetry={() => {}} />
        </Pane>
    ),
}

export const Retrying: Story = {
    render: () => (
        <Pane>
            <IssueDetailErrorState loading onRetry={() => {}} />
        </Pane>
    ),
}
