import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { cn } from '@posthog/quill'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { QuillSelect, QuillSelectOption } from 'lib/components/QuillSelect/QuillSelect'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { UNIQUE_USERS, getHogQLValue } from 'scenes/insights/filters/aggregationTarget'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import {
    getAggregationGroupTypeIndex,
    isFunnelsQuery,
    isInsightQueryNode,
    isLifecycleQuery,
    isRetentionQuery,
} from '~/queries/utils'

import type { AggregationSelectProps } from './AggregationSelect'
import {
    CUSTOM_DATA_WAREHOUSE_ITEMS,
    aggregationQuerySourceUpdate,
    getCustomAggregationEditorValue,
} from './aggregationSelectUtils'

// Picking this option only reveals the SQL editor, the query changes once an expression is entered
const CUSTOM_SQL_OPTION = '__custom_sql_expression__'

export function QuillAggregationSelect({
    insightProps,
    className,
    hogqlAvailable,
}: AggregationSelectProps): JSX.Element | null {
    const { querySource, isFunnels, isLifecycle, isRetention, hasOnlyDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(groupsAccessLogic)
    const [editingCustomSql, setEditingCustomSql] = useState(false)

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const value =
        (isLifecycleQuery(querySource) && querySource.customAggregationTarget) ||
        (isFunnelsQuery(querySource) && querySource.funnelsFilter?.customAggregationTarget) ||
        (isRetentionQuery(querySource) && querySource.retentionFilter?.customAggregationTarget)
            ? CUSTOM_DATA_WAREHOUSE_ITEMS
            : getHogQLValue(
                  getAggregationGroupTypeIndex(querySource),
                  isFunnelsQuery(querySource) ? querySource.funnelsFilter?.funnelAggregateByHogQL : undefined
              )

    const options: QuillSelectOption<string>[] = [{ value: UNIQUE_USERS, label: 'Unique users' }]

    if (needsUpgradeForGroups || canStartUsingGroups) {
        options.push({
            value: '$group_upsell',
            label: 'Unique groups',
            disabledReason: needsUpgradeForGroups ? 'Needs group analytics' : 'Set up group analytics first',
        })
    } else {
        Array.from(groupTypes.values()).forEach((groupType) => {
            options.push({
                value: `$group_${groupType.group_type_index}`,
                label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
            })
        })
    }

    if (hogqlAvailable) {
        options.push({ value: 'properties.$session_id', label: 'Unique sessions' })
    }

    if (isFunnels || isLifecycle || isRetention) {
        const hasOnlyDataWarehouseRetentionEntities =
            isRetentionQuery(querySource) &&
            querySource.retentionFilter?.targetEntity?.type === 'data_warehouse' &&
            querySource.retentionFilter?.returningEntity?.type === 'data_warehouse'

        options.push({
            value: CUSTOM_DATA_WAREHOUSE_ITEMS,
            label: 'Custom entities',
            description: 'Custom entities from your data warehouse instead of persons or groups',
            disabledReason:
                hasOnlyDataWarehouseSeries || hasOnlyDataWarehouseRetentionEntities
                    ? undefined
                    : 'Only for insights with only data warehouse series',
        })
    }

    const customSqlValue = hogqlAvailable
        ? getCustomAggregationEditorValue(
              value,
              options.map((option) => option.value)
          )
        : ''
    const showCustomSqlEditor = hogqlAvailable && (editingCustomSql || !!customSqlValue)

    if (hogqlAvailable) {
        options.push({ value: customSqlValue || CUSTOM_SQL_OPTION, label: 'Custom SQL expression' })
    }

    const onChange = (newValue: string): void => {
        if (newValue === CUSTOM_SQL_OPTION) {
            setEditingCustomSql(true)
            return
        }
        setEditingCustomSql(false)
        updateQuerySource(aggregationQuerySourceUpdate(querySource, newValue))
    }

    return (
        <div className={cn('flex min-w-0 flex-col gap-2', className)}>
            <QuillSelect
                value={showCustomSqlEditor ? customSqlValue || CUSTOM_SQL_OPTION : value}
                onChange={onChange}
                options={options}
                data-attr="retention-aggregation-selector"
            />
            {showCustomSqlEditor ? (
                <HogQLEditor
                    onChange={(expression) => {
                        setEditingCustomSql(false)
                        if (expression) {
                            updateQuerySource(aggregationQuerySourceUpdate(querySource, expression))
                        }
                    }}
                    value={customSqlValue}
                    placeholder={
                        "Enter SQL expression, such as:\n- distinct_id\n- properties.$session_id\n- concat(distinct_id, ' ', properties.$session_id)\n- if(1 < 2, 'one', 'two')"
                    }
                />
            ) : null}
        </div>
    )
}
