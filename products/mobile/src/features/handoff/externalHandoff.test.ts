import { Linking, Platform } from 'react-native'

import { externalHandoffPrompt, externalHandoffUrl, openExternalHandoff } from './externalHandoff'
import { buildReportImplementationPrompt } from './prompt'

const REPORT = {
    repository: 'example/mobile-app',
    prompt: buildReportImplementationPrompt(
        { id: 'report-123' },
        'https://us.example.com/project/2/reports/report-123'
    ),
}
const originalOS = Platform.OS

beforeEach(() => jest.clearAllMocks())

afterEach(() => {
    Platform.OS = originalOS
    jest.restoreAllMocks()
})

test.each(['claude', 'codex'] as const)('%s preserves the complete prompt and repository context', (target) => {
    const report = { ...REPORT, prompt: `${REPORT.prompt}\nInvestigate “slow & broken” #123?\n日本語` }
    const url = new URL(externalHandoffUrl(target, report))
    expect(url.searchParams.get(target === 'claude' ? 'q' : 'prompt')).toBe(externalHandoffPrompt(report))
    if (target === 'claude') {
        expect(url.protocol).toBe('claude:')
        expect(url.host).toBe('code')
        expect(url.pathname).toBe('/new')
        expect(url.searchParams.get('repo')).toBe('example/mobile-app')
        expect([...url.searchParams.keys()]).toEqual(['q', 'repo'])
    } else {
        expect(url.origin + url.pathname).toBe('https://chatgpt.com/')
        expect(url.searchParams.get('prompt')).toContain('Use the example/mobile-app repository.')
        // Only the draft parameter: do not turn this into a q= query or claim to select a project.
        expect([...url.searchParams.keys()]).toEqual(['prompt'])
    }
})

test.each([undefined, 'https://github.com/example/app', 'example/app&environment=other'])(
    'does not route an unrecognized repository: %s',
    (repository) => {
        const report = { ...REPORT, repository }
        expect(new URL(externalHandoffUrl('claude', report)).searchParams.has('repo')).toBe(false)
        expect(new URL(externalHandoffUrl('codex', report)).searchParams.has('originUrl')).toBe(false)
        expect(externalHandoffPrompt(report)).toContain('Confirm the correct repository with me')
    }
)

test('failed native launches explain the fallback without exposing the report URL', async () => {
    Platform.OS = 'ios'
    const open = jest.spyOn(Linking, 'openURL').mockRejectedValue(new Error(`No handler: ${REPORT.prompt}`))
    await expect(openExternalHandoff('codex', REPORT)).rejects.toThrow('copy the prompt')
    expect(open).toHaveBeenCalledWith(externalHandoffUrl('codex', REPORT))
})

test.each(['ios', 'android'] as const)(
    'dispatches the Claude mobile composer on %s with the full prompt',
    async (os) => {
        Platform.OS = os
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true)
        await openExternalHandoff('claude', REPORT)
        const url = new URL(open.mock.calls[0]?.[0] ?? '')
        expect(`${url.protocol}//${url.host}${url.pathname}`).toBe('claude://code/new')
        expect(url.searchParams.get('q')).toBe(externalHandoffPrompt(REPORT))
        expect(url.searchParams.get('repo')).toBe(REPORT.repository)
    }
)

test.each(['ios', 'android'] as const)('opens the ChatGPT HTTPS prompt route on %s', async (os) => {
    Platform.OS = os
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true)
    await openExternalHandoff('codex', REPORT)
    expect(open).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith(
        `https://chatgpt.com/?prompt=${encodeURIComponent(externalHandoffPrompt(REPORT))}`
    )
})

test('web previews never dispatch links to desktop applications', async () => {
    Platform.OS = 'web'
    const open = jest.spyOn(Linking, 'openURL')
    await expect(openExternalHandoff('codex', REPORT)).rejects.toThrow('PostHog mobile app')
    expect(open).not.toHaveBeenCalled()
})
