import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCheck, IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import ViewRecordingButton, {
    RecordingPlayerType,
    ViewRecordingButtonVariant,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { PropertyFilterType, PropertyOperator } from '~/types'

// The key-matching helpers and their convention lists are shared with Logs, because both
// products resolve the same SDK-emitted attribute keys (posthogDistinctId, sessionId, ...).
import { isDistinctIdKey, isSessionIdKey } from 'products/logs/frontend/utils'
import { tracingCorrelationConfigLogic } from 'products/tracing/frontend/tracingCorrelationConfigLogic'
import { tracingFiltersLogic } from 'products/tracing/frontend/tracingFiltersLogic'

const APPLIED_INDICATOR_MS = 2000

// The indicator names the state the click leaves behind, not the write, because a click on a value
// already filtered reconciles to the same group and writes nothing (see spanFilterAdd.ts).

interface AttributeRow {
    key: string
    value: string
}

type FilterDirection = 'include' | 'exclude'

export interface SpanAttributesProps {
    attributes: Record<string, string>
    title: string
    emptyLabel?: string
    /** @default true */
    showFilterActions?: boolean
    /** Required when `showFilterActions` is true. */
    propertyType?: PropertyFilterType.SpanAttribute | PropertyFilterType.SpanResourceAttribute
}

export function SpanAttributes({
    attributes,
    title,
    emptyLabel = 'No attributes',
    showFilterActions = true,
    propertyType,
}: SpanAttributesProps): JSX.Element {
    const { addFilter } = useActions(tracingFiltersLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { configuredDistinctIdKeys, configuredSessionIdKeys } = useValues(tracingCorrelationConfigLogic)
    const [appliedFilter, setAppliedFilter] = useState<{ key: string; direction: FilterDirection } | null>(null)
    const appliedFilterTimeoutRef = useRef<number | null>(null)

    // Person/replay links only apply to real OTel attribute tables (propertyType set), because
    // the synthetic "Span details" table repeats span metadata under conventional-looking keys.
    const correlationLinksEnabled =
        !!featureFlags[FEATURE_FLAGS.TRACING_SESSION_PERSON_LINKS] && propertyType !== undefined

    useEffect(
        () => () => {
            if (appliedFilterTimeoutRef.current !== null) {
                window.clearTimeout(appliedFilterTimeoutRef.current)
            }
        },
        []
    )

    const showApplied = (key: string, direction: FilterDirection): void => {
        if (appliedFilterTimeoutRef.current !== null) {
            window.clearTimeout(appliedFilterTimeoutRef.current)
        }
        setAppliedFilter({ key, direction })
        appliedFilterTimeoutRef.current = window.setTimeout(() => setAppliedFilter(null), APPLIED_INDICATOR_MS)
    }

    const rows: AttributeRow[] = Object.entries(attributes).map(([key, value]) => ({ key, value }))

    const columns: LemonTableColumns<AttributeRow> = [
        ...(showFilterActions
            ? [
                  {
                      key: 'actions',
                      width: 0,
                      render: (_: unknown, record: AttributeRow) => (
                          <div className="flex gap-x-0">
                              {appliedFilter?.key === record.key && appliedFilter.direction === 'include' ? (
                                  <LemonButton size="xsmall" tooltip="Filter applied">
                                      <IconCheck className="text-success" />
                                  </LemonButton>
                              ) : (
                                  <LemonButton
                                      tooltip="Add as filter"
                                      size="xsmall"
                                      onClick={(e) => {
                                          e.stopPropagation()
                                          addFilter(record.key, record.value, PropertyOperator.Exact, propertyType)
                                          showApplied(record.key, 'include')
                                      }}
                                  >
                                      <IconPlusSquare />
                                  </LemonButton>
                              )}
                              {appliedFilter?.key === record.key && appliedFilter.direction === 'exclude' ? (
                                  <LemonButton size="xsmall" tooltip="Filter applied">
                                      <IconCheck className="text-success" />
                                  </LemonButton>
                              ) : (
                                  <LemonButton
                                      tooltip="Exclude as filter"
                                      size="xsmall"
                                      onClick={(e) => {
                                          e.stopPropagation()
                                          addFilter(record.key, record.value, PropertyOperator.IsNot, propertyType)
                                          showApplied(record.key, 'exclude')
                                      }}
                                  >
                                      <IconMinusSquare />
                                  </LemonButton>
                              )}
                          </div>
                      ),
                  },
              ]
            : []),
        {
            title: 'Key',
            key: 'key',
            dataIndex: 'key',
            width: 0,
            render: (_, record): JSX.Element => (
                <span className="font-mono text-xs text-muted whitespace-nowrap">{record.key}</span>
            ),
        },
        {
            title: 'Value',
            key: 'value',
            dataIndex: 'value',
            render: (_, record): JSX.Element => {
                if (record.value === '') {
                    return <span className="font-mono text-xs text-muted italic">(empty)</span>
                }
                // The stopPropagation wrapper keeps a link click from also triggering any
                // ancestor row handler, matching SpanRowActions' convention.
                const correlationLink = !correlationLinksEnabled ? null : isDistinctIdKey(
                      record.key,
                      configuredDistinctIdKeys
                  ) ? (
                    <span onClick={(e) => e.stopPropagation()}>
                        <PersonDisplay person={{ distinct_id: record.value }} noEllipsis inline />
                    </span>
                ) : isSessionIdKey(record.key, configuredSessionIdKeys) ? (
                    <span onClick={(e) => e.stopPropagation()}>
                        <ViewRecordingButton
                            sessionId={record.value}
                            openPlayerIn={RecordingPlayerType.Modal}
                            label={record.value}
                            variant={ViewRecordingButtonVariant.Link}
                            checkRecordingExists
                        />
                    </span>
                ) : null
                return (
                    <CopyToClipboardInline
                        explicitValue={record.value}
                        description="attribute value"
                        iconSize="xsmall"
                        iconPosition="start"
                        selectable
                        className="gap-1 font-mono text-xs"
                    >
                        {correlationLink ?? <span>{record.value}</span>}
                    </CopyToClipboardInline>
                )
            },
        },
    ]

    return (
        <div className="bg-primary overflow-hidden rounded border border-border">
            <div className="px-3 py-2 bg-bg-light border-b border-border">
                <span className="text-xs font-semibold text-muted uppercase">{title}</span>
            </div>
            {rows.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted italic">{emptyLabel}</div>
            ) : (
                <LemonTable embedded showHeader={false} size="small" rowKey="key" columns={columns} dataSource={rows} />
            )}
        </div>
    )
}
