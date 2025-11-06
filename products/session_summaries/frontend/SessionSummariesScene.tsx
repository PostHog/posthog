import { useState } from 'react'

import { IconDownload, IconSearch, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, Link } from '@posthog/lemon-ui'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: SessionSummariesScene,
}

// Type definitions
interface SessionKeyAction {
    event_id: string
    event_uuid: string
    session_id: string
    description: string
    abandonment: boolean
    confusion: boolean
    exception: string | null
    timestamp: string
    milliseconds_since_start: number
    window_id: string
    current_url: string
    event: string
    event_type: string | null
    event_index: number
}

interface SessionEvent {
    segment_name: string
    segment_outcome: string
    segment_success: boolean
    segment_index: number
    previous_events_in_segment: SessionKeyAction[]
    target_event: SessionKeyAction
    next_events_in_segment: SessionKeyAction[]
}

interface PatternStats {
    occurences: number
    sessions_affected: number
    sessions_affected_ratio: number
    segments_success_ratio: number
}

interface Pattern {
    pattern_id: number
    pattern_name: string
    pattern_description: string
    severity: 'critical' | 'high' | 'medium' | 'low'
    indicators: string[]
    events: SessionEvent[]
    stats: PatternStats
}

interface PatternsData {
    patterns: Pattern[]
}

type SeverityConfig = {
    type: 'danger' | 'warning' | 'success' | 'default'
    color: string
}

