import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { mcpStoreLogic } from './mcpStoreLogic'
import { McpStoreSettings } from './McpStoreSettings'
import { McpGatewaySettings } from './settings/McpGatewaySettings'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('./settings/McpGatewaySettings', () => ({
    McpGatewaySettings: (): JSX.Element => <div>Gateway settings</div>,
}))

describe('McpStoreSettings', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(useValues).mockReturnValue({
            featureFlags: { [FEATURE_FLAGS.MCP_GATEWAY]: true },
        })
    })

    afterEach(() => {
        cleanup()
        jest.resetAllMocks()
    })

    it('renders gateway settings without mounting the legacy store logic when the gateway flag is enabled', () => {
        render(<McpStoreSettings />)

        expect(screen.getByText('Gateway settings')).toBeInTheDocument()
        expect(mcpStoreLogic.isMounted()).toBe(false)
    })

    it('keeps the existing Settings page as the fallback when the gateway flag is disabled', () => {
        jest.mocked(useValues).mockReturnValue({ featureFlags: { [FEATURE_FLAGS.MCP_GATEWAY]: false } })

        const element = McpStoreSettings()

        expect(element.type).not.toBe(McpGatewaySettings)
        expect(element.type.name).toBe('LegacyMcpStoreSettings')
    })
})
