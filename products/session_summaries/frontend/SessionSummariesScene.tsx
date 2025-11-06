import { useState } from 'react'

import { IconChevronDown, IconDownload, IconSearch, IconSort, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, Link } from '@posthog/lemon-ui'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SessionDetailsModal } from './SessionDetailsModal'

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
            pattern_name: 'Session Replay load failures',
            pattern_description:
                'API errors on the Session Replay list or playlist endpoints prevent recordings from loading, often leading to immediate exits or rage-clicks.',
            severity: 'critical',
            indicators: [
                'One or more "client_request_failure" events on /replay/home or /replay/playlists directly after a page-view to the same URL',
                'More than 2 consecutive request failures for recording or playlist data within the same segment',
                'User leaves the Replay page less than 30 seconds after the first failure or shows "$rageclick" on Replay navigation',
                'Session outcome marked unsuccessful with summary mentioning "persistent API errors" or "blocking API error" on replay',
            ],
            events: [
                {
                    segment_name: 'Brief return to Session Replay then exit',
                    segment_outcome: 'Persistent API errors on replay home triggered quick exit',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: '3d99d89e',
                            event_uuid: '019a4f08-d17c-76db-8453-4a96fa840b06',
                            session_id: '019a4f03-f9ab-7def-b224-50061bb648d5',
                            description: 'Returned to Session Replay via sidebar',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T13:21:24.255000+00:00',
                            milliseconds_since_start: 230018,
                            window_id: '019a4f03-f9ab-7def-b224-5007bf6c1c49',
                            current_url: 'http://localhost:8010/project/4/llm-analytics',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 133,
                        },
                        {
                            event_id: '3d99d89e',
                            event_uuid: '019a4f08-d17c-76db-8453-4a96fa840b06',
                            session_id: '019a4f03-f9ab-7def-b224-50061bb648d5',
                            description: 'Session Replay API failures persist',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-04T13:22:40.069000+00:00',
                            milliseconds_since_start: 305832,
                            window_id: '019a4f03-f9ab-7def-b224-5007bf6c1c49',
                            current_url: 'http://localhost:8010/project/4/replay/home',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 145,
                        },
                    ],
                    target_event: {
                        event_id: '3d99d89e',
                        event_uuid: '019a4f08-d17c-76db-8453-4a96fa840b06',
                        session_id: '019a4f03-f9ab-7def-b224-50061bb648d5',
                        description: 'User left the application shortly after errors',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-11-04T13:22:49.351000+00:00',
                        milliseconds_since_start: 315114,
                        window_id: '019a4f03-f9ab-7def-b224-5007bf6c1c49',
                        current_url: 'http://localhost:8010/project/4/replay/home',
                        event: '$pageleave',
                        event_type: null,
                        event_index: 150,
                    },
                    next_events_in_segment: [],
                },
                {
                    segment_name: 'Navigate project 4 and hit playlist error',
                    segment_outcome: 'Blocking API error prevented viewing playlist, user abandoned flow',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: 'f58cfb54',
                            event_uuid: '019a4f54-6faf-71d9-978d-3b941d086eb3',
                            session_id: '019a4f50-779b-7e43-8cfa-b6399764415f',
                            description: 'Opened project 4 dashboard',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T14:44:44.715000+00:00',
                            milliseconds_since_start: 219681,
                            window_id: '019a4f53-d224-7e90-87f7-3d8f6caa0f4f',
                            current_url: 'http://localhost:8010/project/4',
                            event: '$opt_in',
                            event_type: null,
                            event_index: 106,
                        },
                        {
                            event_id: 'f58cfb54',
                            event_uuid: '019a4f54-6faf-71d9-978d-3b941d086eb3',
                            session_id: '019a4f50-779b-7e43-8cfa-b6399764415f',
                            description: 'Attempted to open saved playlist',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T14:45:24.872000+00:00',
                            milliseconds_since_start: 259838,
                            window_id: '019a4f53-d224-7e90-87f7-3d8f6caa0f4f',
                            current_url: 'http://localhost:8010/project/5/new',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 157,
                        },
                        {
                            event_id: 'f58cfb54',
                            event_uuid: '019a4f54-6faf-71d9-978d-3b941d086eb3',
                            session_id: '019a4f50-779b-7e43-8cfa-b6399764415f',
                            description: 'Playlist fetch returned API failure (toast shown)',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-04T14:45:25.048000+00:00',
                            milliseconds_since_start: 260014,
                            window_id: '019a4f53-d224-7e90-87f7-3d8f6caa0f4f',
                            current_url: 'http://localhost:8010/project/5/replay/playlists/9C6uvm4c',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 159,
                        },
                    ],
                    target_event: {
                        event_id: 'f58cfb54',
                        event_uuid: '019a4f54-6faf-71d9-978d-3b941d086eb3',
                        session_id: '019a4f50-779b-7e43-8cfa-b6399764415f',
                        description: 'Recording load error "Non-OK response" ended playlist attempt',
                        abandonment: true,
                        confusion: false,
                        exception: 'blocking',
                        timestamp: '2025-11-04T14:45:27.994000+00:00',
                        milliseconds_since_start: 262960,
                        window_id: '019a4f53-d224-7e90-87f7-3d8f6caa0f4f',
                        current_url: 'http://localhost:8010/project/5/replay/playlists/9C6uvm4c',
                        event: '$exception',
                        event_type: null,
                        event_index: 169,
                    },
                    next_events_in_segment: [],
                },
                {
                    segment_name: 'Create several feature flags (with frustration and errors)',
                    segment_outcome: 'Created three feature flags after initial rage-clicks and non-blocking errors.',
                    segment_success: true,
                    segment_index: 3,
                    previous_events_in_segment: [],
                    target_event: {
                        event_id: '0b5d9f2c',
                        event_uuid: '019a4f57-533f-7b70-ade1-1e6a0b8a1d4b',
                        session_id: '019a4f50-75a1-70d1-a7a1-485893e9ff2d',
                        description: 'Rage-click on Session replay link (slow response)',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-11-04T14:48:34.389000+00:00',
                        milliseconds_since_start: 449840,
                        window_id: '019a4f57-2535-7c83-877b-b87bb80115e3',
                        current_url: 'http://localhost:8010/project/6/replay/home',
                        event: '$rageclick',
                        event_type: 'click',
                        event_index: 273,
                    },
                    next_events_in_segment: [],
                },
                {
                    segment_name: 'Repeated reloads and API failures on Session Summaries',
                    segment_outcome: 'Multiple API failures blocked summaries; user left after frustration',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [],
                    target_event: {
                        event_id: '5c9670d7',
                        event_uuid: '019a58b4-d69a-7590-8af5-2467dbb1bd04',
                        session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                        description: 'Left and reloaded page after failure',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-11-06T10:27:17.867000+00:00',
                        milliseconds_since_start: 534885,
                        window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: '$pageleave',
                        event_type: null,
                        event_index: 53,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '5c9670d7',
                            event_uuid: '019a58b4-d69a-7590-8af5-2467dbb1bd04',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: "Placeholder 'Coming soon' displayed instead of summaries",
                            abandonment: false,
                            confusion: false,
                            exception: 'blocking',
                            timestamp: '2025-11-06T10:27:24.970000+00:00',
                            milliseconds_since_start: 541988,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 62,
                        },
                        {
                            event_id: '5c9670d7',
                            event_uuid: '019a58b4-d69a-7590-8af5-2467dbb1bd04',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Feature flag error surfaced',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-06T10:29:03.077000+00:00',
                            milliseconds_since_start: 640095,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'onFeatureFlags error',
                            event_type: null,
                            event_index: 92,
                        },
                        {
                            event_id: '5c9670d7',
                            event_uuid: '019a58b4-d69a-7590-8af5-2467dbb1bd04',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: "Spinner then 'Coming soon' placeholder displayed again",
                            abandonment: false,
                            confusion: false,
                            exception: 'blocking',
                            timestamp: '2025-11-06T10:29:35.214000+00:00',
                            milliseconds_since_start: 672232,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 103,
                        },
                    ],
                },
                {
                    segment_name: 'Repeated reloads and API failures on Session Summaries',
                    segment_outcome: 'Multiple API failures blocked summaries; user left after frustration',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: '1daaccfe',
                            event_uuid: '019a58b4-f270-7aa6-9276-21ffdd8e2b92',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Left and reloaded page after failure',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-11-06T10:27:17.867000+00:00',
                            milliseconds_since_start: 534885,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$pageleave',
                            event_type: null,
                            event_index: 53,
                        },
                    ],
                    target_event: {
                        event_id: '1daaccfe',
                        event_uuid: '019a58b4-f270-7aa6-9276-21ffdd8e2b92',
                        session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                        description: "Placeholder 'Coming soon' displayed instead of summaries",
                        abandonment: false,
                        confusion: false,
                        exception: 'blocking',
                        timestamp: '2025-11-06T10:27:24.970000+00:00',
                        milliseconds_since_start: 541988,
                        window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: 'client_request_failure',
                        event_type: null,
                        event_index: 62,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '1daaccfe',
                            event_uuid: '019a58b4-f270-7aa6-9276-21ffdd8e2b92',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Feature flag error surfaced',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-06T10:29:03.077000+00:00',
                            milliseconds_since_start: 640095,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'onFeatureFlags error',
                            event_type: null,
                            event_index: 92,
                        },
                        {
                            event_id: '1daaccfe',
                            event_uuid: '019a58b4-f270-7aa6-9276-21ffdd8e2b92',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: "Spinner then 'Coming soon' placeholder displayed again",
                            abandonment: false,
                            confusion: false,
                            exception: 'blocking',
                            timestamp: '2025-11-06T10:29:35.214000+00:00',
                            milliseconds_since_start: 672232,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 103,
                        },
                        {
                            event_id: '1daaccfe',
                            event_uuid: '019a58b4-f270-7aa6-9276-21ffdd8e2b92',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'User left page after repeated failures',
                            abandonment: true,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-06T10:31:49.846000+00:00',
                            milliseconds_since_start: 806864,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$pageleave',
                            event_type: null,
                            event_index: 134,
                        },
                    ],
                },
                {
                    segment_name: 'Repeated reloads and API failures on Session Summaries',
                    segment_outcome: 'Multiple API failures blocked summaries; user left after frustration',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: '6b59374d',
                            event_uuid: '019a58b6-ede5-7bd1-a486-bb23575539f3',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Left and reloaded page after failure',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-11-06T10:27:17.867000+00:00',
                            milliseconds_since_start: 534885,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$pageleave',
                            event_type: null,
                            event_index: 53,
                        },
                        {
                            event_id: '6b59374d',
                            event_uuid: '019a58b6-ede5-7bd1-a486-bb23575539f3',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: "Placeholder 'Coming soon' displayed instead of summaries",
                            abandonment: false,
                            confusion: false,
                            exception: 'blocking',
                            timestamp: '2025-11-06T10:27:24.970000+00:00',
                            milliseconds_since_start: 541988,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 62,
                        },
                        {
                            event_id: '6b59374d',
                            event_uuid: '019a58b6-ede5-7bd1-a486-bb23575539f3',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Feature flag error surfaced',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-06T10:29:03.077000+00:00',
                            milliseconds_since_start: 640095,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'onFeatureFlags error',
                            event_type: null,
                            event_index: 92,
                        },
                    ],
                    target_event: {
                        event_id: '6b59374d',
                        event_uuid: '019a58b6-ede5-7bd1-a486-bb23575539f3',
                        session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                        description: "Spinner then 'Coming soon' placeholder displayed again",
                        abandonment: false,
                        confusion: false,
                        exception: 'blocking',
                        timestamp: '2025-11-06T10:29:35.214000+00:00',
                        milliseconds_since_start: 672232,
                        window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: 'client_request_failure',
                        event_type: null,
                        event_index: 103,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '6b59374d',
                            event_uuid: '019a58b6-ede5-7bd1-a486-bb23575539f3',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'User left page after repeated failures',
                            abandonment: true,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-06T10:31:49.846000+00:00',
                            milliseconds_since_start: 806864,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$pageleave',
                            event_type: null,
                            event_index: 134,
                        },
                    ],
                },
                {
                    segment_name: 'Repeated reloads and API failures on Session Summaries',
                    segment_outcome: 'Multiple API failures blocked summaries; user left after frustration',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: '569ec36a',
                            event_uuid: '019a58b8-fd43-7be5-b466-7d60ed48972e',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: "Placeholder 'Coming soon' displayed instead of summaries",
                            abandonment: false,
                            confusion: false,
                            exception: 'blocking',
                            timestamp: '2025-11-06T10:27:24.970000+00:00',
                            milliseconds_since_start: 541988,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 62,
                        },
                        {
                            event_id: '569ec36a',
                            event_uuid: '019a58b8-fd43-7be5-b466-7d60ed48972e',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Feature flag error surfaced',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-06T10:29:03.077000+00:00',
                            milliseconds_since_start: 640095,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'onFeatureFlags error',
                            event_type: null,
                            event_index: 92,
                        },
                        {
                            event_id: '569ec36a',
                            event_uuid: '019a58b8-fd43-7be5-b466-7d60ed48972e',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: "Spinner then 'Coming soon' placeholder displayed again",
                            abandonment: false,
                            confusion: false,
                            exception: 'blocking',
                            timestamp: '2025-11-06T10:29:35.214000+00:00',
                            milliseconds_since_start: 672232,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 103,
                        },
                    ],
                    target_event: {
                        event_id: '569ec36a',
                        event_uuid: '019a58b8-fd43-7be5-b466-7d60ed48972e',
                        session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                        description: 'User left page after repeated failures',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-11-06T10:31:49.846000+00:00',
                        milliseconds_since_start: 806864,
                        window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: '$pageleave',
                        event_type: null,
                        event_index: 134,
                    },
                    next_events_in_segment: [],
                },
                {
                    segment_name: 'Final attempt still failing, session ends',
                    segment_outcome: 'Final reload also failed; session closed without viewing summaries',
                    segment_success: false,
                    segment_index: 3,
                    previous_events_in_segment: [
                        {
                            event_id: 'e2109437',
                            event_uuid: '019a58c5-3e07-720f-a7bf-f14ad666be92',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Reloaded Session Summaries page',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-06T10:45:11.297000+00:00',
                            milliseconds_since_start: 1608315,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$opt_in',
                            event_type: null,
                            event_index: 149,
                        },
                    ],
                    target_event: {
                        event_id: 'e2109437',
                        event_uuid: '019a58c5-3e07-720f-a7bf-f14ad666be92',
                        session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                        description: 'Navigation failed; placeholder reloaded, no summaries',
                        abandonment: false,
                        confusion: false,
                        exception: 'blocking',
                        timestamp: '2025-11-06T10:45:12.873000+00:00',
                        milliseconds_since_start: 1609891,
                        window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: 'client_request_failure',
                        event_type: null,
                        event_index: 157,
                    },
                    next_events_in_segment: [
                        {
                            event_id: 'e2109437',
                            event_uuid: '019a58c5-3e07-720f-a7bf-f14ad666be92',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Dismissed info panel again',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-06T10:45:18.233000+00:00',
                            milliseconds_since_start: 1615251,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 161,
                        },
                        {
                            event_id: 'e2109437',
                            event_uuid: '019a58c5-3e07-720f-a7bf-f14ad666be92',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Session ended without success',
                            abandonment: true,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-06T10:45:34.116000+00:00',
                            milliseconds_since_start: 1631134,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$web_vitals',
                            event_type: null,
                            event_index: 163,
                        },
                    ],
                },
                {
                    segment_name: 'Final attempt still failing, session ends',
                    segment_outcome: 'Final reload also failed; session closed without viewing summaries',
                    segment_success: false,
                    segment_index: 3,
                    previous_events_in_segment: [
                        {
                            event_id: '8c5ff5ed',
                            event_uuid: '019a58c5-909a-7f39-8e04-e29ae94b9299',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Reloaded Session Summaries page',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-06T10:45:11.297000+00:00',
                            milliseconds_since_start: 1608315,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$opt_in',
                            event_type: null,
                            event_index: 149,
                        },
                        {
                            event_id: '8c5ff5ed',
                            event_uuid: '019a58c5-909a-7f39-8e04-e29ae94b9299',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Navigation failed; placeholder reloaded, no summaries',
                            abandonment: false,
                            confusion: false,
                            exception: 'blocking',
                            timestamp: '2025-11-06T10:45:12.873000+00:00',
                            milliseconds_since_start: 1609891,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 157,
                        },
                        {
                            event_id: '8c5ff5ed',
                            event_uuid: '019a58c5-909a-7f39-8e04-e29ae94b9299',
                            session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                            description: 'Dismissed info panel again',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-06T10:45:18.233000+00:00',
                            milliseconds_since_start: 1615251,
                            window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 161,
                        },
                    ],
                    target_event: {
                        event_id: '8c5ff5ed',
                        event_uuid: '019a58c5-909a-7f39-8e04-e29ae94b9299',
                        session_id: '019a58ac-ac6f-76db-b53f-4074ed3bb190',
                        description: 'Session ended without success',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-11-06T10:45:34.116000+00:00',
                        milliseconds_since_start: 1631134,
                        window_id: '019a58ac-ac6f-76db-b53f-40753db6688f',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: '$web_vitals',
                        event_type: null,
                        event_index: 163,
                    },
                    next_events_in_segment: [],
                },
                {
                    segment_name: 'Settings access blocked, user frustration',
                    segment_outcome: 'Paywall and API errors caused frustration and abandonment',
                    segment_success: false,
                    segment_index: 1,
                    previous_events_in_segment: [
                        {
                            event_id: 'f64a06fa',
                            event_uuid: '019a5a33-6b29-75e6-9cd2-2718ae2ab733',
                            session_id: '019a5a31-6bbd-7203-9766-90d9c8ad1eb4',
                            description: 'API request failures while loading data',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-06T17:24:59.934000+00:00',
                            milliseconds_since_start: 1190,
                            window_id: '019a5a31-6bbd-7203-9766-90dab9a64337',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 9,
                        },
                    ],
                    target_event: {
                        event_id: 'f64a06fa',
                        event_uuid: '019a5a33-6b29-75e6-9cd2-2718ae2ab733',
                        session_id: '019a5a31-6bbd-7203-9766-90d9c8ad1eb4',
                        description: 'Clicked settings link but hit paywall',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-11-06T17:25:10.613000+00:00',
                        milliseconds_since_start: 11869,
                        window_id: '019a5a31-6bbd-7203-9766-90dab9a64337',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: '$autocapture',
                        event_type: 'click',
                        event_index: 18,
                    },
                    next_events_in_segment: [
                        {
                            event_id: 'f64a06fa',
                            event_uuid: '019a5a33-6b29-75e6-9cd2-2718ae2ab733',
                            session_id: '019a5a31-6bbd-7203-9766-90d9c8ad1eb4',
                            description: 'Rage-clicks show frustration, user exits soon after',
                            abandonment: true,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-11-06T17:25:14.672000+00:00',
                            milliseconds_since_start: 15928,
                            window_id: '019a5a31-6bbd-7203-9766-90dab9a64337',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 20,
                        },
                    ],
                },
                {
                    segment_name: 'Settings access blocked, user frustration',
                    segment_outcome: 'Paywall and API errors caused frustration and abandonment',
                    segment_success: false,
                    segment_index: 1,
                    previous_events_in_segment: [
                        {
                            event_id: 'a958284c',
                            event_uuid: '019a5a33-7b18-78ed-8f6b-7a1042bcb624',
                            session_id: '019a5a31-6bbd-7203-9766-90d9c8ad1eb4',
                            description: 'API request failures while loading data',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-06T17:24:59.934000+00:00',
                            milliseconds_since_start: 1190,
                            window_id: '019a5a31-6bbd-7203-9766-90dab9a64337',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 9,
                        },
                        {
                            event_id: 'a958284c',
                            event_uuid: '019a5a33-7b18-78ed-8f6b-7a1042bcb624',
                            session_id: '019a5a31-6bbd-7203-9766-90d9c8ad1eb4',
                            description: 'Clicked settings link but hit paywall',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-11-06T17:25:10.613000+00:00',
                            milliseconds_since_start: 11869,
                            window_id: '019a5a31-6bbd-7203-9766-90dab9a64337',
                            current_url: 'http://localhost:8010/project/4/session-summaries',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 18,
                        },
                    ],
                    target_event: {
                        event_id: 'a958284c',
                        event_uuid: '019a5a33-7b18-78ed-8f6b-7a1042bcb624',
                        session_id: '019a5a31-6bbd-7203-9766-90d9c8ad1eb4',
                        description: 'Rage-clicks show frustration, user exits soon after',
                        abandonment: true,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-11-06T17:25:14.672000+00:00',
                        milliseconds_since_start: 15928,
                        window_id: '019a5a31-6bbd-7203-9766-90dab9a64337',
                        current_url: 'http://localhost:8010/project/4/session-summaries',
                        event: '$autocapture',
                        event_type: 'click',
                        event_index: 20,
                    },
                    next_events_in_segment: [],
                },
            ],
            stats: { occurences: 3, sessions_affected: 3, sessions_affected_ratio: 0.2, segments_success_ratio: 0.33 },
        },
        {
            pattern_id: 2,
            pattern_name: 'SQL editor cannot load',
            pattern_description:
                'Opening the in-product SQL editor repeatedly triggers request failures and exceptions, driving users away from the tool.',
            severity: 'high',
            indicators: [
                '"$pageview" to /sql immediately followed by "client_request_failure" on the same endpoint',
                'User revisits /sql 2 or more times within one session, each attempt ending in a failure',
                '"confusion": true or "$rageclick" recorded while on the SQL page',
                'Segment outcome or session outcome notes abandonment or exit after unresolved SQL errors',
            ],
            events: [
                {
                    segment_name: 'Deeper exploration, repeated SQL errors, opt-in and exit',
                    segment_outcome: 'Onboarding task done, repeated SQL errors caused abandonment and session end.',
                    segment_success: false,
                    segment_index: 2,
                    previous_events_in_segment: [
                        {
                            event_id: '02ba5df8',
                            event_uuid: '019a4f07-6353-7f91-b1e2-db4635abd455',
                            session_id: '019a4f03-fc15-778f-a19b-19e011e3ba40',
                            description: 'Completed an activation sidebar task',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T13:21:10.804000+00:00',
                            milliseconds_since_start: 206915,
                            window_id: '019a4f03-fc15-778f-a19b-19e1c3cc6aa6',
                            current_url: 'http://localhost:8010/project/6/web',
                            event: 'activation sidebar task completed',
                            event_type: null,
                            event_index: 38,
                        },
                        {
                            event_id: '02ba5df8',
                            event_uuid: '019a4f07-6353-7f91-b1e2-db4635abd455',
                            session_id: '019a4f03-fc15-778f-a19b-19e011e3ba40',
                            description: 'Frontend exception thrown while on SQL page',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-04T13:21:12.702000+00:00',
                            milliseconds_since_start: 208813,
                            window_id: '019a4f03-fc15-778f-a19b-19e1c3cc6aa6',
                            current_url: 'http://localhost:8010/project/6/sql#q=',
                            event: '$exception',
                            event_type: null,
                            event_index: 57,
                        },
                    ],
                    target_event: {
                        event_id: '02ba5df8',
                        event_uuid: '019a4f07-6353-7f91-b1e2-db4635abd455',
                        session_id: '019a4f03-fc15-778f-a19b-19e011e3ba40',
                        description: 'Returned to SQL editor after earlier failure',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-11-04T13:21:15.615000+00:00',
                        milliseconds_since_start: 211726,
                        window_id: '019a4f03-fc15-778f-a19b-19e1c3cc6aa6',
                        current_url: 'http://localhost:8010/project/6/activity/explore',
                        event: '$autocapture',
                        event_type: 'click',
                        event_index: 81,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '02ba5df8',
                            event_uuid: '019a4f07-6353-7f91-b1e2-db4635abd455',
                            session_id: '019a4f03-fc15-778f-a19b-19e011e3ba40',
                            description: 'SQL request failed again, indicating unresolved issue',
                            abandonment: false,
                            confusion: true,
                            exception: 'non-blocking',
                            timestamp: '2025-11-04T13:21:15.786000+00:00',
                            milliseconds_since_start: 211897,
                            window_id: '019a4f03-fc15-778f-a19b-19e1c3cc6aa6',
                            current_url: 'http://localhost:8010/project/6/sql#q=',
                            event: 'client_request_failure',
                            event_type: null,
                            event_index: 83,
                        },
                        {
                            event_id: '02ba5df8',
                            event_uuid: '019a4f07-6353-7f91-b1e2-db4635abd455',
                            session_id: '019a4f03-fc15-778f-a19b-19e011e3ba40',
                            description: 'Opted into product analytics before leaving',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T13:22:42.701000+00:00',
                            milliseconds_since_start: 298812,
                            window_id: '019a4f03-fc15-778f-a19b-19e1c3cc6aa6',
                            current_url: 'http://localhost:8010/project/6/replay/home',
                            event: '$opt_in',
                            event_type: null,
                            event_index: 94,
                        },
                    ],
                },
            ],
            stats: { occurences: 1, sessions_affected: 1, sessions_affected_ratio: 0.07, segments_success_ratio: 0.0 },
        },
        {
            pattern_id: 4,
            pattern_name: 'Creation flow frustration',
            pattern_description:
                'Users experience rage-clicks and abandonment when creating new items (heatmaps, feature flags, playlists) due to confusing forms or save-time errors.',
            severity: 'high',
            indicators: [
                'User clicks a "New…" or "Create" button (heatmap, feature flag, playlist) then quickly produces a "$rageclick" inside the form',
                '"client_request_failure" or blocking exception fired during the save/creation request',
                'Pageleave with "abandonment": true before the item is successfully created',
                'Multiple rapid clicks on the primary submit action within less than 5 seconds',
            ],
            events: [
                {
                    segment_name: 'Tried to create a new heatmap',
                    segment_outcome: 'Abandoned new heatmap after rage-click confusion',
                    segment_success: false,
                    segment_index: 1,
                    previous_events_in_segment: [
                        {
                            event_id: '93ce4749',
                            event_uuid: '019a4f51-8d54-79bb-a4aa-64596f716b8b',
                            session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                            description: 'Opened Heatmaps section',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T14:42:06.232000+00:00',
                            milliseconds_since_start: 47927,
                            window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                            current_url: 'http://localhost:8010/project/3/replay/home',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 54,
                        },
                        {
                            event_id: '93ce4749',
                            event_uuid: '019a4f51-8d54-79bb-a4aa-64596f716b8b',
                            session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                            description: 'Clicked New heatmap',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T14:42:09.326000+00:00',
                            milliseconds_since_start: 51021,
                            window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                            current_url: 'http://localhost:8010/project/3/heatmaps',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 58,
                        },
                    ],
                    target_event: {
                        event_id: '93ce4749',
                        event_uuid: '019a4f51-8d54-79bb-a4aa-64596f716b8b',
                        session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                        description: 'Rage-clicked URL field, indicating form frustration',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-11-04T14:42:16.028000+00:00',
                        milliseconds_since_start: 57723,
                        window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                        current_url: 'http://localhost:8010/project/3/heatmaps/new',
                        event: '$rageclick',
                        event_type: 'click',
                        event_index: 67,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '93ce4749',
                            event_uuid: '019a4f51-8d54-79bb-a4aa-64596f716b8b',
                            session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                            description: 'Left form without finalising heatmap',
                            abandonment: true,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T14:42:22.514000+00:00',
                            milliseconds_since_start: 64209,
                            window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                            current_url: 'http://localhost:8010/project/3/heatmaps/new',
                            event: '$autocapture',
                            event_type: 'change',
                            event_index: 83,
                        },
                    ],
                },
                {
                    segment_name: 'Tried to create a new heatmap',
                    segment_outcome: 'Abandoned new heatmap after rage-click confusion',
                    segment_success: false,
                    segment_index: 1,
                    previous_events_in_segment: [
                        {
                            event_id: 'e81933d1',
                            event_uuid: '019a4f51-a6a3-7594-8fd9-36804c8cc279',
                            session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                            description: 'Opened Heatmaps section',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T14:42:06.232000+00:00',
                            milliseconds_since_start: 47927,
                            window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                            current_url: 'http://localhost:8010/project/3/replay/home',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 54,
                        },
                        {
                            event_id: 'e81933d1',
                            event_uuid: '019a4f51-a6a3-7594-8fd9-36804c8cc279',
                            session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                            description: 'Clicked New heatmap',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-04T14:42:09.326000+00:00',
                            milliseconds_since_start: 51021,
                            window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                            current_url: 'http://localhost:8010/project/3/heatmaps',
                            event: '$autocapture',
                            event_type: 'click',
                            event_index: 58,
                        },
                        {
                            event_id: 'e81933d1',
                            event_uuid: '019a4f51-a6a3-7594-8fd9-36804c8cc279',
                            session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                            description: 'Rage-clicked URL field, indicating form frustration',
                            abandonment: false,
                            confusion: true,
                            exception: null,
                            timestamp: '2025-11-04T14:42:16.028000+00:00',
                            milliseconds_since_start: 57723,
                            window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                            current_url: 'http://localhost:8010/project/3/heatmaps/new',
                            event: '$rageclick',
                            event_type: 'click',
                            event_index: 67,
                        },
                    ],
                    target_event: {
                        event_id: 'e81933d1',
                        event_uuid: '019a4f51-a6a3-7594-8fd9-36804c8cc279',
                        session_id: '019a4f50-aa6c-74b9-9baa-b9c4da7afbd7',
                        description: 'Left form without finalising heatmap',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-11-04T14:42:22.514000+00:00',
                        milliseconds_since_start: 64209,
                        window_id: '019a4f50-aa6c-74b9-9baa-b9c56e311d10',
                        current_url: 'http://localhost:8010/project/3/heatmaps/new',
                        event: '$autocapture',
                        event_type: 'change',
                        event_index: 83,
                    },
                    next_events_in_segment: [],
                },
            ],
            stats: { occurences: 2, sessions_affected: 1, sessions_affected_ratio: 0.07, segments_success_ratio: 0.0 },
        },
        {
            pattern_id: 5,
            pattern_name: 'Background API noise',
            pattern_description:
                'Frequent non-blocking request failures appear across many pages, degrading perceived reliability even when tasks eventually succeed.',
            severity: 'medium',
            indicators: [
                'Session contains more than 5 "client_request_failure" events spread across different features (dashboards, surveys, replay, etc.)',
                'Error toasts shown while the user continues normal navigation or exploration',
                'No single blocking error, but session summaries mention "intermittent API failures" or "minor API hiccup"',
                'Occasional frustration signals (rage-clicks or confusions) without full abandonment',
            ],
            events: [
                {
                    segment_name: 'Deep replay filtering, AI notes & notebook editing',
                    segment_outcome: 'Lengthy analysis hampered by recurring API errors and rage-click frustration.',
                    segment_success: false,
                    segment_index: 4,
                    previous_events_in_segment: [
                        {
                            event_id: '923ec7da',
                            event_uuid: '019a543d-154c-7784-929d-dc7270243837',
                            session_id: '019a53b8-c37a-7d73-a7e8-24f8361585e5',
                            description: 'Copies AI-generated session summary',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-05T12:33:03.259000+00:00',
                            milliseconds_since_start: 4774154,
                            window_id: '019a53e7-20ec-7b49-9d00-2b7e8c50e286',
                            current_url: 'http://localhost:8010/project/6/replay/home',
                            event: '$copy_autocapture',
                            event_type: 'copy',
                            event_index: 295,
                        },
                        {
                            event_id: '923ec7da',
                            event_uuid: '019a543d-154c-7784-929d-dc7270243837',
                            session_id: '019a53b8-c37a-7d73-a7e8-24f8361585e5',
                            description: 'Views recording summary page',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-05T12:39:40.805000+00:00',
                            milliseconds_since_start: 5171700,
                            window_id: '019a53e7-20ec-7b49-9d00-2b7e8c50e286',
                            current_url: 'http://localhost:8010/project/6/replay/home',
                            event: 'session recording has duplicate snapshots',
                            event_type: null,
                            event_index: 403,
                        },
                        {
                            event_id: '923ec7da',
                            event_uuid: '019a543d-154c-7784-929d-dc7270243837',
                            session_id: '019a53b8-c37a-7d73-a7e8-24f8361585e5',
                            description: 'Server returned error toast while in notebook',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-05T12:50:48.016000+00:00',
                            milliseconds_since_start: 5838911,
                            window_id: '019a53e7-20ec-7b49-9d00-2b7e8c50e286',
                            current_url: 'http://localhost:8010/project/6/notebooks/1lMLDyvn',
                            event: '$exception',
                            event_type: null,
                            event_index: 448,
                        },
                    ],
                    target_event: {
                        event_id: '923ec7da',
                        event_uuid: '019a543d-154c-7784-929d-dc7270243837',
                        session_id: '019a53b8-c37a-7d73-a7e8-24f8361585e5',
                        description: 'Rage-clicks filter buttons after repeated failures',
                        abandonment: false,
                        confusion: true,
                        exception: null,
                        timestamp: '2025-11-05T13:38:00.664000+00:00',
                        milliseconds_since_start: 8671559,
                        window_id: '019a53e7-20ec-7b49-9d00-2b7e8c50e286',
                        current_url:
                            'http://localhost:8010/project/6/replay/home?filters=%7B%22filter_test_accounts%22%3Afalse%2C%22date_from%22%3A%22-3d%22%2C%22date_to%22%3Anull%2C%22filter_group%22%3A%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22key%22%3A%22%24session_id%22%2C%22value%22%3A%5B%22019a4f50-779b-7e43-8cfa-b6399764415f%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D%7D%5D%7D%2C%22duration%22%3A%5B%7B%22type%22%3A%22recording%22%2C%22key%22%3A%22active_seconds%22%2C%22value%22%3A5%2C%22operator%22%3A%22gt%22%7D%5D%2C%22order%22%3A%22start_time%22%2C%22order_direction%22%3A%22DESC%22%7D&sessionRecordingId=019a4f50-779b-7e43-8cfa-b6399764415f',
                        event: '$rageclick',
                        event_type: 'click',
                        event_index: 765,
                    },
                    next_events_in_segment: [
                        {
                            event_id: '923ec7da',
                            event_uuid: '019a543d-154c-7784-929d-dc7270243837',
                            session_id: '019a53b8-c37a-7d73-a7e8-24f8361585e5',
                            description: 'Toast error appears again during save attempt',
                            abandonment: false,
                            confusion: false,
                            exception: 'non-blocking',
                            timestamp: '2025-11-05T13:54:26.136000+00:00',
                            milliseconds_since_start: 9657031,
                            window_id: '019a53e7-20ec-7b49-9d00-2b7e8c50e286',
                            current_url:
                                'http://localhost:8010/project/6/replay/home?filters=%7B%22filter_test_accounts%22%3Afalse%2C%22date_from%22%3A%22-3d%22%2C%22date_to%22%3Anull%2C%22filter_group%22%3A%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22key%22%3A%22%24session_id%22%2C%22value%22%3A%5B%22019a4f50-779b-7e43-8cfa-b6399764415f%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D%7D%5D%7D%2C%22duration%22%3A%5B%7B%22type%22%3A%22recording%22%2C%22key%22%3A%22active_seconds%22%2C%22value%22%3A5%2C%22operator%22%3A%22gt%22%7D%5D%2C%22order%22%3A%22start_time%22%2C%22order_direction%22%3A%22DESC%22%7D&sessionRecordingId=019a4f50-779b-7e43-8cfa-b6399764415f',
                            event: 'toast error',
                            event_type: null,
                            event_index: 919,
                        },
                    ],
                },
                {
                    segment_name: 'Repeated replay reloads with persistent API failures',
                    segment_outcome: 'Continued failures and rage-clicks led to final abandonment.',
                    segment_success: false,
                    segment_index: 5,
                    previous_events_in_segment: [
                        {
                            event_id: '2988a4ed',
                            event_uuid: '019a5452-05b5-7e43-b1dc-8301d345f1ef',
                            session_id: '019a53b8-c37a-7d73-a7e8-24f8361585e5',
                            description: 'Re-opens replay home after previous exit',
                            abandonment: false,
                            confusion: false,
                            exception: null,
                            timestamp: '2025-11-05T13:55:55.957000+00:00',
                            milliseconds_since_start: 9746852,
                            window_id: '019a53e7-20ec-7b49-9d00-2b7e8c50e286',
                            current_url:
                                'http://localhost:8010/project/6/replay/home?filters=%7B%22filter_test_accounts%22%3Afalse%2C%22date_from%22%3A%22-3d%22%2C%22date_to%22%3Anull%2C%22filter_group%22%3A%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22key%22%3A%22%24session_id%22%2C%22value%22%3A%5B%22019a4f50-779b-7e43-8cfa-b6399764415f%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D%7D%5D%7D%2C%22duration%22%3A%5B%7B%22type%22%3A%22recording%22%2C%22key%22%3A%22active_seconds%22%2C%22value%22%3A5%2C%22operator%22%3A%22gt%22%7D%5D%2C%22order%22%3A%22start_time%22%2C%22order_direction%22%3A%22DESC%22%7D&sessionRecordingId=019a4f50-779b-7e43-8cfa-b6399764415f',
                            event: '$opt_in',
                            event_type: null,
                            event_index: 922,
                        },
                    ],
                    target_event: {
                        event_id: '2988a4ed',
                        event_uuid: '019a5452-05b5-7e43-b1dc-8301d345f1ef',
                        session_id: '019a53b8-c37a-7d73-a7e8-24f8361585e5',
                        description: 'Session ends shortly after copying summary',
                        abandonment: true,
                        confusion: false,
                        exception: null,
                        timestamp: '2025-11-05T14:00:52.990000+00:00',
                        milliseconds_since_start: 10043885,
                        window_id: '019a53e7-20ec-7b49-9d00-2b7e8c50e286',
                        current_url:
                            'http://localhost:8010/project/6/replay/home?filters=%7B%22filter_test_accounts%22%3Afalse%2C%22date_from%22%3A%22-3d%22%2C%22date_to%22%3Anull%2C%22filter_group%22%3A%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22key%22%3A%22%24session_id%22%2C%22value%22%3A%5B%22019a4f50-779b-7e43-8cfa-b6399764415f%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D%7D%5D%7D%2C%22duration%22%3A%5B%7B%22type%22%3A%22recording%22%2C%22key%22%3A%22active_seconds%22%2C%22value%22%3A5%2C%22operator%22%3A%22gt%22%7D%5D%2C%22order%22%3A%22start_time%22%2C%22order_direction%22%3A%22DESC%22%7D&sessionRecordingId=019a4f50-779b-7e43-8cfa-b6399764415f',
                        event: '$pageleave',
                        event_type: null,
                        event_index: 973,
                    },
                    next_events_in_segment: [],
                },
            ],
            stats: { occurences: 2, sessions_affected: 1, sessions_affected_ratio: 0.07, segments_success_ratio: 0.0 },
        },
    ],
}

