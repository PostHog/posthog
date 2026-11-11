import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { newTransactionalPushLogic } from './push/newTransactionalPushLogic'

export function TransactionalNewButtons(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const showPush = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_PUSH_API')
    const { openModal: openNewPushModal } = useActions(newTransactionalPushLogic)

    return (
        <div className="flex items-center gap-2">
            {showPush ? (
                <AccessControlAction
                    resourceType={AccessControlResourceType.Workflow}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    {todayRailNav ? (
                        <Button data-attr="new-transactional-push" onClick={openNewPushModal} variant="outline">
                            New push notification
                        </Button>
                    ) : (
                        <LemonButton
                            data-attr="new-transactional-push"
                            onClick={openNewPushModal}
                            type="secondary"
                            size="small"
                        >
                            New push notification
                        </LemonButton>
                    )}
                </AccessControlAction>
            ) : null}
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
        </div>
    )
}
