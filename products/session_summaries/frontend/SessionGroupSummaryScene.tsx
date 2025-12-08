import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconSearch, IconShare, IconSort } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonSkeleton,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { debounce } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SessionGroupSummaryDetailsMetadata } from './SessionGroupSummaryDetailsMetadata'
import { SessionGroupSummaryDetailsModal } from './SessionGroupSummaryDetailsModal'
import { SessionGroupSummarySceneLogicProps, sessionGroupSummarySceneLogic } from './sessionGroupSummarySceneLogic'
import {
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternsList,
    PatternAssignedEventSegmentContext,
    SeverityLevel,
} from './types'
import { getIssueTags } from './utils'

export const scene: SceneExport<SessionGroupSummarySceneLogicProps> = {
    component: SessionGroupSummary,
    logic: sessionGroupSummarySceneLogic,
    paramsToProps: ({ params: { sessionGroupId } }) => ({ id: sessionGroupId }),
}

type SeverityConfig = {
    type: 'danger' | 'warning' | 'success' | 'default'
    color: string
}

function getSeverityConfig(severity: SeverityLevel): SeverityConfig {
    const configs: Record<SeverityLevel, SeverityConfig> = {
        // bg-danger
        critical: { type: 'danger', color: 'bg-danger' },
        high: { type: 'warning', color: 'bg-yellow-700' },
        medium: { type: 'warning', color: 'bg-warning' },
        low: { type: 'default', color: 'bg-muted' },
    }
    return configs[severity]
}

function capitalizeFirst(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1)
}

function SessionGroupSummaryLoadingSkeleton(): JSX.Element {
    return (
        <div className="space-y-4">
            <LemonSkeleton className="h-20" />
            <LemonSkeleton className="h-32" />
            <LemonSkeleton className="h-32" />
        </div>
    )
}

function SessionExampleCard({
    event,
    onViewDetails,
}: {
    event: PatternAssignedEventSegmentContext
    onViewDetails: () => void
}): JSX.Element {
    const { target_event, segment_outcome } = event

    const issueTags = getIssueTags(target_event)

    return (
        <div className="flex flex-col gap-2 rounded border p-3 bg-bg-light">
            <div className="flex items-center justify-between gap-2">
                <Tooltip title="View details" placement="right">
                    <h4 className="mb-0 text-link hover:underline cursor-pointer" onClick={onViewDetails}>
                        {target_event.description}
                        <span className="text-link ml-1">
                            <IconPlayCircle />
                        </span>
                    </h4>
                </Tooltip>
                {issueTags.length > 0 && <div className="flex items-center gap-1">{issueTags}</div>}
            </div>
            <div className="mb-2">
                <SessionGroupSummaryDetailsMetadata event={event} />
            </div>
            <p className="text-xs font-normal text-muted-alt mb-0">
                <b>Outcome:</b> {segment_outcome}
            </p>
        </div>
    )
}

export type IssueTypeFilter = 'blocking_error' | 'non_blocking_error' | 'abandonment' | 'confusion'

function FilterBar({
    searchValue,
    onSearchChange,
    issueTypeFilters,
    onIssueTypeFilterChange,
    filteredCount,
    totalCount,
    issueTypeCounts,
}: {
    searchValue: string
    onSearchChange: (value: string) => void
    issueTypeFilters: Set<IssueTypeFilter>
    onIssueTypeFilterChange: (filter: IssueTypeFilter) => void
    filteredCount: number
    totalCount: number
    issueTypeCounts: Record<IssueTypeFilter, number>
}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-6 mb-4 items-center">
            <span className="text-sm text-muted-alt">
                Showing {filteredCount} of {totalCount} issues
            </span>
            <div className="flex items-center gap-2">
                {(
                    [
                        ['blocking_error', 'Blocking'],
                        ['abandonment', 'Abandonment'],
                        ['confusion', 'Confusion'],
                        ['non_blocking_error', 'Non-blocking'],
                    ] as const
                ).map(([key, label]) => {
                    const isActive = issueTypeFilters.has(key)
                    const count = issueTypeCounts[key]
                    return (
                        <LemonCheckbox
                            key={key}
                            checked={isActive}
                            onChange={() => onIssueTypeFilterChange(key)}
                            label={
                                <>
                                    {label} <span className="text-muted-alt">({count})</span>
                                </>
                            }
                            size="small"
                            bordered
                        />
                    )
                })}
            </div>
            <div className="flex-1 min-w-60">
                <LemonInput
                    type="search"
                    placeholder="Filter issues by keyword..."
                    value={searchValue}
                    onChange={onSearchChange}
                    prefix={<IconSearch />}
                    fullWidth
                />
            </div>
        </div>
    )
}

