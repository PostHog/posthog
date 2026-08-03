import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { SecureConnectionApi } from './generated/api.schemas'
import { secureConnectionsLogic } from './secureConnectionsLogic'

export const scene: SceneExport = {
    component: SecureConnectionsScene,
    logic: secureConnectionsLogic,
}

function connectionStateLabel(connectionState: string): string {
    if (connectionState === 'connected') {
        return 'Connected'
    }
    if (connectionState === 'waiting') {
        return 'Waiting for proxy'
    }
    return 'Not configured'
}

function SecureConnectionsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        cdpApprovals,
        cdpApprovalsLoading,
        connectionStatus,
        connectionStatusLoading,
        enrollment,
        enrollmentLoading,
        testResult,
        testResultLoading,
    } = useValues(secureConnectionsLogic)
    const { createEnrollment, loadConnectionStatus, setCdpApproval, testConnection } =
        useActions(secureConnectionsLogic)

    const isLocalDevelopment = !!window.POSTHOG_APP_CONTEXT?.preflight?.is_debug

    if (!isLocalDevelopment && !featureFlags[FEATURE_FLAGS.SECURE_CONNECTIONS]) {
        return <NotFound object="page" />
    }

    const connectionState = connectionStatus?.connection_state ?? 'not_configured'
    const helmCommand = enrollment
        ? `helm upgrade --install posthog-secure-connection oci://ghcr.io/posthog/charts/burrow-proxy \\
  --set controlUrl=${enrollment.control_url} \\
  --set auth.key=${enrollment.enrollment_key} \\
  --set advertise.enabled=true \\
  --set advertise.tenantId=${enrollment.tenant_id} \\
  --set advertise.token=${enrollment.advertisement_token} \\
  --values connections.yaml`
        : ''
    const unavailableApprovedConnectionIds = Object.keys(cdpApprovals.cdp_approved_connections).filter(
        (connectionId) => !connectionStatus?.connections.some((connection) => connection.id === connectionId)
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Secure connections"
                description="Connect PostHog to services that are only available on your private network."
                resourceType={{ type: 'secure_connections' }}
            />

            <LemonBanner type="warning">
                Secure connections is in alpha. It is experimental and currently available for internal testing only.
            </LemonBanner>

            <SceneSection title="Connection status" titleSize="sm">
                <LemonCard className="p-4">
                    {connectionStatusLoading && !connectionStatus ? (
                        <LemonSkeleton className="h-8" />
                    ) : (
                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <LemonTag type={connectionState === 'connected' ? 'success' : 'muted'}>
                                    {connectionStateLabel(connectionState)}
                                </LemonTag>
                                <p className="mb-0 mt-2 text-secondary">
                                    {connectionState === 'connected'
                                        ? 'PostHog can see services advertised by your connection proxy.'
                                        : 'Set up the connection proxy to make private services available to PostHog.'}
                                </p>
                            </div>
                            <div className="flex gap-2">
                                <LemonButton
                                    type="secondary"
                                    onClick={() => loadConnectionStatus()}
                                    loading={connectionStatusLoading}
                                >
                                    Refresh
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    onClick={() => testConnection()}
                                    loading={testResultLoading}
                                >
                                    Test connection
                                </LemonButton>
                            </div>
                        </div>
                    )}
                    {testResult && (
                        <LemonBanner className="mt-4" type={testResult.success ? 'success' : 'warning'}>
                            {testResult.detail}
                        </LemonBanner>
                    )}
                </LemonCard>
            </SceneSection>

            {connectionStatus?.connections.length ? (
                <SceneSection title="Available services" titleSize="sm">
                    <LemonTable<SecureConnectionApi>
                        dataSource={connectionStatus.connections}
                        columns={[
                            { title: 'Name', dataIndex: 'name' },
                            { title: 'Type', dataIndex: 'connection_type' },
                            {
                                title: 'Status',
                                dataIndex: 'connection_status',
                                render: (value) => <LemonTag type="success">{value}</LemonTag>,
                            },
                            {
                                title: 'Magic hostname',
                                render: (_, connection) => <code>{connection.id}.secure-connections.internal</code>,
                            },
                            {
                                title: 'CDP access',
                                render: (_, connection) => {
                                    const approved = !!cdpApprovals.cdp_approved_connections[connection.id]
                                    const compatible = connection.selector_kind === 'hostname'
                                    return (
                                        <LemonButton
                                            size="small"
                                            type={approved ? 'secondary' : 'primary'}
                                            status={approved ? 'danger' : 'default'}
                                            loading={cdpApprovalsLoading}
                                            disabledReason={
                                                compatible ? undefined : 'CDP currently supports HTTP services only.'
                                            }
                                            onClick={() =>
                                                setCdpApproval({ connectionId: connection.id, approved: !approved })
                                            }
                                        >
                                            {approved
                                                ? 'Revoke CDP access'
                                                : compatible
                                                  ? 'Allow CDP access'
                                                  : 'Not compatible'}
                                        </LemonButton>
                                    )
                                },
                            },
                        ]}
                    />
                </SceneSection>
            ) : null}

            {unavailableApprovedConnectionIds.length ? (
                <SceneSection title="Unavailable CDP approvals" titleSize="sm">
                    <LemonBanner type="warning">
                        <p>
                            These approved services are no longer being advertised. CDP cannot use them, but their
                            approval remains until an admin revokes it.
                        </p>
                        <div className="flex flex-wrap gap-2 mt-2">
                            {unavailableApprovedConnectionIds.map((connectionId) => (
                                <LemonButton
                                    key={connectionId}
                                    size="small"
                                    type="secondary"
                                    status="danger"
                                    loading={cdpApprovalsLoading}
                                    onClick={() => setCdpApproval({ connectionId, approved: false })}
                                >
                                    Revoke {connectionId}
                                </LemonButton>
                            ))}
                        </div>
                    </LemonBanner>
                </SceneSection>
            ) : null}

            <SceneSection title="Using Secure connections from CDP" titleSize="sm">
                <div className="space-y-3 max-w-3xl">
                    <p>
                        Project admins must explicitly allow each advertised service before a CDP destination can use
                        it. Access is denied by default and can be revoked here at any time.
                    </p>
                    <p>
                        In destination code, replace the private hostname with the service's magic hostname shown above.
                        PostHog recognizes it, checks this project's CDP approval, and opens a short-lived,
                        authenticated tunnel through the connection worker. Existing request headers and credentials are
                        still used to authenticate to the private service.
                    </p>
                    <CodeSnippet
                        language={Language.JavaScript}
                    >{`fetch('http://<connection-id>.secure-connections.internal/path', {
  method: 'POST',
  headers: { 'Authorization': 'Bearer <service-api-key>' },
  body: JSON.stringify({ event: 'example' })
})`}</CodeSnippet>
                    <LemonBanner type="info">
                        A Secure connection only grants network reachability. It does not give the destination access to
                        the private service's application credentials.
                    </LemonBanner>
                </div>
            </SceneSection>

            <SceneSection title="Set up a connection proxy" titleSize="sm">
                <div className="space-y-4 max-w-3xl">
                    <p>
                        Generate an enrollment key, define the services you want PostHog to reach in{' '}
                        <code>connections.yaml</code>, then deploy the proxy in your network.
                    </p>
                    <LemonButton type="primary" onClick={() => createEnrollment()} loading={enrollmentLoading}>
                        {connectionState === 'not_configured' ? 'Generate enrollment key' : 'Generate a new key'}
                    </LemonButton>
                    {enrollment && (
                        <LemonBanner type="warning">
                            This key is shown once. Copy the command now and keep it in a secure place.
                        </LemonBanner>
                    )}
                    {enrollment && <CodeSnippet language={Language.Bash}>{helmCommand}</CodeSnippet>}
                    <div>
                        <h3>Example service configuration</h3>
                        <CodeSnippet language={Language.YAML}>{`connections:
  - name: internal-api
    selectorKind: hostname
    selector: internal-api.local
    target: internal-api.default.svc.cluster.local:8080`}</CodeSnippet>
                    </div>
                </div>
            </SceneSection>
        </SceneContent>
    )
}
