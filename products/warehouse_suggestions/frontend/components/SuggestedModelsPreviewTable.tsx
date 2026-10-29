import { useActions, useValues } from 'kea'

import { IconCheck, IconClock, IconX } from '@posthog/icons'
import { Badge, Button, DataTable, type DataTableProps, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { subjectUrl } from '../subjectUrl'
import { suggestionBlockedReason } from '../suggestionBlockedReason'
import {
    SavingHighlight,
    isMaterializePayload,
    isUnmaterializePayload,
    materializeSaving,
    notNowCondition,
    readSummary,
    rebuiltSummary,
    savingHighlight,
    unmaterializeSaving,
} from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

const PAGE_SIZE = 10

interface SuggestedChange {
    label: string
    badge: 'info' | 'default'
    dataAttr: string
    saving: SavingHighlight
}

interface SuggestionCellContext {
    row: { original: WarehouseSuggestionApi }
}

function suggestedChange(suggestion: WarehouseSuggestionApi): SuggestedChange | null {
    const { payload } = suggestion
    if (isMaterializePayload(payload)) {
        return {
            label: 'Materialize',
            badge: 'info',
            dataAttr: 'warehouse-suggestions-materialize',
            saving: savingHighlight(materializeSaving(payload)),
        }
    }
    if (isUnmaterializePayload(payload)) {
        return {
            label: 'Stop materializing',
            badge: 'default',
            dataAttr: 'warehouse-suggestions-unmaterialize',
            saving: savingHighlight(unmaterializeSaving(payload)),
        }
    }
    return null
}

function detailLines(suggestion: WarehouseSuggestionApi): string[] {
    const rebuiltByViews = isMaterializePayload(suggestion.payload) ? (suggestion.payload.recomputed_by_views ?? 0) : 0
    const readByPeople = (suggestion.evidence.human_requests ?? 0) > 0
    return [
        ...(rebuiltByViews > 0 ? [rebuiltSummary(rebuiltByViews)] : []),
        ...(readByPeople || rebuiltByViews === 0 ? [readSummary(suggestion.evidence)] : []),
    ]
}

function SuggestionActions({ suggestion }: { suggestion: WarehouseSuggestionApi }): JSX.Element | null {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { openMaterializeModal, openAcceptConfirm, dismissSuggestion } = useActions(warehouseSuggestionsLogic)
    const change = suggestedChange(suggestion)
    if (!change) {
        return null
    }
    const blockedReason = suggestionBlockedReason(
        suggestion,
        actionsInFlight,
        leavingSuggestionIds.includes(suggestion.id)
    )
    const accept = (): void =>
        suggestion.kind === 'unmaterialize' ? openAcceptConfirm(suggestion.id) : openMaterializeModal(suggestion.id)

    return (
        <div data-suggestion-row={suggestion.id} className="flex justify-end">
            <div data-suggestion-actions className="flex items-center gap-1">
                <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label={change.label}
                    tooltip={change.label}
                    disabledReason={blockedReason}
                    onClick={accept}
                    data-attr={change.dataAttr}
                >
                    <IconCheck />
                </Button>
                <Button
                    size="icon-sm"
                    aria-label="Not now"
                    tooltip={`Not now. ${notNowCondition(suggestion.kind)}`}
                    disabledReason={blockedReason}
                    onClick={() => dismissSuggestion(suggestion.id, 'not_now')}
                    data-attr="warehouse-suggestions-not-now"
                >
                    <IconClock />
                </Button>
                <Button
                    size="icon-sm"
                    aria-label="Dismiss"
                    tooltip="Dismiss. Won't be suggested again."
                    disabledReason={blockedReason}
                    onClick={() => dismissSuggestion(suggestion.id, 'not_useful')}
                    data-attr="warehouse-suggestions-dismiss"
                >
                    <IconX />
                </Button>
            </div>
        </div>
    )
}

const COLUMNS: DataTableProps<WarehouseSuggestionApi, unknown>['columns'] = [
    {
        id: 'change',
        header: 'Change',
        enableSorting: false,
        cell: ({ row }: SuggestionCellContext) => {
            const change = suggestedChange(row.original)
            return change ? <Badge variant={change.badge}>{change.label}</Badge> : null
        },
    },
    {
        id: 'name',
        header: 'Name',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }: SuggestionCellContext) => (
            <div className="flex min-w-0 flex-col gap-0.5">
                <Button
                    variant="link"
                    size="inline"
                    className="self-start"
                    render={<LinkPrimitive to={subjectUrl(row.original)} target="_blank" />}
                >
                    <span className="truncate">{row.original.payload.subject_name}</span>
                    <span className="sr-only"> (opens in a new tab)</span>
                </Button>
                {detailLines(row.original).map((line) => (
                    <Text key={line} size="xs" variant="muted" className="@min-[40rem]/main-content:hidden">
                        {line}
                    </Text>
                ))}
            </div>
        ),
    },
    {
        id: 'detail',
        header: () => <span className="hidden @min-[40rem]/main-content:inline">Detail</span>,
        enableSorting: false,
        cell: ({ row }: SuggestionCellContext) => (
            <div className="hidden flex-col @min-[40rem]/main-content:flex">
                {detailLines(row.original).map((line) => (
                    <Text key={line} size="xs" variant="muted" className="whitespace-nowrap">
                        {line}
                    </Text>
                ))}
            </div>
        ),
    },
    {
        id: 'saving',
        header: 'Saves a month',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }: SuggestionCellContext) => {
            const change = suggestedChange(row.original)
            return change ? (
                <Text
                    size="xs"
                    weight="semibold"
                    translate="no"
                    className="whitespace-nowrap tabular-nums text-success-foreground"
                >
                    {change.saving.amount}
                </Text>
            ) : null
        },
    },
    {
        id: 'actions',
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }: SuggestionCellContext) => <SuggestionActions suggestion={row.original} />,
    },
]

export interface SuggestedModelsPreviewTableProps {
    suggestions: WarehouseSuggestionApi[]
}

export function SuggestedModelsPreviewTable({ suggestions }: SuggestedModelsPreviewTableProps): JSX.Element {
    return (
        <div data-attr="models-overview-suggestions">
            <DataTable columns={COLUMNS} data={suggestions} pageSize={PAGE_SIZE} size="sm" fullWidth />
        </div>
    )
}
