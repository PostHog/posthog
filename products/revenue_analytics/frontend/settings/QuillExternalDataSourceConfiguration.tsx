import { IconInfo, IconPlus } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Spinner,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, DataWarehouseViewLink, ExternalDataSource } from '~/types'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { QuillRevenueSourceJoin } from './QuillRevenueSourceJoin'

function HeadWithHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {label}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </span>
    )
}

export interface QuillExternalDataSourceConfigurationProps {
    hideDescription?: boolean
    revenueSources: ExternalDataSource[]
    sourcesLoading: boolean
    sourcesUpdating: boolean
    joins: DataWarehouseViewLink[]
    configDisabledReason: (source: ExternalDataSource) => string | undefined
    onAddSource: () => void
    onSourceEnabledChange: (source: ExternalDataSource, checked: boolean) => void
    onInvoicelessChargesChange: (source: ExternalDataSource, checked: boolean) => void
    onEditJoin: (join: DataWarehouseViewLink) => void
    onDeleteJoin: (join: DataWarehouseViewLink) => void
    onNewJoin: (join: Partial<DataWarehouseViewLink>) => void
}

export function QuillExternalDataSourceConfiguration({
    hideDescription = false,
    revenueSources,
    sourcesLoading,
    sourcesUpdating,
    joins,
    configDisabledReason,
    onAddSource,
    onSourceEnabledChange,
    onInvoicelessChargesChange,
    onEditJoin,
    onDeleteJoin,
    onNewJoin,
}: QuillExternalDataSourceConfigurationProps): JSX.Element {
    const joinProps = { joins, configDisabledReason, onEditJoin, onDeleteJoin, onNewJoin }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
                {!hideDescription && (
                    <Text size="xs" render={<p className="m-0 max-w-160" />}>
                        PostHog can display revenue data in our Revenue Analytics product from the following data
                        warehouse sources. You can enable/disable each source to stop it from being used for revenue
                        data. You can also configure how we join your revenue data to the PostHog persons table - when
                        this is set, we'll be able to properly display revenue for a person via the
                        persons.$virt_revenue and persons.$virt_mrr virtual fields.
                    </Text>
                )}
                <AccessControlAction
                    resourceType={AccessControlResourceType.RevenueAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button variant="primary" onClick={onAddSource}>
                        <IconPlus />
                        Add new source
                    </Button>
                </AccessControlAction>
            </div>
            {sourcesLoading ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                </div>
            ) : (
                <Table fullWidth className="rounded-md border border-border">
                    <TableHeader>
                        <TableRow>
                            <TableHead />
                            <TableHead>Source</TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="Persons Join"
                                    help="How do you want to join persons to this source in Revenue Analytics?"
                                />
                            </TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="Groups Join"
                                    help="How do you want to join groups to this source in Revenue Analytics?"
                                />
                            </TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="Include invoiceless charges"
                                    help="By default, Revenue analytics considers both your invoices and any invoiceless charges when calculating your revenue - and exposing it through the `revenue_item` views. Disable this if we should only consider your invoices and omit charges from the calculations."
                                />
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    {revenueSources.length === 0 ? (
                        <TableEmpty>
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>No DWH revenue sources configured yet</EmptyTitle>
                                </EmptyHeader>
                            </Empty>
                        </TableEmpty>
                    ) : (
                        <TableBody>
                            {revenueSources.map((source) => (
                                <TableRow key={source.id}>
                                    <TableCell>
                                        {sourcesUpdating ? <Spinner /> : <SourceIcon type={source.source_type} />}
                                    </TableCell>
                                    <TableCell>
                                        <span className="inline-flex items-center gap-2">
                                            <Button
                                                variant="link-foreground"
                                                size="sm"
                                                nativeButton={false}
                                                render={
                                                    <LinkPrimitive
                                                        to={urls.dataWarehouseSource(`managed-${source.id}`)}
                                                    />
                                                }
                                            >
                                                {source.source_type}&nbsp;{source.prefix && `(${source.prefix})`}
                                            </Button>
                                            <AccessControlAction
                                                resourceType={AccessControlResourceType.RevenueAnalytics}
                                                minAccessLevel={AccessControlLevel.Editor}
                                            >
                                                <Switch
                                                    aria-label={`Use ${source.source_type} for revenue analytics`}
                                                    checked={source.revenue_analytics_config.enabled}
                                                    disabledReason={sourcesUpdating ? 'Updating...' : undefined}
                                                    onCheckedChange={(checked) =>
                                                        onSourceEnabledChange(source, checked)
                                                    }
                                                />
                                            </AccessControlAction>
                                        </span>
                                    </TableCell>
                                    <TableCell>
                                        <QuillRevenueSourceJoin
                                            source={source}
                                            joiningTableName="persons"
                                            joiningTableKey="pdi.distinct_id"
                                            {...joinProps}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        <QuillRevenueSourceJoin
                                            source={source}
                                            joiningTableName="groups"
                                            joiningTableKey="key"
                                            editTooltip="Edit join"
                                            {...joinProps}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        <Switch
                                            aria-label="Include invoiceless charges"
                                            checked={
                                                source.revenue_analytics_config.enabled &&
                                                source.revenue_analytics_config.include_invoiceless_charges
                                            }
                                            disabledReason={configDisabledReason(source)}
                                            onCheckedChange={(checked) => onInvoicelessChargesChange(source, checked)}
                                        />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    )}
                </Table>
            )}
        </div>
    )
}