// Helper function to map severity to tag type and color
function getSeverityConfig(severity: Pattern['severity']): SeverityConfig {
    const configs: Record<Pattern['severity'], SeverityConfig> = {
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

const samplePatternsData: PatternsData = {
    patterns: [
        {
            pattern_id: 1,
            pattern_name: 'Pay-gate Blocks Core Settings',
            pattern_description:
                'Users trying to reach project or environment settings are shown a pay-gate and leave without upgrading, cutting short deeper engagement and any chance of conversion.',
            severity: 'critical',
            indicators: [
                'Event "pay gate shown" triggered while user is on settings-related URLs (e.g., /settings/project, /settings/environment)',
                'No subsequent "upgrade", "plan selected", or billing page visit before session end',
                'Session outcome marked unsuccessful with abandonment flagged in same segment as the pay gate',
                'User attempts to access the gated page again within the same session (more than 1 navigation to the same settings area) before giving up',
            ],
            events: [
                {
                    segment_name: 'Entered settings, hit paywall, and exited',
                    segment_outcome: 'Paywall blocked deeper settings; user did not upgrade and eventually left.',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: 'c0128dac',
                            event_uuid: '0197e8d6-2490-7cbc-96f1-f60012051e4b',
                            session_id: '0197e8d5-6eb2-79b6-95bf-5a5ba11edbfa',
                            description: 'Clicked Settings link from sidebar',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:00:37.138000-07:00',
                            milliseconds_since_start: 45190,
                            window_id: '0197e8d5-6eb2-79b6-95bf-5a5cba19880f',
                            current_url: 'https://eu.posthog.com/project/9822',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 57,
                        },
                    ],
                    target_event: {
                        event_id: 'c0128dac',
                        event_uuid: '0197e8d6-2490-7cbc-96f1-f60012051e4b',
                        session_id: '0197e8d5-6eb2-79b6-95bf-5a5ba11edbfa',
                        description: 'Paywall displayed repeatedly, blocking desired settings',
                        abandonment: true,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-07-08T00:00:37.915000-07:00',
                        milliseconds_since_start: 45967,
                        window_id: '0197e8d5-6eb2-79b6-95bf-5a5cba19880f',
                        current_url: 'https://eu.posthog.com/project/9822/settings/project',
                        event: 'pay gate shown',
                        event_type: null,
                        event_index: 59,
                    },
                    next_events_in_segment: [
                        {
                            event_id: 'c0128dac',
                            event_uuid: '0197e8d6-2490-7cbc-96f1-f60012051e4b',
                            session_id: '0197e8d5-6eb2-79b6-95bf-5a5ba11edbfa',
                            description: 'Navigated to Integrations page then became idle',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:00:40.056000-07:00',
                            milliseconds_since_start: 48108,
                            window_id: '0197e8d5-6eb2-79b6-95bf-5a5cba19880f',
                            current_url: 'https://eu.posthog.com/project/9822/settings/project-integrations',
                            event: '$pageview',
                            event_type: null,
                            event_index: 69,
                        },
                    ],
                },
                {
                    segment_name: 'Explore view settings – blocked by first pay-gate',
                    segment_outcome: 'Settings exploration halted by first pay gate.',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: 'ec36e684',
                            event_uuid: '0197e8d9-ea0b-79c4-8574-81e21cc8036e',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'User retries by clicking Reload but remains in limited view',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:04:13.908000-07:00',
                            milliseconds_since_start: 268053,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/activity/explore',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 19,
                        },
                    ],
                    target_event: {
                        event_id: 'ec36e684',
                        event_uuid: '0197e8d9-ea0b-79c4-8574-81e21cc8036e',
                        session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                        description: 'First pay gate appears when opening settings panel',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-07-08T00:04:45.135000-07:00',
                        milliseconds_since_start: 299280,
                        window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                        current_url: 'https://eu.posthog.com/project/67584/activity/explore#panel=settings',
                        event: 'pay gate shown',
                        event_type: null,
                        event_index: 38,
                    },
                    next_events_in_segment: [],
                },
                {
                    segment_name: 'Navigate to Insights & environment settings – second pay-gate',
                    segment_outcome: 'Insights opened but environment settings blocked again by pay gate.',
                    segment_success: false,
                    segment_index: 3,
                    previous_events_in_segment: [
                        {
                            event_id: '8a0fbb0f',
                            event_uuid: '0197e8db-c58c-72e6-b6cd-d3c263754943',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'Sidebar navigation to Product Analytics (Insights)',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:06:20.357000-07:00',
                            milliseconds_since_start: 394502,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/activity/explore#panel=settings',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 67,
                        },
                    ],
                    target_event: {
                        event_id: '8a0fbb0f',
                        event_uuid: '0197e8db-c58c-72e6-b6cd-d3c263754943',
                        session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                        description: 'Second pay gate blocks environment settings page',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-07-08T00:06:46.938000-07:00',
                        milliseconds_since_start: 421083,
                        window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                        current_url:
                            'https://eu.posthog.com/project/67584/settings/environment#web-analytics-authorized-urls',
                        event: 'pay gate shown',
                        event_type: null,
                        event_index: 93,
                    },
                    next_events_in_segment: [],
                },
                {
                    segment_name: 'Return to Activity & Live – frustration and project settings pay-gate',
                    segment_outcome: 'Live view frustration and yet another pay gate ended session.',
                    segment_success: false,
                    segment_index: 6,
                    previous_events_in_segment: [
                        {
                            event_id: '0ab80c47',
                            event_uuid: '0197e8e2-a2e9-7081-8e0f-37c961e74796',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'Rage-clicks on "AlloTools" list item indicating frustration',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-07-08T00:14:10.085000-07:00',
                            milliseconds_since_start: 864230,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/activity/live',
                            event: '$rageclick',
                            event_type: 'click',
                            event_index: 207,
                        },
                    ],
                    target_event: {
                        event_id: '0ab80c47',
                        event_uuid: '0197e8e2-a2e9-7081-8e0f-37c961e74796',
                        session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                        description: 'Pay gate shown on Project Settings page',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-07-08T00:14:16.927000-07:00',
                        milliseconds_since_start: 871072,
                        window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                        current_url: 'https://eu.posthog.com/project/67584/settings/project',
                        event: 'pay gate shown',
                        event_type: null,
                        event_index: 213,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '0ab80c47',
                            event_uuid: '0197e8e2-a2e9-7081-8e0f-37c961e74796',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'Dead click followed by copying validation message',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-07-08T00:15:22.858000-07:00',
                            milliseconds_since_start: 937003,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/settings/project',
                            event: '$dead_click',
                            event_type: 'click',
                            event_index: 223,
                        },
                    ],
                },
            ],
            stats: {
                occurences: 4,
                sessions_affected: 2,
                sessions_affected_ratio: 0.67,
                segments_success_ratio: 0.0,
            },
        },
        {
            pattern_id: 2,
            pattern_name: 'Frustration Click Loops',
            pattern_description:
                'After hitting a blocker or unclear UI state, users repeatedly click or toggle the same element (rage-clicks, rapid checkbox switches, reload spamming), signalling confusion and potential churn.',
            severity: 'high',
            indicators: [
                '"$rageclick" or "$dead_click" events recorded on the same target element',
                '"confusion": true on multiple consecutive events within a 10-second window',
                'More than 3 identical clicks/toggles on the same control without state change (e.g., checkbox rapidly on/off, repeated Reload button presses)',
                'Frustration sequence followed by idle time or session exit without completing intended task',
            ],
            events: [
                {
                    segment_name: 'Initial price-calculator setup',
                    segment_outcome: 'Customized initial pricing inputs, brief checkbox indecision resolved quickly',
                    segment_success: true,
                    segment_index: 0,
                    previous_events_in_segment: [
                        {
                            event_id: 'ab81df96',
                            event_uuid: '0197e8d6-6ff4-7abf-861b-58ed46233c10',
                            session_id: '0197e8d5-6f25-7310-a1d9-00f7557f4b8f',
                            description: 'Changed monthly event volume input',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:00:50.886000-07:00',
                            milliseconds_since_start: 59024,
                            window_id: '0197e8d5-6f25-7310-a1d9-00f8d751ee76',
                            current_url: 'https://posthog.com/pricing?calculator',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 5,
                        },
                    ],
                    target_event: {
                        event_id: 'ab81df96',
                        event_uuid: '0197e8d6-6ff4-7abf-861b-58ed46233c10',
                        session_id: '0197e8d5-6f25-7310-a1d9-00f7557f4b8f',
                        description: 'Rapidly toggled Website analytics checkbox multiple times',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-07-08T00:00:57.138000-07:00',
                        milliseconds_since_start: 65275,
                        window_id: '0197e8d5-6f25-7310-a1d9-00f8d751ee76',
                        current_url: 'https://posthog.com/pricing?calculator',
                        event: '$autocapture',
                        event_type: 'click',
                        event_index: 7,
                    },
                    next_events_in_segment: [
                        {
                            event_id: 'ab81df96',
                            event_uuid: '0197e8d6-6ff4-7abf-861b-58ed46233c10',
                            session_id: '0197e8d5-6f25-7310-a1d9-00f7557f4b8f',
                            description: 'Opened "explain event types" help section',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:01:03.475000-07:00',
                            milliseconds_since_start: 71613,
                            window_id: '0197e8d5-6f25-7310-a1d9-00f8d751ee76',
                            current_url: 'https://posthog.com/pricing?calculator',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 13,
                        },
                    ],
                },
                {
                    segment_name: 'Return to Activity & Live – frustration and project settings pay-gate',
                    segment_outcome: 'Live view frustration and yet another pay gate ended session.',
                    segment_success: false,
                    segment_index: 6,
                    previous_events_in_segment: [],
                    target_event: {
                        event_id: '6a28908e',
                        event_uuid: '0197e8e2-8626-796a-8711-41f657435816',
                        session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                        description: 'Rage-clicks on "AlloTools" list item indicating frustration',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-07-08T00:14:10.085000-07:00',
                        milliseconds_since_start: 864230,
                        window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                        current_url: 'https://eu.posthog.com/project/67584/activity/live',
                        event: '$rageclick',
                        event_type: 'click',
                        event_index: 207,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '6a28908e',
                            event_uuid: '0197e8e2-8626-796a-8711-41f657435816',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'Pay gate shown on Project Settings page',
                            abandonment: true,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:14:16.927000-07:00',
                            milliseconds_since_start: 871072,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/settings/project',
                            event: 'pay gate shown',
                            event_type: null,
                            event_index: 213,
                        },
                        {
                            event_id: '6a28908e',
                            event_uuid: '0197e8e2-8626-796a-8711-41f657435816',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'Dead click followed by copying validation message',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-07-08T00:15:22.858000-07:00',
                            milliseconds_since_start: 937003,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/settings/project',
                            event: '$dead_click',
                            event_type: 'click',
                            event_index: 223,
                        },
                    ],
                },
                {
                    segment_name: 'Return to Activity & Live – frustration and project settings pay-gate',
                    segment_outcome: 'Live view frustration and yet another pay gate ended session.',
                    segment_success: false,
                    segment_index: 6,
                    previous_events_in_segment: [
                        {
                            event_id: '47e65f6d',
                            event_uuid: '0197e8e3-b0eb-7a2b-be7d-d040d686ee19',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'Rage-clicks on "AlloTools" list item indicating frustration',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-07-08T00:14:10.085000-07:00',
                            milliseconds_since_start: 864230,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/activity/live',
                            event: '$rageclick',
                            event_type: 'click',
                            event_index: 207,
                        },
                        {
                            event_id: '47e65f6d',
                            event_uuid: '0197e8e3-b0eb-7a2b-be7d-d040d686ee19',
                            session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                            description: 'Pay gate shown on Project Settings page',
                            abandonment: true,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-07-08T00:14:16.927000-07:00',
                            milliseconds_since_start: 871072,
                            window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                            current_url: 'https://eu.posthog.com/project/67584/settings/project',
                            event: 'pay gate shown',
                            event_type: null,
                            event_index: 213,
                        },
                    ],
                    target_event: {
                        event_id: '47e65f6d',
                        event_uuid: '0197e8e3-b0eb-7a2b-be7d-d040d686ee19',
                        session_id: '0197e8d5-5a41-7628-8954-ab652f7afed0',
                        description: 'Dead click followed by copying validation message',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-07-08T00:15:22.858000-07:00',
                        milliseconds_since_start: 937003,
                        window_id: '0197e8d5-5a42-73e2-885c-1b98f1841598',
                        current_url: 'https://eu.posthog.com/project/67584/settings/project',
                        event: '$dead_click',
                        event_type: 'click',
                        event_index: 223,
                    },
                    next_events_in_segment: [],
                },
            ],
            stats: {
                occurences: 3,
                sessions_affected: 2,
                sessions_affected_ratio: 0.67,
                segments_success_ratio: 0.5,
            },
        },
    ],
}

