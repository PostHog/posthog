import { Fragment } from 'react'

import { IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

export function QuillAddIntegrationButton({
    open,
    onOpenChange,
    groups,
    newSourcesNotice,
    showNewSources,
    restrictedReason,
    integrationLabel,
    isNewSource,
    integrationUrl,
    onIntegrate,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    groups: { title: string; sources: readonly string[] }[]
    newSourcesNotice: string | null
    showNewSources: boolean
    restrictedReason: string | null
    integrationLabel: (integrationId: string) => string
    isNewSource: (integrationId: string) => boolean
    integrationUrl: (integrationId: string) => string | undefined
    onIntegrate: (integrationId: string) => void
}): JSX.Element {
    return (
        <DropdownMenu open={open} onOpenChange={onOpenChange}>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="primary"
                        data-attr="add-integration"
                        aria-label="Add source"
                        disabledReason={restrictedReason}
                        tooltip={showNewSources && !open ? 'New ad sources are available' : undefined}
                    />
                }
            >
                <IconPlus />
                Add source
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {newSourcesNotice ? (
                    <>
                        <div className="flex w-72 max-w-full flex-col gap-1 p-2">
                            <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                                New ad sources
                            </Text>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {newSourcesNotice}
                            </Text>
                        </div>
                        <DropdownMenuSeparator />
                    </>
                ) : null}
                {groups.map(({ title, sources }, index) => (
                    <Fragment key={title}>
                        {index > 0 && <DropdownMenuSeparator />}
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>{title}</DropdownMenuLabel>
                            {sources.map((integrationId) => {
                                const url = integrationUrl(integrationId)
                                return (
                                    <DropdownMenuItem
                                        key={integrationId}
                                        disabledReason={restrictedReason}
                                        onClick={() => onIntegrate(integrationId)}
                                        // A real link keeps cmd-click and middle-click opening the source in a new tab.
                                        {...(url
                                            ? { render: <Button size="row" left render={<LinkPrimitive to={url} />} /> }
                                            : {})}
                                    >
                                        <SourceIcon type={integrationId} size="xsmall" disableTooltip />
                                        {integrationLabel(integrationId)}
                                        {isNewSource(integrationId) && <Badge variant="info">New</Badge>}
                                    </DropdownMenuItem>
                                )
                            })}
                        </DropdownMenuGroup>
                    </Fragment>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
