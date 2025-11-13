import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconDownload, IconSearch, IconSort, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Breadcrumb } from '~/types'

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

// Helper function to map severity to tag type and color
function getSeverityConfig(severity: SeverityLevel): SeverityConfig {
    const configs: Record<SeverityLevel, SeverityConfig> = {
        critical: { type: 'danger', color: 'bg-danger' },
        high: { type: 'warning', color: 'bg-warning' },
        medium: { type: 'success', color: 'bg-success' },
        low: { type: 'default', color: 'bg-muted' },
    }
    return configs[severity]
}

// Helper function to capitalize first letter
function capitalizeFirst(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1)
}

// Loading skeleton component
function SessionGroupSummaryLoadingSkeleton(): JSX.Element {
    return (
        <div className="space-y-4">
            <LemonSkeleton className="h-20" />
            <LemonSkeleton className="h-32" />
            <LemonSkeleton className="h-32" />
        </div>
    )
}

// Session Example Card Component
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
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted mb-2">
                <span>{target_event.session_id}</span>
                <span className="hidden sm:inline">·</span>
                <span>alex.l@posthog.com</span>
            </div>
            <p className="text-xs font-normal text-muted-alt mb-0">
                <b>Outcome:</b> {segment_outcome}
            </p>
        </div>
    )
}

// Filter Bar Component
function FilterBar(): JSX.Element {
    const [searchValue, setSearchValue] = useState('')

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
            <div className="flex rounded border">
                <LemonButton type="secondary" icon={<IconSort />} className="rounded-r-none border-r">
                    Sort by impact
                </LemonButton>
                <LemonButton type="secondary" icon={<IconChevronDown />} className="rounded-l-none" />
            </div>
        </div>
    )
}

// Pattern Card Component
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
                <div className="flex flex-wrap items-center gap-3 text-sm text-muted mb-2">
                    <span>{pattern.stats.sessions_affected} sessions</span>
                    <span className="hidden sm:inline">·</span>
                    <div className="flex items-center gap-1.5">
                        <div className={`size-2 rounded-full ${severityConfig.color}`} />
                        <div className="text-sm font-normal mb-0">{capitalizeFirst(pattern.severity)}</div>
                    </div>
                    <span className="hidden sm:inline">·</span>
                    <div className="hidden sm:flex items-center gap-2">
                        <LemonButton size="xsmall" type="tertiary" icon={<IconThumbsUp />} />
                        <LemonButton size="xsmall" type="tertiary" icon={<IconThumbsDown />} />
                    </div>
                </div>
            </div>
            <p className="text-sm text-muted-alt mb-0">{pattern.pattern_description}</p>
        </div>
    )

    const content = (
        <div className="p-2 bg-bg-3000">
            <p className="mb-3 text-sm font-medium">Examples from sessions:</p>
            <div className="flex flex-col gap-3">
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

// Main Scene Component
export function SessionGroupSummary(): JSX.Element {
    const {
        sessionGroupSummary,
        sessionGroupSummaryLoading,
        sessionGroupSummaryMissing,
        accessDeniedToSessionGroupSummary,
    } = useValues(sessionGroupSummarySceneLogic)
    const [selectedEvent, setSelectedEvent] = useState<PatternAssignedEventSegmentContext | null>(null)
    const [isModalOpen, setIsModalOpen] = useState(false)
    const summary = JSON.parse(sessionGroupSummary?.summary || '{}') as EnrichedSessionGroupSummaryPatternsList
    const handleViewDetails = (event: PatternAssignedEventSegmentContext): void => {
        setSelectedEvent(event)
        setIsModalOpen(true)
    }
    const handleCloseModal = (): void => {
        setIsModalOpen(false)
        setSelectedEvent(null)
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
                    <LemonButton type="secondary" icon={<IconDownload />}>
                        Export
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
                <FilterBar />
                <div className="flex flex-col gap-2">
                    {summary.patterns.map((pattern) => (
                        <PatternCard key={pattern.pattern_id} pattern={pattern} onViewDetails={handleViewDetails} />
                    ))}
                </div>
            </div>

            {selectedEvent && (
                <SessionGroupSummaryDetailsModal
                    isOpen={isModalOpen}
                    onClose={handleCloseModal}
                    event={selectedEvent}
                />
            )}
        </SceneContent>
    )
}
