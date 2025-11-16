import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCheck, IconSearch, IconShare, IconSort } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Breadcrumb } from '~/types'

import { SessionGroupSummaryDetailsMetadata } from './SessionGroupSummaryDetailsMetadata'
import { SessionGroupSummaryDetailsModal } from './SessionGroupSummaryDetailsModal'
import { SessionGroupSummarySceneLogicProps, sessionGroupSummarySceneLogic } from './sessionGroupSummarySceneLogic'
import {
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternsList,
    PatternAssignedEventSegmentContext,
    SeverityLevel,
} from './types'

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
        critical: { type: 'danger', color: 'bg-danger' },
        high: { type: 'warning', color: 'bg-warning' },
        medium: { type: 'success', color: 'bg-success' },
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

    return (
        <div className="flex flex-col gap-2 rounded border p-3 bg-bg-light">
            <div className="flex items-center justify-between gap-2">
                <h4 className="mb-0">{target_event.description}</h4>
                <Link
                    onClick={(e) => {
                        e.preventDefault()
                        onViewDetails()
                    }}
                    className="text-sm font-medium whitespace-nowrap cursor-pointer"
                >
                    View details
                </Link>
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

function FilterBar({
    sortBy,
    onSortChange,
}: {
    sortBy: 'severity' | 'session_count'
    onSortChange: (sortBy: 'severity' | 'session_count') => void
}): JSX.Element {
    const [searchValue, setSearchValue] = useState('')
    const sortLabel = sortBy === 'severity' ? 'Sort by severity' : 'Sort by session count'

    return (
        <div className="flex flex-wrap items-center gap-4 mb-4">
            <div className="flex-1 min-w-60">
                <LemonInput
                    type="search"
                    placeholder="Filter patterns by keyword..."
                    value={searchValue}
                    onChange={setSearchValue}
                    prefix={<IconSearch />}
                    fullWidth
                />
            </div>
            <LemonMenu
                items={[
                    {
                        label: 'Sort by severity',
                        icon: sortBy === 'severity' ? <IconCheck /> : undefined,
                        onClick: () => onSortChange('severity'),
                    },
                    {
                        label: 'Sort by session count',
                        icon: sortBy === 'session_count' ? <IconCheck /> : undefined,
                        onClick: () => onSortChange('session_count'),
                    },
                ]}
            >
                <LemonButton type="secondary" icon={<IconSort />}>
                    {sortLabel}
                </LemonButton>
            </LemonMenu>
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
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setVisibleCount((prev) => prev + 3)}
                        disabled={visibleCount >= pattern.events.length}
                    >
                        Show more examples
                    </LemonButton>
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
    const summary = JSON.parse(sessionGroupSummary?.summary || '{}') as EnrichedSessionGroupSummaryPatternsList

    const sortedPatterns = useMemo(() => {
        if (!summary.patterns) {
            return []
        }
        const patterns = [...summary.patterns]
        if (sortBy === 'severity') {
            return patterns.sort((a, b) => SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity])
        }
        return patterns.sort((a, b) => b.stats.sessions_affected - a.stats.sessions_affected)
    }, [summary.patterns, sortBy])
    const handleViewDetails = (
        pattern: EnrichedSessionGroupSummaryPattern,
        event: PatternAssignedEventSegmentContext
    ): void => {
        openSessionDetails(pattern.pattern_id, event.target_event.event_uuid)
    }
    const handleCloseModal = (): void => {
        closeSessionDetails()
    }
    const backBreadcrumb: Breadcrumb = {
        key: Scene.SessionGroupSummariesTable,
        name: 'Session summaries',
        path: urls.sessionSummaries(),
        iconType: 'insight/hog',
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
                        icon={<IconShare />}
                        onClick={() => void copyToClipboard(window.location.href, 'link')}
                    >
                        Share
                    </LemonButton>
                }
                forceBackTo={backBreadcrumb}
            />
            <div className="flex flex-wrap items-center gap-3 text-sm text-muted mb-2">
                <span>{totalSessions} sessions analyzed</span>
                <span className="hidden sm:inline">·</span>
                <span>{new Date(sessionGroupSummary.created_at).toLocaleString()}</span>
            </div>
            <div className="space-y-4">
                <FilterBar sortBy={sortBy} onSortChange={setSortBy} />
                <div className="flex flex-col gap-2">
                    {sortedPatterns.map((pattern) => (
                        <PatternCard
                            key={pattern.pattern_id}
                            pattern={pattern}
                            onViewDetails={(event) => handleViewDetails(pattern, event)}
                        />
                    ))}
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