function PatternCard({
    pattern,
    onViewDetails,
}: {
    pattern: EnrichedSessionGroupSummaryPattern
    onViewDetails: (event: PatternAssignedEventSegmentContext) => void
}): JSX.Element {
    const [visibleCount, setVisibleCount] = useState(3)
    const severityConfig = getSeverityConfig(pattern.severity)

    const handleCollapseChange = (activeKey: number | null): void => {
        // Reset visible count when panel is closed
        if (activeKey === null) {
            setVisibleCount(3)
        }
    }

    const header = (
        <div className="py-3 px-1">
            <div>
                <h3 className="text-base font-medium mb-0">{pattern.pattern_name}</h3>
                <div className="flex flex-wrap items-center gap-2 text-sm text-muted mb-2">
                    <span>
                        {pattern.stats.sessions_affected} session{pattern.stats.sessions_affected > 1 ? 's' : ''}
                    </span>
                    <span className="hidden sm:inline">·</span>
                    <span>{(pattern.stats.sessions_affected_ratio * 100).toFixed(0)}%</span>
                    <span className="hidden sm:inline">·</span>
                    <div className="flex items-center gap-1.5">
                        <div className={`size-2 rounded-full ${severityConfig.color}`} />
                        <div className="text-sm font-normal mb-0">{capitalizeFirst(pattern.severity)}</div>
                    </div>
                    {/* TODO: Enable thumbs up/down for feedback */}
                    {/* <span className="hidden sm:inline">·</span>
                    <div className="hidden sm:flex items-center gap-2">
                        <LemonButton size="xsmall" type="tertiary" icon={<IconThumbsUp />} />
                        <LemonButton size="xsmall" type="tertiary" icon={<IconThumbsDown />} />
                    </div> */}
                </div>
            </div>
            <p className="text-sm text-muted-alt mb-0">{pattern.pattern_description}</p>
        </div>
    )

    const content = (
        <div className="p-2 bg-bg-3000">
            <p className="mb-3 text-sm font-medium">Examples from sessions:</p>
            <div className="flex flex-col gap-2">
                {pattern.events.slice(0, visibleCount).map((event, index) => (
                    <SessionExampleCard
                        key={`${pattern.pattern_id}-${index}`}
                        event={event}
                        onViewDetails={() => onViewDetails(event)}
                    />
                ))}
            </div>
            {pattern.events.length > 3 && (
                <div className="mt-4 flex justify-center gap-2">
                    {visibleCount > 3 && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => setVisibleCount((prev) => Math.max(prev - 3, 3))}
                        >
                            Show fewer examples
                        </LemonButton>
                    )}
                    {visibleCount < pattern.events.length && (
                        <LemonButton type="secondary" size="small" onClick={() => setVisibleCount((prev) => prev + 3)}>
                            Show more examples
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )

    return (
        <LemonCollapse
            panels={[
                {
                    key: pattern.pattern_id,
                    header,
                    content,
                },
            ]}
            size="small"
            onChange={handleCollapseChange}
        />
    )
}

const SEVERITY_ORDER: Record<SeverityLevel, number> = {
    critical: 4,
    high: 3,
    medium: 2,
    low: 1,
}

export function SessionGroupSummary(): JSX.Element {
    const {
        sessionGroupSummary,
        sessionGroupSummaryLoading,
        sessionGroupSummaryMissing,
        accessDeniedToSessionGroupSummary,
        selectedEvent,
    } = useValues(sessionGroupSummarySceneLogic)
    const { openSessionDetails, closeSessionDetails } = useActions(sessionGroupSummarySceneLogic)
    const [sortBy, setSortBy] = useState<'severity' | 'session_count'>('severity')
    const [searchValue, setSearchValue] = useState('')
    const [debouncedSearchValue, setDebouncedSearchValue] = useState('')
    const [issueTypeFilters, setIssueTypeFilters] = useState<Set<IssueTypeFilter>>(() => new Set(['blocking_error']))

    const handleIssueTypeFilterChange = (filter: IssueTypeFilter): void => {
        setIssueTypeFilters((prev) => {
            const next = new Set(prev)
            if (next.has(filter)) {
                next.delete(filter)
            } else {
                next.add(filter)
            }
            return next
        })
    }
    const summary = useMemo(() => {
        return JSON.parse(sessionGroupSummary?.summary || '{}') as EnrichedSessionGroupSummaryPatternsList
    }, [sessionGroupSummary?.summary])

    const debouncedSetSearch = useRef(debounce((value: string) => setDebouncedSearchValue(value), 100)).current

    useEffect(() => {
        debouncedSetSearch(searchValue)
    }, [searchValue, debouncedSetSearch])

    const matchesIssueTypeFilter = (event: PatternAssignedEventSegmentContext): boolean => {
        if (issueTypeFilters.size === 0) {
            return true
        }
        const { target_event } = event
        if (issueTypeFilters.has('blocking_error') && target_event.exception === 'blocking') {
            return true
        }
        if (issueTypeFilters.has('non_blocking_error') && target_event.exception === 'non-blocking') {
            return true
        }
        if (issueTypeFilters.has('abandonment') && target_event.abandonment) {
            return true
        }
        if (issueTypeFilters.has('confusion') && target_event.confusion) {
            return true
        }
        return false
    }

    const filteredPatterns = useMemo(() => {
        if (!summary.patterns) {
            return []
        }
        const trimmedSearch = debouncedSearchValue.trim().toLowerCase()
        return summary.patterns
            .map((pattern) => {
                const filteredEvents = pattern.events.filter((event) => {
                    if (!matchesIssueTypeFilter(event)) {
                        return false
                    }
                    if (trimmedSearch) {
                        return (
                            event.target_event.description.toLowerCase().includes(trimmedSearch) ||
                            event.segment_outcome.toLowerCase().includes(trimmedSearch)
                        )
                    }
                    return true
                })
                if (filteredEvents.length === 0) {
                    return null
                }
                return {
                    ...pattern,
                    events: filteredEvents,
                }
            })
            .filter((pattern): pattern is EnrichedSessionGroupSummaryPattern => pattern !== null)
        // eslint-disable-next-line react-hooks/exhaustive-deps -- matchesIssueTypeFilter only depends on issueTypeFilters which is already in deps
    }, [summary.patterns, debouncedSearchValue, issueTypeFilters])

    const sortedPatterns = useMemo(() => {
        const patterns = [...filteredPatterns]
        if (sortBy === 'severity') {
            return patterns.sort((a, b) => SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity])
        }
        return patterns.sort((a, b) => b.stats.sessions_affected - a.stats.sessions_affected)
    }, [filteredPatterns, sortBy])

    const filteredIssuesCount = useMemo(() => {
        return sortedPatterns.reduce((sum, pattern) => sum + pattern.events.length, 0)
    }, [sortedPatterns])

    const totalIssuesCount = useMemo(() => {
        if (!summary.patterns) {
            return 0
        }
        return summary.patterns.reduce((sum, pattern) => sum + pattern.events.length, 0)
    }, [summary.patterns])

    const issueTypeCounts = useMemo(() => {
        const counts: Record<IssueTypeFilter, number> = {
            blocking_error: 0,
            non_blocking_error: 0,
            abandonment: 0,
            confusion: 0,
        }
        if (!summary.patterns) {
            return counts
        }
        for (const pattern of summary.patterns) {
            for (const event of pattern.events) {
                const { target_event } = event
                if (target_event.exception === 'blocking') {
                    counts.blocking_error++
                }
                if (target_event.exception === 'non-blocking') {
                    counts.non_blocking_error++
                }
                if (target_event.abandonment) {
                    counts.abandonment++
                }
                if (target_event.confusion) {
                    counts.confusion++
                }
            }
        }
        return counts
    }, [summary.patterns])
    const handleViewDetails = (
        pattern: EnrichedSessionGroupSummaryPattern,
        event: PatternAssignedEventSegmentContext
    ): void => {
        openSessionDetails(pattern.pattern_id, event.target_event.event_uuid)
    }
    const handleCloseModal = (): void => {
        closeSessionDetails()
    }
    if (sessionGroupSummaryLoading) {
        return (
            <SceneContent>
                <SessionGroupSummaryLoadingSkeleton />
            </SceneContent>
        )
    }
    if (accessDeniedToSessionGroupSummary) {
        return (
            <SceneContent>
                <LemonBanner type="error">You don't have permission to view this session group summary.</LemonBanner>
            </SceneContent>
        )
    }
    if (sessionGroupSummaryMissing) {
        return (
            <SceneContent>
                <LemonBanner type="error">Session group summary not found.</LemonBanner>
            </SceneContent>
        )
    }
    if (!sessionGroupSummary) {
        return (
            <SceneContent>
                <LemonBanner type="error">Failed to load session group summary.</LemonBanner>
            </SceneContent>
        )
    }
    const totalSessions = sessionGroupSummary.session_ids.length
    return (
        <SceneContent>
            <SceneTitleSection
                name={sessionGroupSummary.title}
                resourceType={{
                    type: sceneConfigurations[Scene.SessionGroupSummary]?.iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconShare />}
                        onClick={() => void copyToClipboard(window.location.href, 'link')}
                    >
                        Share
                    </LemonButton>
                }
                forceBackTo={{
                    key: Scene.SessionGroupSummariesTable,
                    name: 'Session summaries',
                    path: urls.sessionSummaries(),
                    iconType: 'notebook',
                }}
            />
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted">
                <div className="flex items-center gap-3">
                    <LemonTag type="warning">BETA</LemonTag>
                    <span>{totalSessions} sessions analyzed</span>
                    <span className="hidden sm:inline">·</span>
                    <span>{new Date(sessionGroupSummary.created_at).toLocaleString()}</span>
                </div>
                <LemonMenu
                    items={[
                        {
                            label: 'Sort by severity',
                            icon: sortBy === 'severity' ? <IconCheck /> : undefined,
                            onClick: () => setSortBy('severity'),
                        },
                        {
                            label: 'Sort by session count',
                            icon: sortBy === 'session_count' ? <IconCheck /> : undefined,
                            onClick: () => setSortBy('session_count'),
                        },
                    ]}
                >
                    <LemonButton type="secondary" size="small" icon={<IconSort />}>
                        {sortBy === 'severity' ? 'Sort by severity' : 'Sort by session count'}
                    </LemonButton>
                </LemonMenu>
            </div>
            <div className="space-y-4">
                <FilterBar
                    searchValue={searchValue}
                    onSearchChange={setSearchValue}
                    issueTypeFilters={issueTypeFilters}
                    onIssueTypeFilterChange={handleIssueTypeFilterChange}
                    filteredCount={filteredIssuesCount}
                    totalCount={totalIssuesCount}
                    issueTypeCounts={issueTypeCounts}
                />
                <div className="flex flex-col gap-2">
                    {sortedPatterns.length === 0 && summary.patterns && summary.patterns.length > 0 ? (
                        <p className="text-muted">No patterns match your search</p>
                    ) : (
                        sortedPatterns.map((pattern) => (
                            <PatternCard
                                key={pattern.pattern_id}
                                pattern={pattern}
                                onViewDetails={(event) => handleViewDetails(pattern, event)}
                            />
                        ))
                    )}
                </div>
            </div>

            <SessionGroupSummaryDetailsModal
                isOpen={selectedEvent !== null}
                onClose={handleCloseModal}
                event={selectedEvent}
            />
        </SceneContent>
    )
}