// Session Example Card Component
function SessionExampleCard({ event }: { event: SessionEvent }): JSX.Element {
    const { target_event, segment_outcome } = event

    return (
        <div className="flex flex-col gap-2 rounded border p-3 bg-bg-light">
            <div className="flex items-center justify-between gap-2">
                <h4 className="mb-0">{target_event.description}</h4>
                <Link to="#" className="text-sm font-medium whitespace-nowrap">
                    View details
                </Link>
            </div>
            <p className="text-xs text-muted mb-1">{target_event.session_id}</p>
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
            <LemonInput
                type="search"
                placeholder="Filter patterns by name or keyword..."
                value={searchValue}
                onChange={setSearchValue}
                prefix={<IconSearch />}
                fullWidth
            />
            <LemonButton type="secondary" icon={<IconDownload />}>
                Export
            </LemonButton>
        </div>
    )
}

// Pattern Card Component
function PatternCard({ pattern }: { pattern: Pattern }): JSX.Element {
    const severityConfig = getSeverityConfig(pattern.severity)

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
        <div className="p-4 bg-bg-3000">
            <p className="mb-3 text-sm font-medium">Examples from sessions:</p>
            <div className="flex flex-col gap-3">
                {pattern.events.map((event, index) => (
                    <SessionExampleCard key={`${pattern.pattern_id}-${index}`} event={event} />
                ))}
            </div>
            {pattern.events.length > 0 && (
                <div className="mt-4 flex justify-center">
                    <LemonButton type="secondary" size="small">
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
        />
    )
}

// Main Scene Component
export function SessionSummariesScene(): JSX.Element {
    const totalSessions = samplePatternsData.patterns.reduce((sum, pattern) => sum + pattern.stats.sessions_affected, 0)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Session summary report"
                description={`${totalSessions} sessions analyzed`}
                resourceType={{
                    type: sceneConfigurations[Scene.SessionSummaries]?.iconType || 'default_icon_type',
                }}
            />
            <div className="space-y-4">
                <FilterBar />
                <div className="flex flex-col gap-2">
                    {samplePatternsData.patterns.map((pattern) => (
                        <PatternCard key={pattern.pattern_id} pattern={pattern} />
                    ))}
                </div>
            </div>
        </SceneContent>
    )
}
