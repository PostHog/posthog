import { Meta, StoryFn } from '@storybook/react'

import { TransactionalEmailMetricTile } from './TransactionalEmailMetricTile'

const meta: Meta<typeof TransactionalEmailMetricTile> = {
    title: 'Scenes-App/Transactional/Email metric tile',
    component: TransactionalEmailMetricTile,
    parameters: { mockDate: '2026-06-15', testOptions: { snapshotBrowsers: [] } },
}
export default meta

const LABELS = ['2026-06-10', '2026-06-11', '2026-06-12', '2026-06-13', '2026-06-14']

export const RateThatRose: StoryFn = () => (
    <div className="w-72">
        <TransactionalEmailMetricTile
            tile={{
                key: 'bounced',
                title: 'Bounced',
                format: 'rate',
                value: 2.4,
                points: [1, 1.2, 8, 1.1, 1],
                count: 24,
                baseLabel: 'sent',
                bases: [200, 200, 200, 200, 200],
                counts: [2, 2, 16, 2, 2],
                change: 1.2,
                goodDirection: 'down',
            }}
            labels={LABELS}
            interval="day"
            timezone="UTC"
            color="var(--danger)"
            caption="24 of sent"
        />
    </div>
)
