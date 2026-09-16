import { useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { logsSourcesLogic } from '../logsSourcesLogic'

export function ConnectStep(): JSX.Element {
    const { setup, setupLoading } = useValues(logsSourcesLogic)
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
                In the AWS console, create an Amazon Data Firehose stream with source Direct PUT and destination HTTP
                endpoint, then subscribe your CloudWatch log groups to it. Use these values.
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
                        Buffer size {setup.buffering_size_mb} MB, buffer interval {setup.buffering_interval_seconds}{' '}
                        seconds
                    </li>
                    <li>Content encoding {setup.content_encoding}</li>
                    <li>Retry duration {setup.retry_duration_seconds} seconds, back up failed data only to S3</li>
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