// Session Example Card Component
function SessionExampleCard({ event, onViewDetails }: { event: SessionEvent; onViewDetails: () => void }): JSX.Element {
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
    pattern: Pattern
    onViewDetails: (event: SessionEvent) => void
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
export function SessionSummariesScene(): JSX.Element {
    const [selectedEvent, setSelectedEvent] = useState<SessionEvent | null>(null)
    const [isModalOpen, setIsModalOpen] = useState(false)

    const totalSessions = samplePatternsData.patterns.reduce((sum, pattern) => sum + pattern.stats.sessions_affected, 0)

    const handleViewDetails = (event: SessionEvent): void => {
        setSelectedEvent(event)
        setIsModalOpen(true)
    }

    const handleCloseModal = (): void => {
        setIsModalOpen(false)
        setSelectedEvent(null)
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Session Summaries Report - AI feedback sessions (last 3 days) "
                resourceType={{
                    type: sceneConfigurations[Scene.SessionSummaries]?.iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton type="secondary" icon={<IconDownload />}>
                        Export
                    </LemonButton>
                }
            />
            <div className="flex flex-wrap items-center gap-3 text-sm text-muted mb-2">
                <span>{totalSessions} sessions analyzed</span>
                <span className="hidden sm:inline">·</span>
                <span>PostHog App + Website</span>
                <span className="hidden sm:inline">·</span>
                <div className="flex items-center gap-1.5">
                    <div className="text-sm font-normal mb-0">11.05.2025 01:00:12</div>
                </div>
            </div>
            <div className="space-y-4">
                <FilterBar />
                <div className="flex flex-col gap-2">
                    {samplePatternsData.patterns.map((pattern) => (
                        <PatternCard key={pattern.pattern_id} pattern={pattern} onViewDetails={handleViewDetails} />
                    ))}
                </div>
            </div>

            {selectedEvent && (
                <SessionDetailsModal isOpen={isModalOpen} onClose={handleCloseModal} event={selectedEvent} />
            )}
        </SceneContent>
    )
}
