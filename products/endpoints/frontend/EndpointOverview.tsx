import { useValues } from 'kea'

import { LemonButton, LemonLabel, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { endpointLogic } from './endpointLogic'

interface EndpointOverviewProps {
    tabId: string
}

export function EndpointOverview({ tabId }: EndpointOverviewProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    const hasParameters = endpoint.parameters && Object.keys(endpoint.parameters).length > 0

    return (
        <div className="grid gap-2 overflow-hidden grid-cols-1 min-[1200px]:grid-cols-[1fr_26rem]">
            <div className="flex flex-col gap-0 overflow-hidden">
                <div className="inline-flex deprecated-space-x-8">
                    <div className="flex flex-col">
                        <LemonLabel>Status</LemonLabel>
                        <LemonTag type={endpoint.is_active ? 'success' : 'danger'}>
                            <b className="uppercase">{endpoint.is_active ? 'Active' : 'Inactive'}</b>
                        </LemonTag>
                    </div>
                    <div className="flex flex-col">
                        <LemonLabel info="A version is incremented when the underlying query changes. You can execute old versions of the Endpoint by setting the `version` param on the request body.">
                            Current version
                        </LemonLabel>
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold">v{endpoint.current_version}</span>
                            <span className="text-xs text-muted">({endpoint.versions_count} total)</span>
                        </div>
                    </div>
                    <div className="flex flex-col">
                        <LemonLabel>Endpoint URL</LemonLabel>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            onClick={() => {
                                navigator.clipboard.writeText(endpoint.endpoint_path)
                                lemonToast.success('Endpoint URL copied to clipboard')
                            }}
                            className="font-mono text-xs"
                        >
                            {endpoint.endpoint_path}
                        </LemonButton>
                    </div>
                </div>

                {hasParameters && (
                    <div className="flex flex-col mt-4">
                        <LemonLabel>Variables</LemonLabel>
                        <div className="space-y-2 mt-1">
                            {Object.entries(endpoint.parameters).map(([key, value]) => (
                                <div key={key} className="flex items-start gap-2">
                                    <code className="text-xs bg-bg-light px-2 py-1 rounded">{key}</code>
                                    <span className="text-muted-alt">:</span>
                                    <code className="text-xs text-muted">{JSON.stringify(value)}</code>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            <div className="flex flex-col gap-4 overflow-hidden items-start min-[1200px]:items-end">
                <div className="flex flex-col overflow-hidden items-start min-[1200px]:items-end">
                    <div className="inline-flex deprecated-space-x-8">
                        <div className="flex flex-col">
                            <LemonLabel>Last executed</LemonLabel>
                            {endpoint.last_executed_at ? (
                                <TZLabel time={endpoint.last_executed_at} />
                            ) : (
                                <span className="text-muted">Never</span>
                            )}
                        </div>
                        <div className="flex flex-col">
                            <LemonLabel>Created by</LemonLabel>
                            {endpoint.created_by && <ProfilePicture user={endpoint.created_by} size="md" showName />}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
