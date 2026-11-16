import { useActions, useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

import { MessagingSetup } from '../MessagingSetup'
import { MESSAGING_TAB_CONTENT, isMessagingSetupTab } from '../messagingTabs'
import { comingSoonInterestLogic } from './comingSoon/comingSoonInterestLogic'
import { ComingSoonInterestTag } from './comingSoon/ComingSoonInterestTag'
import { SmtpInterestModal } from './comingSoon/SmtpInterestModal'
import { SMTP_INTEREST_SURVEY } from './comingSoon/smtpInterestSurvey'
import { useComingSoonInterestSurvey } from './comingSoon/useComingSoonInterestSurvey'
import { TransactionalEmailLog } from './log/TransactionalEmailLog'
import { TransactionalEmailMetrics } from './metrics/TransactionalEmailMetrics'
import { TransactionalEmailsTable } from './TransactionalEmailsTable'
import { TransactionalRoute, TransactionalTab } from './transactionalRoute'

export function TransactionalTabs({ currentTab }: { currentTab: TransactionalRoute }): JSX.Element {
    const smtpInterestLogic = comingSoonInterestLogic(useComingSoonInterestSurvey(SMTP_INTEREST_SURVEY))
    const { hasRecordedInterest } = useValues(smtpInterestLogic)
    const { registerInterest } = useActions(smtpInterestLogic)
    const isTransactionalTab = currentTab === 'transactional' || currentTab === 'log' || currentTab === 'metrics'

    return (
        <>
            <LemonTabs<TransactionalTab | 'library' | 'messaging-setup' | 'smtp'>
                activeKey={isTransactionalTab || currentTab === 'library' ? currentTab : 'messaging-setup'}
                onChange={(key) => {
                    // No SMTP page exists yet, so this tab asks for interest and the current tab stays selected.
                    if (key === 'smtp') {
                        registerInterest()
                    }
                }}
                tabs={[
                    {
                        label: 'Transactional emails',
                        key: 'transactional',
                        link: urls.transactional(),
                        content: <TransactionalEmailsTable />,
                    },
                    {
                        label: 'Log',
                        key: 'log',
                        link: urls.transactionalLog(),
                        content: <TransactionalEmailLog />,
                    },
                    {
                        label: 'Metrics',
                        key: 'metrics',
                        link: urls.transactionalMetrics(),
                        content: <TransactionalEmailMetrics />,
                    },
                    {
                        label: 'Templates',
                        key: 'library',
                        link: urls.transactional('library'),
                        content: MESSAGING_TAB_CONTENT.library,
                    },
                    {
                        label: 'Messaging',
                        key: 'messaging-setup',
                        link: urls.transactional('channels'),
                        content: (
                            <MessagingSetup
                                tab={isMessagingSetupTab(currentTab) ? currentTab : 'channels'}
                                linkFor={(tab) => urls.transactional(tab)}
                            />
                        ),
                    },
                    {
                        label: (
                            <>
                                SMTP
                                <ComingSoonInterestTag hasRecordedInterest={hasRecordedInterest} />
                            </>
                        ),
                        key: 'smtp',
                        tooltip: hasRecordedInterest
                            ? 'You told us you want SMTP. Click to add or change your note.'
                            : 'Coming soon: send email through PostHog from any app or tool that supports SMTP, with no code changes. Click to tell us you want this.',
                        'data-attr': 'transactional-smtp-coming-soon',
                    },
                ]}
                sceneInset
            />
            <SmtpInterestModal />
        </>
    )
}
