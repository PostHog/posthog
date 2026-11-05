import { useValues } from 'kea'
import { router } from 'kea-router'

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
import {
    MESSAGING_NAV_TAB_KEYS,
    MESSAGING_TAB_CONTENT,
    MessagingNavTabKey,
    isMessagingSetupTab,
} from '../messagingTabs'
import { TransactionalEmailsTable } from './TransactionalEmailsTable'
import { TransactionalEmailWizard } from './wizard/TransactionalEmailWizard'

export const scene: SceneExport = {
    component: TransactionalScene,
    productKey: ProductKey.WORKFLOWS,
}

export function TransactionalScene(): JSX.Element {
    const { location } = useValues(router)
    const showTransactional = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    // The tab routes are literal paths, so the tab is the last path segment rather than a route param.
    const lastSegment = location.pathname.split('/').pop() ?? ''
    const currentTab: MessagingNavTabKey | 'transactional' = MESSAGING_NAV_TAB_KEYS.includes(
        lastSegment as MessagingNavTabKey
    )
        ? (lastSegment as MessagingNavTabKey)
        : 'transactional'

    if (!showTransactional) {
        return <NotFound object="page" />
    }

    if (lastSegment === 'new') {
        return <TransactionalEmailWizard />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Transactional"
                description="Send emails from your code with one API call"
                resourceType={{ type: 'transactional' }}
                actions={
                    currentTab === 'transactional' ? (
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
            <LemonTabs<'transactional' | 'library' | 'messaging-setup'>
                activeKey={currentTab === 'transactional' || currentTab === 'library' ? currentTab : 'messaging-setup'}
                tabs={[
                    {
                        label: 'Transactional emails',
                        key: 'transactional',
                        link: urls.transactional(),
                        content: <TransactionalEmailsTable />,
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
                ]}
                sceneInset
            />
        </SceneContent>
    )
}
