import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { EditKeyModal } from 'scenes/settings/user/PersonalAPIKeys'

import { metricsPrometheusConnectLogic } from './metricsPrometheusConnectLogic'

export function MetricsPrometheusConnectModal(): JSX.Element {
    const { isConnectModalOpen, serverUrl, provisioningSnippet, connectionTest, connectionTestLoading } =
        useValues(metricsPrometheusConnectLogic)
    const { closeConnectModal, snippetCopied, createApiKey, testConnection } = useActions(metricsPrometheusConnectLogic)

    return (
        <>
            <LemonModal
                isOpen={isConnectModalOpen}
                onClose={closeConnectModal}
                title="Connect Grafana"
                description="Add PostHog as a Prometheus data source and query your metrics with PromQL."
                width={640}
                footer={
                    <LemonButton type="secondary" onClick={closeConnectModal}>
                        Close
                    </LemonButton>
                }
            >
                <div className="flex flex-col gap-4">
                    <LemonField.Pure
                        label="Prometheus server URL"
                        help="In Grafana, add a Prometheus data source and paste this URL. Other Prometheus clients use the same URL."
                    >
                        <CodeSnippet
                            language={Language.Text}
                            thing="server URL"
                            onCopy={() => snippetCopied('server_url')}
                        >
                            {serverUrl}
                        </CodeSnippet>
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Authentication"
                        help="In the data source settings, add an HTTP header named Authorization with the value Bearer, a space, and your personal API key. The key needs the metrics read scope."
                    >
                        <div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={createApiKey}
                                data-attr="metrics-prometheus-create-api-key"
                            >
                                Create personal API key
                            </LemonButton>
                        </div>
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Test the connection"
                        help="Run the test query that Grafana runs when you save the data source."
                    >
                        <div className="flex flex-col gap-2">
                            <div>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={testConnection}
                                    loading={connectionTestLoading}
                                    data-attr="metrics-prometheus-test-connection"
                                >
                                    Test connection
                                </LemonButton>
                            </div>
                            {connectionTest?.status === 'success' ? (
                                <LemonBanner type="success">
                                    PostHog answered the test query. Grafana can connect with this URL.
                                </LemonBanner>
                            ) : connectionTest?.status === 'error' ? (
                                <LemonBanner type="error">
                                    <p className="m-0">
                                        The test query failed. Try again later, or share feedback if it keeps failing.
                                    </p>
                                    <p className="m-0 font-mono text-xs">{connectionTest.message}</p>
                                </LemonBanner>
                            ) : null}
                        </div>
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Provision as code"
                        help="To manage Grafana as code, add this data source to a provisioning file. Set POSTHOG_PERSONAL_API_KEY in the environment of Grafana."
                    >
                        <CodeSnippet
                            language={Language.YAML}
                            thing="provisioning file"
                            onCopy={() => snippetCopied('provisioning')}
                        >
                            {provisioningSnippet}
                        </CodeSnippet>
                    </LemonField.Pure>
                </div>
            </LemonModal>
            <EditKeyModal zIndex="1162" />
        </>
    )
}
