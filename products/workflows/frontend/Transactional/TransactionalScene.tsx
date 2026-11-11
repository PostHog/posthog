import { useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { EmailSuspensionBanner } from '../EmailSuspensionBanner'
import { MessagingTabActions } from '../MessagingTabActions'
import { NewTransactionalPushModal } from './push/NewTransactionalPushModal'
import { TransactionalNewButtons } from './TransactionalNewButtons'
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
    const showPush = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_PUSH_API')
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
            {showPush ? <NewTransactionalPushModal /> : null}
        </SceneContent>
    )
}

function TransactionalSceneActions({ tab }: { tab: Exclude<TransactionalRoute, 'new'> }): JSX.Element | null {
    if (tab === 'webhooks') {
        return null
    }
    if (tab !== 'transactional' && tab !== 'log' && tab !== 'metrics') {
        return <MessagingTabActions tab={tab} channelsUrl={urls.transactional('channels')} />
    }
    return <TransactionalNewButtons />
}
