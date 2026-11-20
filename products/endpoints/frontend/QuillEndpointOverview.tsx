import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconCopy, IconInfo } from '@posthog/icons'
import { Avatar, AvatarFallback, Badge, Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { endpointLogic } from './endpointLogic'
import { EndpointTab, endpointSceneLogic } from './endpointSceneLogic'

function OverviewField({
    label,
    info,
    children,
}: {
    label: string
    info?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Text size="xs" variant="muted" render={<span />} className="inline-flex items-center gap-1">
                {label}
                {info && (
                    <Tooltip>
                        <TooltipTrigger render={<span className="inline-flex" />}>
                            <IconInfo />
                        </TooltipTrigger>
                        <TooltipContent>{info}</TooltipContent>
                    </Tooltip>
                )}
            </Text>
            <div className="flex min-h-6 items-center">{children}</div>
        </div>
    )
}

function CopyButton({ value, name, dataAttr }: { value: string; name: string; dataAttr: string }): JSX.Element {
    return (
        <Button
            variant="outline"
            size="sm"
            className="max-w-full font-mono"
            onClick={() => void copyToClipboard(value, name)}
            data-attr={dataAttr}
        >
            <IconCopy />
            <span className="truncate">{value}</span>
        </Button>
    )
}

export function QuillEndpointOverview(): JSX.Element {
    const { endpoint } = useValues(endpointLogic)
    const { viewingVersion } = useValues(endpointSceneLogic)

    if (!endpoint) {
        return <></>
    }

    const isViewingOldVersion = viewingVersion && viewingVersion.version !== endpoint.current_version
    const versionUrl = isViewingOldVersion ? `${endpoint.endpoint_path}?version=${viewingVersion.version}` : null
    const creator = endpoint.created_by ? fullName(endpoint.created_by) || endpoint.created_by.email : null

    return (
        <div className="flex flex-col gap-4" data-quill>
            <div className="flex flex-wrap gap-x-8 gap-y-4">
                <OverviewField label="Endpoint status">
                    <Badge variant={endpoint.is_active ? 'success' : 'destructive'}>
                        {endpoint.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                </OverviewField>
                <OverviewField
                    label="Current version"
                    info={
                        <>
                            Versions auto-increment when the query changes. Access older versions in the{' '}
                            <Button
                                variant="link"
                                size="inline"
                                render={
                                    <LinkPrimitive to={`${urls.endpoint(endpoint.name)}?tab=${EndpointTab.VERSIONS}`} />
                                }
                            >
                                Versions tab
                            </Button>
                            .
                        </>
                    }
                >
                    <Text size="sm" weight="semibold" render={<span />}>
                        v{endpoint.current_version}
                    </Text>
                </OverviewField>
                {!isViewingOldVersion && (
                    <OverviewField label="Endpoint URL">
                        <CopyButton value={endpoint.endpoint_path} name="endpoint URL" dataAttr="endpoint-copy-url" />
                    </OverviewField>
                )}
                <OverviewField label="Last executed">
                    {endpoint.last_executed_at ? (
                        <Text size="xs" render={<span />}>
                            <TZLabel time={endpoint.last_executed_at} />
                        </Text>
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            Never
                        </Text>
                    )}
                </OverviewField>
                {creator && (
                    <OverviewField label="Created by">
                        <span className="flex items-center gap-2">
                            <Avatar size="xs">
                                <AvatarFallback>{creator.slice(0, 1).toUpperCase()}</AvatarFallback>
                            </Avatar>
                            <Text size="xs" render={<span />}>
                                {creator}
                            </Text>
                        </span>
                    </OverviewField>
                )}
            </div>

            {isViewingOldVersion && (
                <div className="flex flex-wrap gap-x-8 gap-y-4">
                    <OverviewField label="Version status">
                        <Badge variant={viewingVersion.is_active ? 'success' : 'destructive'}>
                            {viewingVersion.is_active ? 'Active' : 'Inactive'}
                        </Badge>
                    </OverviewField>
                    <OverviewField label="Viewing version">
                        <Text size="sm" weight="semibold" render={<span />}>
                            v{viewingVersion.version}
                        </Text>
                    </OverviewField>
                    <OverviewField label="Version URL">
                        <CopyButton value={versionUrl!} name="version URL" dataAttr="endpoint-copy-version-url" />
                    </OverviewField>
                </div>
            )}
        </div>
    )
}
