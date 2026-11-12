import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { urls } from 'scenes/urls'

import { connectionSelectorLogic } from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

import type { WarehouseNativeBinding } from './warehouseNativeSources'

export type WarehouseNativeConnectionFieldsProps = {
    binding: WarehouseNativeBinding
    onChange: (binding: WarehouseNativeBinding) => void
}

export function WarehouseNativeConnectionFields({
    binding,
    onChange,
}: WarehouseNativeConnectionFieldsProps): JSX.Element {
    const { connectionOptions, connectionOptionsLoading } = useValues(connectionSelectorLogic)
    const { maybeLoadConnectionOptions, loadConnectionOptions } = useActions(connectionSelectorLogic)

    useOnMountEffect(() => {
        maybeLoadConnectionOptions()
    })

    // A reload keeps the loaded options, so the select only waits for the first load
    const loading = connectionOptions === null
    // A warehouse-native query needs a direct BigQuery connection. A synced source cannot run it.
    const options = (connectionOptions ?? [])
        .filter((source) => source.source_type === 'BigQuery' && source.access_method === 'direct')
        .map((source) => ({ value: source.id, label: source.description || source.prefix || 'BigQuery' }))
    if (!loading && binding.connection_id && !options.some((option) => option.value === binding.connection_id)) {
        options.push({ value: binding.connection_id, label: 'Unavailable connection' })
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <LemonLabel>Connection</LemonLabel>
                <div className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                        {!loading && options.length === 0 ? (
                            <div className="text-secondary text-sm">
                                This project has no direct BigQuery connection yet.{' '}
                                <Link
                                    to={urls.dataWarehouseSourceNew('BigQuery', undefined, undefined, 'direct')}
                                    target="_blank"
                                    data-attr="experiment-warehouse-native-add-connection"
                                >
                                    Add a BigQuery connection
                                </Link>
                            </div>
                        ) : (
                            <LemonSelect
                                fullWidth
                                loading={loading}
                                value={loading ? null : binding.connection_id || null}
                                onChange={(connectionId) => onChange({ ...binding, connection_id: connectionId ?? '' })}
                                options={options}
                                placeholder="Select a BigQuery connection"
                                data-attr="experiment-warehouse-native-connection"
                            />
                        )}
                    </div>
                    {/* A connection added in another tab only shows after a reload */}
                    <LemonButton
                        icon={<IconRefresh />}
                        type="secondary"
                        onClick={() => loadConnectionOptions()}
                        loading={connectionOptionsLoading}
                        tooltip="Reload connections"
                        aria-label="Reload connections"
                        data-attr="experiment-warehouse-native-reload-connections"
                    />
                </div>
            </div>
            <div className="flex flex-wrap gap-3">
                <div className="flex min-w-48 flex-1 flex-col gap-1">
                    <LemonLabel info="What the experiment assigns to a variant, such as customer or account.">
                        Randomization unit
                    </LemonLabel>
                    <LemonInput
                        value={binding.unit.unit_type}
                        onChange={(unitType) =>
                            onChange({ ...binding, unit: { ...binding.unit, unit_type: unitType } })
                        }
                        placeholder="customer"
                        data-attr="experiment-warehouse-native-unit-type"
                    />
                </div>
                <div className="flex min-w-48 flex-1 flex-col gap-1">
                    <LemonLabel info="Which IDs the entity_id column holds, such as billing_customer_id.">
                        ID type
                    </LemonLabel>
                    <LemonInput
                        value={binding.unit.id_namespace}
                        onChange={(idNamespace) =>
                            onChange({ ...binding, unit: { ...binding.unit, id_namespace: idNamespace } })
                        }
                        placeholder="billing_customer_id"
                        data-attr="experiment-warehouse-native-id-namespace"
                    />
                </div>
            </div>
            <div className="text-secondary text-xs">
                The exposure query and every metric query must use the same connection, unit and ID type, so that their
                entity_id values match.
            </div>
        </div>
    )
}
