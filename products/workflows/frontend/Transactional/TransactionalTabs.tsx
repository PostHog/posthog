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
import { PrototypeEmailsTable } from './sendFromCodePrototype/PrototypeEmailsTable'
import { useSendFromCodePrototype } from './sendFromCodePrototype/useSendFromCodePrototype'
import { VariantAfterDomainVerified } from './sendFromCodePrototype/VariantAfterDomainVerified'
import { VariantCodeFirstEmptyState } from './sendFromCodePrototype/VariantCodeFirstEmptyState'
import { VariantSendFromCodePage } from './sendFromCodePrototype/VariantSendFromCodePage'
import { TransactionalEmailsTable } from './TransactionalEmailsTable'
import { TransactionalRoute, TransactionalTab } from './transactionalRoute'
import { TransactionalWebhooks } from './webhooks/TransactionalWebhooks'

export function TransactionalTabs({
    currentTab,
    showWebhooks,
}: {
    currentTab: TransactionalRoute
    showWebhooks: boolean
}): JSX.Element {
    const smtpInterestLogic = comingSoonInterestLogic(useComingSoonInterestSurvey(SMTP_INTEREST_SURVEY))
    const { hasRecordedInterest } = useValues(smtpInterestLogic)
    const { registerInterest } = useActions(smtpInterestLogic)
    const isTransactionalTab = currentTab === 'transactional' || currentTab === 'log' || currentTab === 'metrics'
    // PROTOTYPE (ticket #320): variants swap the list tab's content, and A adds a "Send from code" tab.
    const prototype = useSendFromCodePrototype()
    const { variant, withParams } = prototype
    const showCodePage =
        variant === 'A' &&
        currentTab === 'transactional' &&
        (prototype.view === 'code' || (prototype.view === null && prototype.emails === 'none'))
    const listContent =
        variant === 'B' ? (
            <VariantCodeFirstEmptyState />
        ) : variant === 'C' ? (
            <VariantAfterDomainVerified />
        ) : variant && prototype.emails === 'some' ? (
            <PrototypeEmailsTable />
        ) : (
            <TransactionalEmailsTable />
        )

    return (
        <>
            <LemonTabs<TransactionalTab | 'library' | 'webhooks' | 'messaging-setup' | 'smtp' | 'send-from-code'>
                activeKey={
                    showCodePage
                        ? 'send-from-code'
                        : isTransactionalTab || currentTab === 'library' || currentTab === 'webhooks'
                          ? currentTab
                          : 'messaging-setup'
                }
                onChange={(key) => {
                    // No SMTP page exists yet, so this tab asks for interest and the current tab stays selected.
                    if (key === 'smtp') {
                        registerInterest()
                    }
                }}
                tabs={[
                    variant === 'A'
                        ? {
                              label: 'Send from code',
                              key: 'send-from-code',
                              link: withParams(urls.transactional(), { view: 'code' }),
                              content: <VariantSendFromCodePage />,
                          }
                        : null,
                    {
                        label: 'Transactional emails',
                        key: 'transactional',
                        link: withParams(urls.transactional(), { view: variant === 'A' ? 'list' : null }),
                        content: listContent,
                    },
                    {
                        label: 'Log',
                        key: 'log',
                        link: withParams(urls.transactionalLog()),
                        content: <TransactionalEmailLog />,
                    },
                    {
                        label: 'Metrics',
                        key: 'metrics',
                        link: withParams(urls.transactionalMetrics()),
                        content: <TransactionalEmailMetrics />,
                    },
                    {
                        label: 'Templates',
                        key: 'library',
                        link: withParams(urls.transactional('library')),
                        content: MESSAGING_TAB_CONTENT.library,
                    },
                    showWebhooks
                        ? {
                              label: 'Webhooks',
                              key: 'webhooks',
                              link: urls.transactional('webhooks'),
                              content: <TransactionalWebhooks />,
                          }
                        : null,
                    {
                        label: 'Messaging',
                        key: 'messaging-setup',
                        link: withParams(urls.transactional('channels')),
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
