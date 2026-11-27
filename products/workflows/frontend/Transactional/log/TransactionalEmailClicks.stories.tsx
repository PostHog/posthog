import { Meta, StoryFn } from '@storybook/react'

import { EmailClickRow } from './emailClicks'
import { TransactionalEmailClicks, TransactionalEmailClicksProps } from './TransactionalEmailClicks'

const meta: Meta<typeof TransactionalEmailClicks> = {
    title: 'Scenes-App/Transactional/Email clicks',
    component: TransactionalEmailClicks,
    parameters: { mockDate: '2026-06-15', testOptions: { snapshotBrowsers: [] } },
}
export default meta

const ROWS: EmailClickRow[] = [
    { key: 'a', at: '2026-06-15T09:05:00Z', link: 'https://example.com/billing?tab=plans' },
    { key: 'b', at: '2026-06-15T09:07:00Z', link: null },
    { key: 'c', at: '2026-06-15T10:30:00Z', link: 'https://help.example.com/' },
]

const Template: StoryFn<TransactionalEmailClicksProps> = (props) => (
    <div className="max-w-180">
        <TransactionalEmailClicks {...props} />
    </div>
)

export const WithLinks = Template.bind({})
WithLinks.args = { rows: ROWS, links: 'loaded', moreClicks: false, onRetry: () => {} }

export const LinksLoading = Template.bind({})
LinksLoading.args = { rows: ROWS.map((row) => ({ ...row, link: null })), links: 'loading', moreClicks: false }

export const LinksFailedWithOlderClicksLeftOut = Template.bind({})
LinksFailedWithOlderClicksLeftOut.args = {
    rows: ROWS.map((row) => ({ ...row, link: null })),
    links: 'failed',
    moreClicks: true,
    onRetry: () => {},
}
