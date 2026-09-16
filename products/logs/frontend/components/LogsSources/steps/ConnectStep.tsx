import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { logsSourcesLogic } from '../logsSourcesLogic'

export function ConnectStep(): JSX.Element {
    const { setup, setupLoading, setupLoadFailed, wizardSourceId } = useValues(logsSourcesLogic)
    const { loadSetup } = useActions(logsSourcesLogic)
    if (setupLoadFailed && wizardSourceId) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadSetup(wizardSourceId),
                    loading: setupLoading,
                    'data-attr': 'logs-source-retry-setup',
                }}
            >
                Couldn't load the setup values for this source. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (setupLoading || !setup) {
        return (
            <div className="flex items-center gap-2 text-secondary">
                <Spinner /> Preparing your endpoint
            </div>
        )
    }
    return (
        <div className="space-y-4">
            <p className="m-0 text-secondary">
                In the AWS console, create an Amazon Data Firehose stream. Set the source to Direct PUT and the
                destination to HTTP endpoint, then subscribe your CloudWatch log groups to the stream. Use the values
                below.
            </p>
            <LemonField.Pure label="HTTP endpoint URL">
                <CodeSnippet language={Language.Text} compact wrap>
                    {setup.endpoint_url}
                </CodeSnippet>
            </LemonField.Pure>
            <LemonField.Pure
                label="Access key"
                help="This is your project API key. Firehose sends it with every request so PostHog knows which project the logs belong to."
            >
                <CodeSnippet language={Language.Text} compact>
                    {setup.access_key}
                </CodeSnippet>
            </LemonField.Pure>
            <LemonField.Pure label="Stream settings">
                <ul className="m-0 pl-4 text-sm text-secondary">
                    <li>
                        Buffer size: {setup.buffering_size_mb} MB. Buffer interval: {setup.buffering_interval_seconds}{' '}
                        seconds.
                    </li>
                    <li>Content encoding: {setup.content_encoding}</li>
                    <li>Retry duration: {setup.retry_duration_seconds} seconds. S3 backup: failed data only.</li>
                </ul>
            </LemonField.Pure>
            <LemonButton
                type="secondary"
                to={setup.quick_create_url ?? undefined}
                targetBlank
                disabledReason={
                    setup.quick_create_url
                        ? undefined
                        : 'The CloudFormation template is not available on this instance. Enter the values above in the Firehose console.'
                }
                data-attr="logs-source-launch-stack"
            >
                Launch CloudFormation stack
            </LemonButton>
            <p className="m-0 text-xs text-secondary">
                The stack creates the Firehose stream, an S3 bucket for failed deliveries, the IAM roles, and one
                subscription filter in your AWS account. Nothing is created until you click Create stack in the AWS
                console.
            </p>
        </div>
    )
}
