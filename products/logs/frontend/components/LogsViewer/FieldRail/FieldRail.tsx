import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { Field, FieldOption } from './Field'
import { fieldCountsLogic } from './fieldCountsLogic'
import { fieldRailLogic } from './fieldRailLogic'
import { FieldConfig, FieldFilterKey, fieldsByGroup, resourceAttributeValues } from './fields'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

export interface FieldRailProps {
    id: string
}

/** Resizable left-hand field rail, rendered entirely from the FIELDS config (see fields.ts). */
export function FieldRail({ id }: FieldRailProps): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFieldRailCollapsed } = useActions(logsViewerConfigLogic)
    const { severityLevels, serviceNames, filterGroup } = useValues(logsViewerFiltersLogic)
    const { fieldValues, loadingFieldKeys, fieldSearch, visibleFields } = useValues(fieldCountsLogic({ id }))
    const { setFieldSearch } = useActions(fieldCountsLogic({ id }))
    const { collapsedFields } = useValues(fieldRailLogic({ id }))
    const { toggleFieldValue, toggleFieldCollapsed } = useActions(fieldRailLogic({ id }))

    const selectedByKey: Record<FieldFilterKey, string[]> = {
        severityLevels: severityLevels ?? [],
        serviceNames: serviceNames ?? [],
    }

    const onToggleClosed = useCallback(
        (shouldBeClosed: boolean) => setFieldRailCollapsed(shouldBeClosed),
        [setFieldRailCollapsed]
    )
    const resizerLogicProps: ResizerLogicProps = useMemo(
        () => ({
            logicKey: `logs-field-rail-${id}`,
            containerRef: railRef,
            persistent: true,
            persistPrefix: '2026-06-18',
            placement: 'right',
            closeThreshold: COLLAPSE_THRESHOLD_PX,
            onToggleClosed,
        }),
        [id, onToggleClosed]
    )
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    const renderField = (field: FieldConfig): JSX.Element => {
        const { source } = field
        // Selection: column fields read their dedicated filter field; resource-attribute fields read
        // their log_resource_attribute filter out of the group.
        const selected =
            source.type === 'resourceAttribute'
                ? resourceAttributeValues(filterGroup, source.key)
                : selectedByKey[source.filterKey]
        // Values + counts come from the cross-filtered endpoint, keyed by field.key.
        const fetched: FieldOption[] = (fieldValues[field.key] ?? []).map((r) => ({
            value: r.value,
            label: r.value,
            count: r.count,
        }))
        const loading = loadingFieldKeys.includes(field.key)
        const onToggle = (value: string): void => toggleFieldValue(source, value)
        const onToggleCollapsed = (): void => toggleFieldCollapsed(field.key)
        const collapsed = collapsedFields.includes(field.key)

        if (field.kind === 'fixed') {
            // Fixed value set from config, counts overlaid. Missing values render as a dimmed 0.
            const countByValue = new Map(fetched.map((option) => [option.value, option.count]))
            const options: FieldOption[] = (field.fixedOptions ?? []).map((option) => ({
                ...option,
                count: countByValue.get(option.value) ?? 0,
            }))
            return (
                <Field
                    key={field.key}
                    title={field.title}
                    options={options}
                    selected={selected}
                    onToggle={onToggle}
                    loading={loading}
                    collapsed={collapsed}
                    onToggleCollapsed={onToggleCollapsed}
                    dimZeroCounts
                />
            )
        }

        // Dynamic field: values + counts come straight from the cross-filtered endpoint (zeros never appear).
        return (
            <Field
                key={field.key}
                title={field.title}
                options={fetched}
                selected={selected}
                onToggle={onToggle}
                loading={loading}
                emptyLabel={field.emptyLabel}
                searchValue={field.searchable ? (fieldSearch[field.key] ?? '') : undefined}
                onSearchChange={field.searchable ? (value) => setFieldSearch(field.key, value) : undefined}
                searchPlaceholder={field.searchPlaceholder}
                collapsed={collapsed}
                onToggleCollapsed={onToggleCollapsed}
                maxHeight={field.maxHeight}
            />
        )
    }

    return (
        <div
            ref={railRef}
            className="relative flex flex-col shrink-0 border rounded bg-surface-primary overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: desiredSize ?? DEFAULT_WIDTH_PX, minWidth: 'min-content', maxWidth: '40%' }}
            data-attr="logs-field-rail"
        >
            <div className="px-2 py-1 border-b">
                <span className="text-xs font-semibold text-secondary uppercase tracking-wide">Filters</span>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-2">
                {fieldsByGroup(visibleFields).map(([group, fields]) => (
                    <div key={group}>
                        <div className="px-1 pb-1 mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted border-b border-primary">
                            {group}
                        </div>
                        {fields.map(renderField)}
                    </div>
                ))}
            </div>
            <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
        </div>
    )
}
