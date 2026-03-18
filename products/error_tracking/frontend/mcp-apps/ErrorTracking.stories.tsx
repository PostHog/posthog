import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryFn } from '@storybook/react'

import {
    ErrorDetailsView,
    type ErrorDetailsData,
    ErrorIssueListView,
    type ErrorIssueData,
    type ErrorIssueListData,
    ErrorIssueView,
    StackTraceView,
    type ExceptionData,
} from './index'

const meta: Meta = {
    title: 'MCP Apps/Error Tracking',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator doesn't have dark mode built-in by default so just disable this to avoid duplicated snapshots
            skipDarkMode: true,
        },
    },
}
export default meta

const activeIssue: ErrorIssueData = {
    id: 'issue-1',
    name: 'TypeError: Cannot read properties of undefined (reading "map")',
    description: 'Occurs in DashboardGrid.tsx when dashboard items are null.',
    status: 'active',
    first_seen: '2025-12-10T08:30:00Z',
    assignee: { id: 'user-42', type: 'user' },
}

const resolvedIssue: ErrorIssueData = {
    id: 'issue-2',
    name: 'RangeError: Maximum call stack size exceeded',
    description: 'Infinite recursion in recursive property filter rendering.',
    status: 'resolved',
    first_seen: '2025-11-15T14:00:00Z',
}

const issueWithLinks: ErrorIssueData = {
    id: 'issue-3',
    name: 'NetworkError: Failed to fetch /api/projects/1/insights',
    status: 'pending_release',
    first_seen: '2025-12-18T09:00:00Z',
    external_issues: [
        {
            external_url: 'https://github.com/PostHog/posthog/issues/12345',
            integration: { display_name: 'GitHub' },
        },
        {
            external_url: 'https://linear.app/posthog/issue/HOG-678',
            integration: { display_name: 'Linear' },
        },
    ],
}

const suppressedIssue: ErrorIssueData = {
    id: 'issue-4',
    name: 'Warning: Each child in a list should have a unique "key" prop',
    status: 'suppressed',
    first_seen: '2025-10-01T12:00:00Z',
}

export const Active: StoryFn = () => <ErrorIssueView issue={activeIssue} />
Active.storyName = 'Active issue'

export const Resolved: StoryFn = () => <ErrorIssueView issue={resolvedIssue} />
Resolved.storyName = 'Resolved issue'

export const WithExternalLinks: StoryFn = () => <ErrorIssueView issue={issueWithLinks} />
WithExternalLinks.storyName = 'Issue with external links'

const sampleListData: ErrorIssueListData = {
    count: 4,
    results: [activeIssue, resolvedIssue, issueWithLinks, suppressedIssue],
    _posthogUrl: 'https://us.posthog.com/project/1/error_tracking',
}

export const List: StoryFn = () => <ErrorIssueListView data={sampleListData} />
List.storyName = 'Issue list'

// -- Stack Trace stories --

const jsException: ExceptionData = {
    type: 'TypeError',
    value: 'Cannot read properties of undefined (reading "map")',
    mechanism: { handled: false, type: 'generic' },
    stacktrace: {
        type: 'resolved',
        frames: [
            {
                raw_id: 'frame-1',
                resolved_name: 'renderList',
                source: 'src/components/DashboardGrid.tsx',
                line: 42,
                column: 18,
                in_app: true,
                lang: 'javascript',
                resolved: true,
                context: {
                    before: [
                        { number: 40, line: '    const items = props.dashboardItems' },
                        { number: 41, line: '' },
                    ],
                    line: {
                        number: 42,
                        line: '    return items.map((item) => <DashboardTile key={item.id} {...item} />)',
                    },
                    after: [
                        { number: 43, line: '}' },
                        { number: 44, line: '' },
                    ],
                },
            },
            {
                raw_id: 'frame-2',
                resolved_name: 'DashboardGrid',
                source: 'src/components/DashboardGrid.tsx',
                line: 28,
                column: 5,
                in_app: true,
                lang: 'javascript',
                resolved: true,
                context: {
                    before: [
                        { number: 26, line: 'export function DashboardGrid({ dashboard }: Props) {' },
                        { number: 27, line: '    const filteredItems = filterItems(dashboard)' },
                    ],
                    line: { number: 28, line: '    return <div className="grid">{renderList(filteredItems)}</div>' },
                    after: [{ number: 29, line: '}' }],
                },
            },
            {
                raw_id: 'frame-3',
                resolved_name: 'renderWithHooks',
                source: 'node_modules/react-dom/cjs/react-dom.development.js',
                line: 14985,
                column: 18,
                in_app: false,
                lang: 'javascript',
                resolved: true,
            },
            {
                raw_id: 'frame-4',
                resolved_name: 'mountIndeterminateComponent',
                source: 'node_modules/react-dom/cjs/react-dom.development.js',
                line: 17811,
                column: 13,
                in_app: false,
                lang: 'javascript',
                resolved: true,
            },
        ],
    },
}

const pythonException: ExceptionData = {
    type: 'ValueError',
    value: "invalid literal for int() with base 10: 'abc'",
    stacktrace: {
        type: 'resolved',
        frames: [
            {
                raw_id: 'py-1',
                resolved_name: 'process_event',
                source: 'posthog/api/event.py',
                line: 156,
                in_app: true,
                lang: 'python',
                resolved: true,
                context: {
                    before: [
                        { number: 154, line: '    def process_event(self, data):' },
                        { number: 155, line: '        event_id = data.get("id")' },
                    ],
                    line: { number: 156, line: '        team_id = int(data["team_id"])' },
                    after: [{ number: 157, line: '        return Event.objects.create(team_id=team_id)' }],
                },
            },
            {
                raw_id: 'py-2',
                resolved_name: 'capture',
                source: 'posthog/api/capture.py',
                line: 89,
                in_app: true,
                lang: 'python',
                resolved: true,
            },
        ],
    },
}

export const StackTrace: StoryFn = () => <StackTraceView exceptions={[jsException]} />
StackTrace.storyName = 'Stack trace (JavaScript)'

export const PythonStackTrace: StoryFn = () => <StackTraceView exceptions={[pythonException]} />
PythonStackTrace.storyName = 'Stack trace (Python)'

export const ChainedExceptions: StoryFn = () => <StackTraceView exceptions={[jsException, pythonException]} />
ChainedExceptions.storyName = 'Chained exceptions'

const sampleErrorDetails: ErrorDetailsData = {
    results: [
        {
            uuid: 'evt-123',
            distinct_id: 'user-42',
            timestamp: '2025-12-15T14:30:00Z',
            properties: {
                $exception_list: [jsException],
                $exception_type: 'TypeError',
                $exception_message: 'Cannot read properties of undefined (reading "map")',
                $browser: 'Chrome',
                $browser_version: '120.0',
                $os: 'macOS',
                $os_version: '14.2',
                $lib: 'posthog-js',
                $current_url: 'https://app.posthog.com/dashboard/1',
            },
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/error_tracking/issue-1',
}

export const ErrorDetails: StoryFn = () => <ErrorDetailsView data={sampleErrorDetails} />
ErrorDetails.storyName = 'Error details with stack trace'
