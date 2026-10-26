import { useActions, useValues } from 'kea'

import { IconShare } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { emailDomainLogic } from '../emailDomainLogic'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'

export function ShareRecordsMenu(): JSX.Element | null {
    const { records } = useValues(emailDomainStatusLogic)
    const { shareRecords } = useActions(emailDomainLogic)
    if (!records.length) {
        return null
    }
    return (
        <LemonMenu
            items={[
                {
                    label: 'Copy link for a teammate in PostHog',
                    onClick: () => shareRecords('link'),
                    'data-attr': 'email-domain-share-records-link',
                },
                {
                    label: 'Copy settings as text',
                    onClick: () => shareRecords('text'),
                    'data-attr': 'email-domain-share-records-text',
                },
            ]}
        >
            <LemonButton type="tertiary" icon={<IconShare />} data-attr="email-domain-share-records">
                Send to whoever manages DNS
            </LemonButton>
        </LemonMenu>
    )
}
