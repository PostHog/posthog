import { LemonButton, LemonDialog, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { HogFunctionTestPlaceholder } from 'scenes/hog-functions/configuration/HogFunctionTest'
import { urls } from 'scenes/urls'

import { HogFunctionMessageTesting } from './HogFunctionMessageTesting'

export function HogFunctionBroadcastDelivery(): JSX.Element {
    const { logicProps, configurationChanged, personsCount, personsCountLoading, personsListQuery, broadcastLoading } =
        useValues(hogFunctionConfigurationLogic)
    const { sendBroadcast } = useActions(hogFunctionConfigurationLogic(logicProps))

    const { id } = logicProps

    return (
        <>
            <HogFunctionMessageTesting />
            <HogFunctionTestPlaceholder
                title="Send broadcast"
                description={
                    id && id !== 'new' ? (
                        <div className="mt-2 space-y-2">
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Confirm Broadcast',
                                        description: (
                                            <>
                                                <p>
                                                    Emails will be sent to{' '}
                                                    <Link
                                                        to={
                                                            combineUrl(urls.activity(), {}, { q: personsListQuery }).url
                                                        }
                                                        target="_blank"
                                                    >
                                                        {personsCount} person
                                                        <span>{personsCount === 1 ? '' : 's'}</span> matching the
                                                        filters.
                                                    </Link>
                                                </p>
                                                <p>Are you sure you want to send this broadcast?</p>
                                            </>
                                        ),
                                        primaryButton: {
                                            children: 'Send',
                                            onClick: sendBroadcast,
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }}
                                loading={personsCountLoading || broadcastLoading}
                                disabledReason={
                                    configurationChanged ? 'Save or clear changes to send broadcast' : undefined
                                }
                            >
                                Send to {personsCount} email
                                <span>{personsCount === 1 ? '' : 's'}</span>
                            </LemonButton>
                            <div>
                                <strong>Please note:</strong> Clicking the button above will synchronously send to all
                                the e-mails. While this is fine for testing with small lists, please don't use this for
                                production use cases yet.
                            </div>
                        </div>
                    ) : (
                        <div className="mt-2 space-y-2">
                            <LemonButton type="primary" disabledReason="Must save to send broadcast">
                                Send to {personsCount} email
                                <span>{personsCount === 1 ? '' : 's'}</span>
                            </LemonButton>
                            <div>
                                Save your configuration to send a broadcast. Nothing will be sent until you manually
                                send the broadcast above.
                            </div>
                        </div>
                    )
                }
            />
        </>
    )
}
