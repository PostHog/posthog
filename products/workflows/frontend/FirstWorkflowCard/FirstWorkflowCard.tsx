import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { AdvertisementCard } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'
import { getProductPushDisplay } from 'lib/components/NavPanelAdvertisement/navPanelProductPushDisplay'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FIRST_WORKFLOW_CARD_DISMISS_KEY, firstWorkflowCardLogic } from './firstWorkflowCardLogic'

export function FirstWorkflowCard(): JSX.Element {
    const { triggerEventLoading } = useValues(firstWorkflowCardLogic)
    const { openFirstWorkflow, reportShown, reportDismissed } = useActions(firstWorkflowCardLogic)

    useEffect(() => {
        reportShown()
    }, [reportShown])

    return (
        <div className="w-full">
            <Link
                to={urls.workflowNew()}
                className={triggerEventLoading ? 'cursor-progress text-primary opacity-70' : 'text-primary'}
                aria-busy={triggerEventLoading}
                data-attr="nav-panel-first-workflow-card"
                onClick={(event) => {
                    event.preventDefault()
                    if (!triggerEventLoading) {
                        openFirstWorkflow()
                    }
                }}
            >
                <BindLogic logic={navPanelAdvertisementLogic} props={{ dismissKey: FIRST_WORKFLOW_CARD_DISMISS_KEY }}>
                    <AdvertisementCard
                        title="Create your first workflow"
                        text="Start from your most-used event, then send an email or a Slack message each time it happens."
                        hero={getProductPushDisplay(ProductKey.WORKFLOWS)}
                        onClose={() => reportDismissed()}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}
