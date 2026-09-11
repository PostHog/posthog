import { useActions, useValues } from 'kea'

import { LemonSkeleton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { SCRATCHPAD_PAGE_SIZE, scratchpadLogic } from '../../logics/scratchpadLogic'
import { KIND_TAG_TYPE, isReportUuid, scratchpadKindOf, scratchpadTopicOf, shortenUuid } from '../../utils/scratchpadKeys'
import { stripScoutPrefix } from '../../utils/scoutRunsWindow'

// Below this the six columns stop fitting, so every row collapses into one stacked cell. Measured
// on the container, not the viewport: the panel gets about 520 px once the nav and a side panel
// are open, which no viewport breakpoint ever reports.
const NARROW = '@max-[52rem]/ledger'
// Pipeline stages write to the scratchpad too. They are not scouts and have no scout page, so the
// Scout column names the stage and says which it is rather than linking nowhere.
const PIPELINE_PREFIX = 'pipeline:'

/**
 * The fleet's memory as a dense, newest-first ledger: one row per entry, every signal as a column,
 * and the full note as an expandable body. Reading a thousand cards top to bottom was the old
 * shape; this one answers "what has the fleet learned about X" and "what did scout Y write".
 */
export function ScratchpadLedger(): JSX.Element {
    const { filteredEntries, expandedKeys, reportTitles } = useValues(scratchpadLogic)
    const { toggleEntry } = useActions(scratchpadLogic)

    const columns: LemonTableColumns<ScratchpadEntryApi> = [
        {
            title: 'Updated',
            key: 'updated',
            className: `${NARROW}:hidden w-32`,
            render: (_, entry) =>
                entry.updated_at ? <TZLabel time={entry.updated_at} className="text-xs" /> : null,
        },
        {
            title: 'Scout',
            key: 'scout',
            className: `${NARROW}:hidden max-w-40`,
            render: (_, entry) => <ScoutCell skillName={entry.created_by_skill} />,
        },
        {
            title: 'Kind',
            key: 'kind',
            className: `${NARROW}:hidden w-24`,
            render: (_, entry) => <KindCell entryKey={entry.key} />,
        },
        {
            title: 'Key',
            key: 'key',
            className: `${NARROW}:hidden max-w-64`,
            render: (_, entry) => <KeyCell entry={entry} reportTitles={reportTitles} />,
        },
        {
            title: 'Note',
            key: 'note',
            className: `${NARROW}:hidden`,
            render: (_, entry) => <NotePreview content={entry.content} />,
        },
        {
            title: 'Carried',
            key: 'carried',
            className: `${NARROW}:hidden w-24 text-right`,
            render: (_, entry) => <CarriedCell entry={entry} />,
        },
        {
            title: 'Entry',
            key: 'stacked',
            className: `hidden ${NARROW}:table-cell`,
            render: (_, entry) => <StackedCell entry={entry} reportTitles={reportTitles} />,
        },
    ]

    return (
        <div className="@container/ledger">
            <LemonTable
                dataSource={filteredEntries ?? []}
                columns={columns}
                rowKey="key"
                size="small"
                pagination={{ pageSize: SCRATCHPAD_PAGE_SIZE }}
                expandable={{
                    // Expansion lives in the logic, not the table: the full body is fetched on
                    // expand, and the scout page's memory panel shares that cache.
                    isRowExpanded: (entry) => expandedKeys.includes(entry.key),
                    onRowExpand: (entry) => toggleEntry(entry.key),
                    onRowCollapse: (entry) => toggleEntry(entry.key),
                    expandedRowRender: (entry) => <ExpandedEntry entry={entry} />,
                }}
            />
        </div>
    )
}

function ScoutCell({ skillName }: { skillName: string | null | undefined }): JSX.Element {
    if (!skillName) {
        return <span className="text-xs text-muted">—</span>
    }
    if (skillName.startsWith(PIPELINE_PREFIX)) {
        return (
            <span className="truncate text-xs text-muted">
                {skillName.slice(PIPELINE_PREFIX.length)} (pipeline)
            </span>
        )
    }
    return (
        <Link to={urls.inboxScout(skillName)} subtle className="truncate text-xs">
            {stripScoutPrefix(skillName)}
        </Link>
    )
}

function KindCell({ entryKey }: { entryKey: string }): JSX.Element {
    const kind = scratchpadKindOf(entryKey)
    if (!kind) {
        return <span className="text-xs text-muted">—</span>
    }
    return (
        <LemonTag type={KIND_TAG_TYPE[kind] ?? 'muted'} size="small">
            {kind}
        </LemonTag>
    )
}

/**
 * The key, or the report it belongs to. Scouts namespace their per-report bookkeeping by report
 * UUID, and a raw UUID tells a reader nothing — so once the title is resolved the row names the
 * report and links to it, and falls back to the shortened UUID while it is not.
 */
function KeyCell({
    entry,
    reportTitles,
}: {
    entry: ScratchpadEntryApi
    reportTitles: Record<string, string | null>
}): JSX.Element {
    const topic = scratchpadTopicOf(entry.key)
    if (topic && isReportUuid(topic)) {
        const title = reportTitles[topic]
        return (
            <Tooltip title={entry.key}>
                <Link to={urls.inboxReport('reports', topic)} subtle className="truncate text-xs">
                    Report: {title || shortenUuid(topic)}
                </Link>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={entry.key}>
            <span className="block truncate font-mono text-xs text-primary">{entry.key}</span>
        </Tooltip>
    )
}

function NotePreview({ content }: { content: string | null | undefined }): JSX.Element {
    if (!content) {
        return <span className="text-xs italic text-muted">No content.</span>
    }
    return (
        <LemonMarkdown lowKeyHeadings disableImages="all" className="line-clamp-1 text-xs [&_*]:inline [&_*]:text-xs">
            {content}
        </LemonMarkdown>
    )
}

/**
 * Days the entry has been carried forward — a large number means the fleet keeps re-touching this
 * learning rather than deriving it again. An expiry replaces it, because a memory about to lapse is
 * the more urgent thing to know and the row has one slot.
 */
function CarriedCell({ entry }: { entry: ScratchpadEntryApi }): JSX.Element {
    if (entry.expires_at) {
        return (
            <Tooltip title={`Expires ${dayjs(entry.expires_at).format('D MMM YYYY, h:mm A')}`}>
                <span className="whitespace-nowrap text-xs text-warning">
                    exp {dayjs(entry.expires_at).format('D MMM')}
                </span>
            </Tooltip>
        )
    }
    const days = carriedDays(entry)
    return (
        <span className="whitespace-nowrap text-xs text-muted">{days === null ? '—' : days < 1 ? 'new' : `${days} d`}</span>
    )
}

/** Every column's data in one cell, for a panel too narrow to hold six of them. */
function StackedCell({
    entry,
    reportTitles,
}: {
    entry: ScratchpadEntryApi
    reportTitles: Record<string, string | null>
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1 py-0.5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                {entry.updated_at && <TZLabel time={entry.updated_at} className="text-xs text-muted" />}
                <ScoutCell skillName={entry.created_by_skill} />
                <KindCell entryKey={entry.key} />
                <span className="flex-1" />
                <CarriedCell entry={entry} />
            </div>
            <KeyCell entry={entry} reportTitles={reportTitles} />
            <NotePreview content={entry.content} />
        </div>
    )
}

/**
 * The open row: the note as its author wrote it (markdown, not the raw markup the cards showed),
 * plus where it came from and how long it has held. The list carries previews only, so a long
 * body arrives after the expand — until it lands the preview stays on screen under a skeleton.
 */
function ExpandedEntry({ entry }: { entry: ScratchpadEntryApi }): JSX.Element {
    const { fullContentByKey, loadingContentKeys } = useValues(scratchpadLogic)

    // `hasOwn` guards against a key like `constructor` resolving to an inherited prototype value.
    const content = Object.hasOwn(fullContentByKey, entry.key) ? fullContentByKey[entry.key] : entry.content
    const isLoadingContent = loadingContentKeys.includes(entry.key)
    const days = carriedDays(entry)

    return (
        <div className="flex flex-col gap-2 px-2 py-2">
            {content ? (
                <LemonMarkdown lowKeyHeadings disableImages="all" className="text-xs">
                    {content}
                </LemonMarkdown>
            ) : (
                <span className="text-xs italic text-muted">No content.</span>
            )}
            {isLoadingContent && <LemonSkeleton className="h-4 w-2/3" />}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 text-xs text-tertiary">
                {entry.created_at && (
                    <span>
                        Created <TZLabel time={entry.created_at} className="text-xs" />
                    </span>
                )}
                {days !== null && days >= 1 && <span>Carried forward {days === 1 ? '1 day' : `${days} days`}</span>}
                {entry.expires_at ? (
                    <span className="text-warning">
                        Expires <TZLabel time={entry.expires_at} className="text-xs" />
                    </span>
                ) : (
                    <span>Durable, no expiry</span>
                )}
                <span className="flex-1" />
                {entry.created_by_run_url && (
                    <Link to={entry.created_by_run_url} className="shrink-0">
                        Open the run that last wrote it
                    </Link>
                )}
            </div>
        </div>
    )
}

function carriedDays(entry: ScratchpadEntryApi): number | null {
    if (!entry.created_at || !entry.updated_at) {
        return null
    }
    return dayjs(entry.updated_at).diff(dayjs(entry.created_at), 'day')
}
