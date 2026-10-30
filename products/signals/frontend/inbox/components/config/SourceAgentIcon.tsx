import { useValues } from 'kea'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { WAREHOUSE_SOURCE_SETUP, WarehouseBackedSource } from '../../signalSourcesLogic'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { AgentRosterDefinition } from './agentRosterMeta'

const SIZES = {
    small: { px: 16, className: 'text-base' },
    medium: { px: 24, className: 'text-2xl' },
} as const

export function SourceAgentIcon({
    agent,
    size = 'small',
}: {
    agent: AgentRosterDefinition
    size?: keyof typeof SIZES
}): JSX.Element | null {
    const { availableSources } = useValues(availableSourcesLogic)
    const warehouseSetup = Object.hasOwn(WAREHOUSE_SOURCE_SETUP, agent.source)
        ? WAREHOUSE_SOURCE_SETUP[agent.source as WarehouseBackedSource]
        : null
    if (warehouseSetup && availableSources?.[warehouseSetup.dwSourceType]?.iconPath) {
        return <SourceIcon type={warehouseSetup.dwSourceType} sizePx={SIZES[size].px} disableTooltip />
    }
    const meta = getSourceProductMeta(agent.sourceProduct)
    if (!meta?.Icon) {
        return null
    }
    const Icon = meta.Icon
    return <Icon className={`shrink-0 ${SIZES[size].className} ${meta.colorClass}`} />
}
