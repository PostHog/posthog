import { useActions, useValues } from 'kea'

import { IconChevronDown, IconClock } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { scratchpadLogic } from '../../logics/scratchpadLogic'
import { scratchpadEntryBody, scratchpadEntryTitle } from '../../utils/scoutMemoryPresentation'
import { stripScoutPrefix } from '../../utils/scoutRunsWindow'
import { KIND_TAG_TYPE, scratchpadKindOf } from '../../utils/scratchpadKeys'

/**
 * One scratchpad entry, as the scout page's memory panel shows it. Shares the collapse/expand
 * grammar of the scout emission cards: a header (chevron · kind · key · expiry · updated time) that
 * stays visible, a 2-line preview when collapsed, the full body plus an attribution footer (which
 * scout created it, when, and how long it's been carried forward) when open.
 *
 * The list only carries previews, so a long entry's tail arrives on expand — until it lands, the
 * preview stays on screen with a skeleton under it rather than the card going blank.
 *
 * On a single scout's page pass `titled`: the entry's own opening heading leads in regular type and
 * the storage key drops out. Every entry there belongs to that scout, so a truncated key says less
 * than the name the scout gave the learning.
 *
 * The fleet-wide panel uses a ledger table instead; this card is the compact per-scout shape.
 */
export function ScratchpadEntryCard({
    entry,
    titled = false,
}: {
    entry: ScratchpadEntryApi
    titled?: boolean
}): JSX.Element {
    const { expandedKeys, fullContentByKey, loadingContentKeys } = useValues(scratchpadLogic)
    const { toggleEntry } = useActions(scratchpadLogic)

    const expanded = expandedKeys.includes(entry.key)
    const isLoadingContent = loadingContentKeys.includes(entry.key)
    // `hasOwn` guards against a key like `constructor` resolving to an inherited prototype value.
    const content = Object.hasOwn(fullContentByKey, entry.key) ? fullContentByKey[entry.key] : entry.content

    const kind = scratchpadKindOf(entry.key)
    const body = kind ? entry.key.slice(kind.length + 1) : entry.key
    const scoutName = entry.created_by_skill ? stripScoutPrefix(entry.created_by_skill) : null
    // Collapsed, a titled card previews the body under its own heading, so the heading isn't said
    // twice. Expanded, the entry reads as written.
    const preview = titled && !expanded ? scratchpadEntryBody(content) : content

    // How long the note has been carried forward: a fresh creation reads ~0 days; a large gap
    // means the fleet has re-touched this learning across many runs — the "gets sharper" signal.
    const maintainedDays =
        entry.created_at && entry.updated_at ? dayjs(entry.updated_at).diff(dayjs(entry.created_at), 'day') : 0

    return (
        <div className="flex flex-col rounded border border-primary bg-bg-light">
            <button
                type="button"
                onClick={() => toggleEntry(entry.key)}
                className="flex items-center gap-2 px-3 py-2 text-left"
                aria-expanded={expanded}
            >
                <IconChevronDown
                    className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '' : '-rotate-90'}`}
                />
                {kind && (
                    <LemonTag type={KIND_TAG_TYPE[kind] ?? 'muted'} size="small" className="shrink-0">
                        {kind}
                    </LemonTag>
                )}
                {titled ? (
                    <span className="truncate text-xs font-medium text-default">
                        {scratchpadEntryTitle(content, body)}
                    </span>
                ) : (
                    <span className="truncate font-mono text-xs text-primary">{body}</span>
                )}
                <span className="flex-1" />
                {/* Most memories are durable, so an expiry is the exception worth calling out on the
                    row itself — a memory about to lapse should not look identical to one that holds. */}
                {entry.expires_at && (
                    <span className="whitespace-nowrap text-[11px] text-warning">
                        exp {dayjs(entry.expires_at).format('D MMM')}
                    </span>
                )}
                {entry.updated_at && (
                    <span className="flex items-center gap-1 whitespace-nowrap text-[11px] text-muted">
                        <IconClock className="size-3" />
                        {humanFriendlyDetailedTime(entry.updated_at)}
                    </span>
                )}
            </button>

            <div className="px-3 pb-2 pl-9">
                {preview ? (
                    <pre
                        className={`m-0 whitespace-pre-wrap break-words font-mono text-xs text-primary ${
                            expanded ? '' : titled ? 'line-clamp-1' : 'line-clamp-2'
                        }`}
                    >
                        {preview}
                    </pre>
                ) : (
                    <span className="text-xs italic text-muted">No content.</span>
                )}

                {expanded && isLoadingContent && <LemonSkeleton className="h-4 w-2/3 mt-1" />}

                {expanded && (entry.created_at || scoutName || entry.created_by_run_id) && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 mt-2 text-xs text-tertiary">
                        {entry.created_at && <span>Created {humanFriendlyDetailedTime(entry.created_at)}</span>}
                        {maintainedDays >= 1 && (
                            <span>· carried forward {maintainedDays === 1 ? '1 day' : `${maintainedDays} days`}</span>
                        )}
                        {entry.expires_at ? (
                            <span>· expires {humanFriendlyDetailedTime(entry.expires_at)}</span>
                        ) : (
                            <span>· durable, no expiry</span>
                        )}
                        <span className="flex-1" />
                        {(scoutName || entry.created_by_run_id) && (
                            <span className="shrink-0">
                                by{' '}
                                {entry.created_by_run_url ? (
                                    <Link to={entry.created_by_run_url}>
                                        {scoutName ? `${scoutName} scout` : 'a scout'}
                                    </Link>
                                ) : scoutName ? (
                                    `${scoutName} scout`
                                ) : (
                                    'a scout'
                                )}
                            </span>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
