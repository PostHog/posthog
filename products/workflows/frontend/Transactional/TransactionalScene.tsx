import { useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EmailSuspensionBanner } from '../EmailSuspensionBanner'
import { MessagingSetup } from '../MessagingSetup'
import { MessagingTabActions } from '../MessagingTabActions'
import { MESSAGING_TAB_CONTENT, isMessagingSetupTab } from '../messagingTabs'
import { TransactionalEmailLog } from './log/TransactionalEmailLog'
import { TransactionalEmailMetrics } from './metrics/TransactionalEmailMetrics'
import { TransactionalEmailsTable } from './TransactionalEmailsTable'
import { TransactionalRoute, TransactionalTab, transactionalRouteFor } from './transactionalRoute'
import { TransactionalWebhooks } from './webhooks/TransactionalWebhooks'
import { TransactionalEmailWizard } from './wizard/TransactionalEmailWizard'

export const scene: SceneExport = {
    component: TransactionalScene,
    productKey: ProductKey.WORKFLOWS,
}

export function TransactionalScene(): JSX.Element {
    const { location } = useValues(router)
    const showTransactional = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const showWebhooks = useFeatureFlag('WORKFLOWS_EMAIL_DELIVERY_WEBHOOKS')
    // Leaving for another scene changes the URL before that scene has loaded, so this one keeps showing its last view.
    const route = transactionalRouteFor(location.pathname)
    const lastRoute = useRef<TransactionalRoute>(route ?? 'transactional')
    lastRoute.current = route ?? lastRoute.current
    const currentTab = lastRoute.current === 'webhooks' && !showWebhooks ? 'transactional' : lastRoute.current
    const isTransactionalTab = currentTab === 'transactional' || currentTab === 'log' || currentTab === 'metrics'

    if (!showTransactional) {
        return <NotFound object="page" />
    }

    if (currentTab === 'new') {
        return <TransactionalEmailWizard />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Transactional"
                description="Send emails from your code with one API call"
                resourceType={{ type: 'transactional' }}
                actions={
                    currentTab === 'webhooks' ? undefined : isTransactionalTab ? (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {todayRailNav ? (
                                <Button
                                    data-attr="new-transactional-email"
                                    onClick={() => router.actions.push(urls.transactionalNew())}
                                    variant="primary"
                                >
                                    New transactional email
                                </Button>
                            ) : (
                                <LemonButton
                                    data-attr="new-transactional-email"
                                    to={urls.transactionalNew()}
                                    type="primary"
                                    size="small"
                                >
                                    New transactional email
                                </LemonButton>
                            )}
                        </AccessControlAction>
                    ) : (
                        <MessagingTabActions tab={currentTab} channelsUrl={urls.transactional('channels')} />
                    )
                }
            />
            <EmailSuspensionBanner />
            <LemonTabs<TransactionalTab | 'library' | 'webhooks' | 'messaging-setup'>
                activeKey={
                    isTransactionalTab || currentTab === 'library' || currentTab === 'webhooks'
                        ? currentTab
                        : 'messaging-setup'
                }
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
                        link: urls.transactional('channels'),
                        content: (
                            <MessagingSetup
                                tab={isMessagingSetupTab(currentTab) ? currentTab : 'channels'}
                                linkFor={(tab) => urls.transactional(tab)}
                            />
                        ),
                    },
                ]}
                sceneInset
            />
        </SceneContent>
    )
}
