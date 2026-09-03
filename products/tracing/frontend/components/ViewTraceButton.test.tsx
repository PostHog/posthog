import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { ViewTraceButton } from './ViewTraceButton'

describe('ViewTraceButton', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Tracing]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
    })

    afterEach(() => cleanup())

    const renderButton = (props: Parameters<typeof ViewTraceButton>[0]): void => {
        render(
            <Provider>
                <ViewTraceButton {...props} />
            </Provider>
        )
    }

    // A log row without a trace is the common case, not an edge case. Rendering the button anyway
    // would link to `/tracing?trace=`, and one dead link teaches people to stop clicking it.
    it.each([
        ['an absent trace id', undefined],
        ['an empty trace id', ''],
        ['a null trace id', null],
    ])('renders nothing for %s', (_name, traceId) => {
        renderButton({ traceId })
        expect(screen.queryByText('View trace')).not.toBeInTheDocument()
    })

    it('renders nothing without tracing access, rather than a disabled button', () => {
        // Matches how the trace links logs already has behave.
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { [AccessControlResourceType.Tracing]: AccessControlLevel.None },
        } as AppContext

        renderButton({ traceId: 'abc123' })
        expect(screen.queryByText('View trace')).not.toBeInTheDocument()
    })

    it('links to the trace, anchored on the span and hinted with the timestamp', () => {
        renderButton({ traceId: 'abc123', spanId: 'def456', timestamp: '2026-06-11T08:00:00.000Z' })

        expect(screen.getByText('View trace').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining('trace=abc123')
        )
        // The timestamp bounds the cold-load query; without it the lookup scans the whole
        // retention window, because OTel trace ids embed no time.
        expect(screen.getByText('View trace').closest('a')?.getAttribute('href')).toContain('ts=')
    })
})
