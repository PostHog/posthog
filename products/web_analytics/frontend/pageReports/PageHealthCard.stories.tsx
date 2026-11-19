import type { Meta, StoryObj } from '@storybook/react'

import { PageHealthSummary } from './pageHealth'
import { PageHealthCard } from './PageHealthCard'

const CARDS: PageHealthSummary[] = [
    {
        key: 'search',
        title: 'Search visibility',
        status: 'strong',
        value: '35%',
        detail: 'from Google, site average 30%',
        headline: '35% of visitors come from Google search, against 30% site-wide.',
        reasons: [
            '35% of visitors come from Google search, against 30% site-wide.',
            'The average Google position is 3.1.',
        ],
    },
    {
        key: 'ai',
        title: 'AI visibility',
        status: 'needs_attention',
        value: '0%',
        detail: 'from AI assistants, site average 11%',
        headline: 'Read by 23 AI crawlers but no AI assistant sent visitors.',
        reasons: ['Read by 23 AI crawlers but no AI assistant sent visitors.'],
    },
    {
        key: 'engagement',
        title: 'Engagement',
        status: 'fair',
        value: '24s',
        detail: 'for 90% of visits · 41% bounce',
        headline: '90% of visitors spend up to 24s on this page.',
        reasons: ['90% of visitors spend up to 24s on this page.'],
    },
    {
        key: 'search',
        title: 'Search visibility',
        status: 'not_found',
        value: '0%',
        detail: 'from Google, site average 31%',
        headline: 'No visitors from Google search',
        reasons: ["None of this page's 420 visitors arrived from Google search."],
    },
    {
        key: 'ai',
        title: 'AI visibility',
        status: 'not_set_up',
        value: null,
        detail: null,
        headline: 'AI crawlers are not measured yet',
        reasons: ['Forward your server logs to see which AI crawlers read this page.'],
    },
    {
        key: 'engagement',
        title: 'Engagement',
        status: 'no_data',
        value: null,
        detail: null,
        headline: 'Not enough visitors yet',
        reasons: ['This page had 12 visitors in this period. Health needs at least 30.'],
    },
    {
        key: 'search',
        title: 'Search visibility',
        status: 'loading',
        headline: 'Checking this page',
        reasons: [],
        value: null,
        detail: null,
    },
]

function AllStatuses(): JSX.Element {
    return (
        <div className="grid grid-cols-3 max-w-4xl border rounded-lg bg-surface-primary overflow-hidden divide-x divide-y">
            {CARDS.map((card) => (
                <PageHealthCard key={`${card.key}-${card.status}`} card={card} onClick={() => {}} onHover={() => {}} />
            ))}
        </div>
    )
}

const meta: Meta<typeof AllStatuses> = {
    title: 'Scenes-App/Web Analytics/Page reports/Page health card',
    component: AllStatuses,
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

export const Statuses: StoryObj<typeof AllStatuses> = {}
