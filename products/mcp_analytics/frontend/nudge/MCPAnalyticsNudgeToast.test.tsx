import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MCPAnalyticsNudgeToast } from './MCPAnalyticsNudgeToast'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

describe('MCPAnalyticsNudgeToast', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(async () => {
        useMocks({ get: { '/_preflight/': { cloud: true } } })
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        preflightLogic.mount()
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
    })

    afterEach(() => {
        cleanup()
        captureSpy.mockRestore()
    })

    it.each([
        ['copying the wizard command', 'Copy MCP analytics wizard command', 'mcp analytics nudge command copied'],
        ['clicking the setup button', 'Set up MCP analytics', 'mcp analytics nudge cta clicked'],
    ])('tracks %s', async (_, label, event) => {
        render(<MCPAnalyticsNudgeToast surface="dashboard" />)
        fireEvent.click(await screen.findByRole('button', { name: label }))
        expect(captureSpy).toHaveBeenCalledWith(event, { surface: 'dashboard' })
    })
})
