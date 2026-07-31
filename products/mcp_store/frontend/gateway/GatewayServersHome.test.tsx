import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import { GatewayServersLoadError } from './GatewayServersHome'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonBanner: ({
        children,
        action,
    }: {
        children: ReactNode
        action: { children: ReactNode; onClick: () => void }
    }) => (
        <div>
            {children}
            <button onClick={action.onClick}>{action.children}</button>
        </div>
    ),
}))

describe('GatewayServersLoadError', () => {
    afterEach(cleanup)

    it.each([
        [false, "Couldn't load MCP servers. Try again."],
        [true, "Couldn't load this MCP server. Try again."],
    ])('renders a retryable load error for serverDetail=%s', (serverDetail, message) => {
        const onRetry = jest.fn()

        render(<GatewayServersLoadError serverDetail={serverDetail} onRetry={onRetry} />)

        expect(screen.getByText(message)).toBeInTheDocument()
        fireEvent.click(screen.getByText('Try again'))
        expect(onRetry).toHaveBeenCalledTimes(1)
    })
})
