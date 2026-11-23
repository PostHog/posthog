import { IconPlus, IconTrash } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType, DataWarehouseViewLink, ExternalDataSource } from '~/types'

import { findRevenueJoin, newRevenueJoin } from './revenueSourceJoins'

export interface QuillRevenueSourceJoinProps {
    source: ExternalDataSource
    joins: DataWarehouseViewLink[]
    joiningTableName: 'persons' | 'groups'
    joiningTableKey: string
    editTooltip?: string
    configDisabledReason: (source: ExternalDataSource) => string | undefined
    onEditJoin: (join: DataWarehouseViewLink) => void
    onDeleteJoin: (join: DataWarehouseViewLink) => void
    onNewJoin: (join: Partial<DataWarehouseViewLink>) => void
}

export function QuillRevenueSourceJoin({
    source,
    joins,
    joiningTableName,
    joiningTableKey,
    editTooltip,
    configDisabledReason,
    onEditJoin,
    onDeleteJoin,
    onNewJoin,
}: QuillRevenueSourceJoinProps): JSX.Element {
    const join = findRevenueJoin(joins, source, joiningTableName)

    return (
        <span className="flex flex-wrap items-center gap-2">
            <Text size="xs" render={<span className="m-0 whitespace-nowrap" />}>
                Joined to <code>{joiningTableName}</code> via:
            </Text>
            <AccessControlAction
                resourceType={AccessControlResourceType.RevenueAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                {({ disabledReason }) =>
                    join && source.revenue_analytics_config.enabled ? (
                        <>
                            <Button
                                variant="outline"
                                onClick={() => onEditJoin(join)}
                                disabledReason={configDisabledReason(source) ?? disabledReason}
                                tooltip={editTooltip}
                            >
                                {join.source_table_name}.{join.source_table_key}
                            </Button>
                            <Button
                                variant="destructive-outline"
                                size="icon"
                                aria-label="Delete join"
                                tooltip="Delete join"
                                disabledReason={disabledReason}
                                onClick={() => onDeleteJoin(join)}
                            >
                                <IconTrash />
                            </Button>
                        </>
                    ) : (
                        <Button
                            variant="outline"
                            onClick={() => onNewJoin(newRevenueJoin(source, joiningTableName, joiningTableKey))}
                            disabledReason={configDisabledReason(source) ?? disabledReason}
                        >
                            <IconPlus />
                            Add join
                        </Button>
                    )
                }
            </AccessControlAction>
        </span>
    )
}
