import * as moneyPng from '@posthog/brand/hoggies/png/money'
import { IconArrowRight, IconCheckCircle, IconExternal, IconInfo } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardFooter,
    Field,
    Heading,
    Input,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

const HedgehogMoney = pngHoggie(moneyPng)

export function QuillSourceCatalog({
    hasSources,
    totalConnected,
    search,
    onSearchChange,
    groups,
    onSelect,
    onBack,
    onContinue,
}: {
    hasSources: boolean
    totalConnected: number
    search: string
    onSearchChange: (search: string) => void
    groups: {
        title: string
        tooltip?: string
        sources: { id: string; label: string; isConnected: boolean; connectUrl: string }[]
    }[]
    onSelect: (sourceId: string) => void
    onBack?: () => void
    onContinue?: () => void
}): JSX.Element {
    const visibleGroups = groups.filter((group) => group.sources.length > 0)

    return (
        <Card className="w-full">
            <CardContent className="flex flex-col gap-3">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <Heading size="base" render={<h3 className="m-0" />}>
                            Connect your marketing sources
                        </Heading>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {hasSources
                                ? `${totalConnected} source${totalConnected !== 1 ? 's' : ''} connected. Choose another platform to connect.`
                                : 'Choose a platform to start importing spend data.'}
                        </Text>
                    </div>
                    <HedgehogMoney className="w-20 shrink-0" />
                </div>

                <Field>
                    <Input
                        type="search"
                        placeholder="Search integrations"
                        aria-label="Search integrations"
                        value={search}
                        onChange={(event) => onSearchChange(event.target.value)}
                    />
                </Field>
                {visibleGroups.length === 0 && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        No integrations match your search.
                    </Text>
                )}
                {visibleGroups.map((group) => (
                    <div key={group.title} className="flex flex-col gap-2">
                        <div className="flex items-center gap-1">
                            <Text size="xs" variant="muted" weight="medium" render={<span className="m-0" />}>
                                {group.title}
                            </Text>
                            {group.tooltip && (
                                <Tooltip>
                                    <TooltipTrigger
                                        delay={0}
                                        render={
                                            <Button size="icon-xs" aria-label={`About ${group.title.toLowerCase()}`} />
                                        }
                                    >
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent>{group.tooltip}</TooltipContent>
                                </Tooltip>
                            )}
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {group.sources.map((source) => (
                                <Button
                                    key={source.id}
                                    variant="outline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={source.connectUrl} />}
                                    onClick={() => onSelect(source.id)}
                                    data-attr="marketing-manual-connect-source"
                                >
                                    <SourceIcon type={source.id} size="small" disableTooltip />
                                    {source.label}
                                    {source.isConnected && <IconCheckCircle className="text-success-foreground" />}
                                </Button>
                            ))}
                        </div>
                    </div>
                ))}
            </CardContent>
            <CardFooter className="flex-wrap justify-between gap-3">
                {onBack && (
                    <Button variant="outline" onClick={onBack}>
                        Back to suggestions
                    </Button>
                )}
                <Button
                    variant="link"
                    nativeButton={false}
                    render={
                        <LinkPrimitive
                            to="https://posthog.com/docs/web-analytics/marketing-analytics"
                            target="_blank"
                        />
                    }
                >
                    View docs
                    <IconExternal />
                </Button>
                {onContinue && (
                    <Button variant="primary" onClick={onContinue} data-attr="marketing-onboarding-continue">
                        <span>{hasSources ? 'Continue to dashboard' : 'Skip for now'}</span>
                        <IconArrowRight />
                    </Button>
                )}
            </CardFooter>
        </Card>
    )
}
