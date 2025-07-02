import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import api from 'lib/api'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconSlack } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { slackSetupModalLogic, SlackSetupModalLogicProps } from './slackSetupModalLogic'

// Modified version of https://app.slack.com/app-settings/TSS5W8YQZ/A03KWE2FJJ2/app-manifest to match current instance
const getSlackAppManifest = (): any => ({
    display_information: {
        name: 'PostHog',
        description: 'Product Insights right where you need them',
        background_color: '#f54e00',
    },
    features: {
        app_home: {
            home_tab_enabled: false,
            messages_tab_enabled: false,
            messages_tab_read_only_enabled: true,
        },
        bot_user: {
            display_name: 'PostHog',
            always_online: false,
        },
        unfurl_domains: [window.location.hostname],
    },
    oauth_config: {
        redirect_urls: [`${window.location.origin.replace('http://', 'https://')}/integrations/slack/callback`],
        scopes: {
            bot: ['channels:read', 'chat:write', 'groups:read', 'links:read', 'links:write'],
        },
    },
    settings: {
        event_subscriptions: {
            request_url: `${window.location.origin.replace('http://', 'https://')}/api/integrations/slack/events`,
            bot_events: ['link_shared'],
        },
        org_deploy_enabled: false,
        socket_mode_enabled: false,
        token_rotation_enabled: false,
    },
})

export const SlackSetupModal = (props: SlackSetupModalLogicProps): JSX.Element => {
    const logic = slackSetupModalLogic(props)
    const { slackAvailable, user } = useValues(logic)
    const [showSlackInstructions, setShowSlackInstructions] = useState(false)

    return (
        <LemonModal
            title={
                <div className="flex items-center gap-2">
                    <IconSlack />
                    <span>Configure Slack integration</span>
                </div>
            }
            onClose={() => props.onComplete()}
            footer={
                <div className="flex justify-end">
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Close
                    </LemonButton>
                </div>
            }
        >
            <div className="max-w-[400px]">
                {slackAvailable ? (
                    <Link to={api.integrations.authorizeUrl({ kind: 'slack' })} disableClientSideRouting>
                        <img
                            alt="Connect to Slack workspace"
                            height="40"
                            width="139"
                            src="https://platform.slack-edge.com/img/add_to_slack.png"
                            srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                        />
                    </Link>
                ) : user?.is_staff ? (
                    !showSlackInstructions ? (
                        <>
                            <LemonButton type="secondary" onClick={() => setShowSlackInstructions(true)}>
                                Show Instructions
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            <h5>To get started</h5>
                            <p>
                                <ol>
                                    <li>Copy the below Slack App Template</li>
                                    <li>
                                        Go to{' '}
                                        <Link to="https://api.slack.com/apps" target="_blank">
                                            Slack Apps
                                        </Link>
                                    </li>
                                    <li>Create an App using the provided template</li>
                                    <li>
                                        <Link to={urls.instanceSettings()}>Go to Instance Settings</Link> and update the{' '}
                                        <code>"SLACK_"</code> properties using the values from the{' '}
                                        <b>App Credentials</b> section of your Slack Apps
                                    </li>
                                </ol>

                                <CodeSnippet language={Language.JSON}>
                                    {JSON.stringify(getSlackAppManifest(), null, 2)}
                                </CodeSnippet>
                            </p>
                        </>
                    )
                ) : (
                    <p className="text-secondary">
                        This PostHog instance is not configured for Slack. Please contact the instance owner to
                        configure it.
                    </p>
                )}
            </div>
        </LemonModal>
    )
}
