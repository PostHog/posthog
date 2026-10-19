import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { AdvertisementCard } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'
import { getProductPushDisplay } from 'lib/components/NavPanelAdvertisement/navPanelProductPushDisplay'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FIRST_WORKFLOW_CARD_DISMISS_KEY, firstWorkflowCardLogic } from './firstWorkflowCardLogic'

const MIDDLE_MOUSE_BUTTON = 1

export function FirstWorkflowCard(): JSX.Element {
    const { reportShown, reportClicked, reportDismissed } = useActions(firstWorkflowCardLogic)

    useEffect(() => {
        reportShown()
    }, [reportShown])

    return (
        <div className="w-full">
            <Link
                to={urls.workflows()}
                className="text-primary"
                data-attr="nav-panel-first-workflow-card"
                onClick={() => reportClicked()}
                onAuxClick={(event) => {
                    if (event.button === MIDDLE_MOUSE_BUTTON) {
                        reportClicked()
                    }
                }}
            >
                <BindLogic logic={navPanelAdvertisementLogic} props={{ dismissKey: FIRST_WORKFLOW_CARD_DISMISS_KEY }}>
                    <AdvertisementCard
                        title="Create your first workflow"
                        text="Pick an event from your product, then post to Slack, start an AI task, or send an email each time it happens."
                        hero={getProductPushDisplay(ProductKey.WORKFLOWS)}
                        onClose={() => reportDismissed()}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}
