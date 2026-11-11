import { useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EmailSuspensionBanner } from '../EmailSuspensionBanner'
import { MessagingTabActions } from '../MessagingTabActions'
import { TransactionalRoute, transactionalRouteFor } from './transactionalRoute'
import { TransactionalTabs } from './TransactionalTabs'
import { TransactionalEmailWizard } from './wizard/TransactionalEmailWizard'

export const scene: SceneExport = {
    component: TransactionalScene,
    productKey: ProductKey.WORKFLOWS,
}

export function TransactionalScene(): JSX.Element {
    const { location } = useValues(router)
    const showTransactional = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
    const showWebhooks = useFeatureFlag('WORKFLOWS_EMAIL_DELIVERY_WEBHOOKS')
    // Leaving for another scene changes the URL before that scene has loaded, so this one keeps showing its last view.
    const route = transactionalRouteFor(location.pathname)
    const lastRoute = useRef<TransactionalRoute>(route ?? 'transactional')
    lastRoute.current = route ?? lastRoute.current
    const currentTab = lastRoute.current === 'webhooks' && !showWebhooks ? 'transactional' : lastRoute.current

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
                actions={<TransactionalSceneActions tab={currentTab} />}
            />
            <EmailSuspensionBanner />
            <TransactionalTabs currentTab={currentTab} showWebhooks={showWebhooks} />
        </SceneContent>
    )
}

function TransactionalSceneActions({ tab }: { tab: Exclude<TransactionalRoute, 'new'> }): JSX.Element | null {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (tab === 'webhooks') {
        return null
    }
    if (tab !== 'transactional' && tab !== 'log' && tab !== 'metrics') {
        return <MessagingTabActions tab={tab} channelsUrl={urls.transactional('channels')} />
    }
    return (
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
    )
}
