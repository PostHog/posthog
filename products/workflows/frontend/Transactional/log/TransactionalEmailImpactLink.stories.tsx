import { Meta, StoryFn } from '@storybook/react'

import { TransactionalEmailImpactLink } from './TransactionalEmailImpactLink'

const meta: Meta<typeof TransactionalEmailImpactLink> = {
    title: 'Scenes-App/Transactional/Email impact link',
    component: TransactionalEmailImpactLink,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const AcrossAllSends: StoryFn = () => (
    <div className="w-96">
        <TransactionalEmailImpactLink impactUrl="/transactional/templates/tpl-1?tab=impact" />
    </div>
)
