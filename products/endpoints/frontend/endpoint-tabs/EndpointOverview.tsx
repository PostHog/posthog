import { useValues } from 'kea'

import { LemonButton, LemonLabel, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { endpointLogic } from '../endpointLogic'
import { EndpointTab, endpointSceneLogic } from '../endpointSceneLogic'

interface EndpointOverviewProps {
    tabId: string
}

export function EndpointOverview({ tabId }: EndpointOverviewProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))
    const { viewingVersion } = useValues(endpointSceneLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    const isViewingOldVersion = viewingVersion && viewingVersion.version !== endpoint.current_version
    const versionUrl = isViewingOldVersion ? `${endpoint.endpoint_path}?version=${viewingVersion.version}` : null

    return (
        <div className="flex flex-col gap-4">
            {/* Row 1: Endpoint info (always shown) */}
            <div className="grid gap-2 overflow-hidden grid-cols-1 min-[1200px]:grid-cols-[1fr_26rem]">
                <div className="inline-flex deprecated-space-x-8">
                    <div className="flex flex-col w-28">
                        <LemonLabel>Endpoint status</LemonLabel>
                        <LemonTag type={endpoint.is_active ? 'success' : 'danger'} className="w-fit">
                            <b>{endpoint.is_active ? 'Active' : 'Inactive'}</b>
                        </LemonTag>
                    </div>
                    <div className="flex flex-col w-34">
                        <LemonLabel
                            info={
                                <>
                                    Versions auto-increment when the query changes. Access older versions in the{' '}
                                    <Link to={`${urls.endpoint(endpoint.name)}?tab=${EndpointTab.VERSIONS}`}>
                                        Versions tab
                                    </Link>
                                    .
                                </>
                            }
                        >
                            Current version
                        </LemonLabel>
                        <span className="text-sm font-semibold">v{endpoint.current_version}</span>
                    </div>
                    {!isViewingOldVersion && (
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
                    )}
                </div>
                <div className="flex flex-col gap-4 overflow-hidden items-start min-[1200px]:items-end">
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

            {/* Row 2: Version info (only when viewing old version) */}
            {isViewingOldVersion && (
                <div className="inline-flex deprecated-space-x-8">
                    <div className="flex flex-col w-28">
                        <LemonLabel>Version status</LemonLabel>
                        <LemonTag type={viewingVersion.is_active ? 'success' : 'danger'} className="w-fit">
                            <b className="uppercase">{viewingVersion.is_active ? 'Active' : 'Inactive'}</b>
                        </LemonTag>
                    </div>
                    <div className="flex flex-col w-34">
                        <LemonLabel>Viewing version</LemonLabel>
                        <span className="text-sm font-semibold">v{viewingVersion.version}</span>
                    </div>
                    <div className="flex flex-col">
                        <LemonLabel>Version URL</LemonLabel>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            onClick={() => {
                                navigator.clipboard.writeText(versionUrl!)
                                lemonToast.success('Version URL copied to clipboard')
                            }}
                            className="font-mono text-xs"
                        >
                            {versionUrl}
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
