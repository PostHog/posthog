import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { AdvertisementCard } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'
import { getProductPushDisplay } from 'lib/components/NavPanelAdvertisement/navPanelProductPushDisplay'

import { ProductKey } from '~/queries/schema/schema-general'

import { FIRST_WORKFLOW_CARD_DISMISS_KEY, firstWorkflowCardLogic } from './firstWorkflowCardLogic'

const MIDDLE_MOUSE_BUTTON = 1

export function FirstWorkflowCard(): JSX.Element {
    const { firstWorkflowUrl } = useValues(firstWorkflowCardLogic)
    const { reportShown, reportClicked, reportDismissed } = useActions(firstWorkflowCardLogic)

    useEffect(() => {
        reportShown()
    }, [reportShown])

    const card = (
        <BindLogic logic={navPanelAdvertisementLogic} props={{ dismissKey: FIRST_WORKFLOW_CARD_DISMISS_KEY }}>
            <AdvertisementCard
                title="Create your first workflow"
                text="Start from your most-used event, then post to Slack, start an AI task, or send an email each time it happens."
                hero={getProductPushDisplay(ProductKey.WORKFLOWS)}
                onClose={() => reportDismissed()}
            />
        </BindLogic>
    )

    if (!firstWorkflowUrl) {
        return (
            <div className="w-full cursor-progress" aria-busy="true">
                {card}
            </div>
        )
    }

    return (
        <div className="w-full">
            <Link
                to={firstWorkflowUrl}
                className="text-primary"
                data-attr="nav-panel-first-workflow-card"
                onClick={() => reportClicked()}
                onAuxClick={(event) => {
                    if (event.button === MIDDLE_MOUSE_BUTTON) {
                        reportClicked()
                    }
                }}
            >
                {card}
            </Link>
        </div>
    )
}
