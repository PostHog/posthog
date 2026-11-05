import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { TransactionalEmailActivity } from './TransactionalEmailActivity'
import { TransactionalEmailDeliveryProgress } from './TransactionalEmailDeliveryProgress'
import { TransactionalEmailDetails } from './TransactionalEmailDetails'
import {
    TransactionalEmailLogEntryLogicProps,
    transactionalEmailLogEntryLogic,
} from './transactionalEmailLogEntryLogic'
import { TransactionalEmailPersonCard } from './TransactionalEmailPersonCard'
import { TransactionalEmailRendered } from './TransactionalEmailRendered'

export const scene: SceneExport<TransactionalEmailLogEntryLogicProps> = {
    component: TransactionalEmailLogEntryScene,
    logic: transactionalEmailLogEntryLogic,
    paramsToProps: ({ params: { id } }): TransactionalEmailLogEntryLogicProps => ({ messageId: id }),
    productKey: ProductKey.WORKFLOWS,
}

export function TransactionalEmailLogEntryScene(): JSX.Element {
    const showTransactional = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')
    // The scene binds the logic to the message ID in the URL.
    const { email, emailLoading, emailFailed } = useValues(transactionalEmailLogEntryLogic)
    const { loadEmail } = useActions(transactionalEmailLogEntryLogic)

    if (!showTransactional) {
        return <NotFound object="page" />
    }
    if (emailFailed && !emailLoading) {
        return (
            <SceneContent>
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadEmail(),
                        'data-attr': 'transactional-email-log-entry-retry',
                    }}
                >
                    This email couldn't load. Check your connection and try again.
                </LemonBanner>
            </SceneContent>
        )
    }
    if (email === null && !emailLoading) {
        return (
            <NotFound
                object="email"
                caption="No send of this project has this message ID, or it is older than 30 days."
            />
        )
    }

    return (
        <SceneContent>
            <div className="ph-no-capture contents">
                <SceneTitleSection
                    name={email?.recipient || 'Email'}
                    description={email ? email.subject || email.template_name || null : null}
                    resourceType={{ type: 'transactional' }}
                    isLoading={!email}
                    actions={
                        email?.template_id ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.transactionalTemplate(email.template_id)}
                                data-attr="transactional-email-log-entry-open-template"
                            >
                                Open email
                            </LemonButton>
                        ) : undefined
                    }
                />
            </div>
            {!email ? (
                <div className="flex flex-col gap-4">
                    <LemonSkeleton className="h-20" />
                    <LemonSkeleton className="h-100" />
                </div>
            ) : (
                <div className="@container flex flex-col gap-4">
                    <TransactionalEmailDeliveryProgress email={email} />
                    <div className="flex flex-col @3xl:flex-row gap-4 items-start">
                        <div className="w-full @3xl:flex-1 min-w-0 flex flex-col gap-4 order-last @3xl:order-none">
                            {/* A send that never went out kept no copy, so nothing links it to a person. */}
                            {email.action_id && <TransactionalEmailActivity email={email} />}
                            <TransactionalEmailRendered email={email} />
                        </div>
                        <div className="w-full @3xl:w-80 shrink-0 flex flex-col gap-4">
                            {email.distinct_id && <TransactionalEmailPersonCard distinctId={email.distinct_id} />}
                            <TransactionalEmailDetails email={email} />
                        </div>
                    </div>
                </div>
            )}
        </SceneContent>
    )
}
