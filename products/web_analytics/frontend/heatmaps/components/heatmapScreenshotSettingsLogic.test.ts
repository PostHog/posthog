import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { screenshotAccessNotice, screenshotHostnameSuggestions } from '../heatmapScreenshotCookie'
import { heatmapScreenshotSettingsLogic } from './heatmapScreenshotSettingsLogic'

describe('screenshot access settings', () => {
    it('suggests exact toolbar hostnames without expanding wildcards or shared hosting domains', () => {
        expect(
            screenshotHostnameSuggestions([
                'https://WWW.Example.com/path',
                'https://www.example.com',
                'https://*.example.com',
                'https://customer.github.io',
                'http://127.0.0.1',
                'invalid',
            ])
        ).toEqual(['customer.github.io', 'www.example.com'])
    })

    it.each([
        ['https://www.example.com', true, ['www.example.com'], null],
        ['https://child.www.example.com', true, ['www.example.com'], 'without a bypass cookie'],
        ['https://www.example.com', false, ['www.example.com'], 'without a bypass cookie'],
        ['https://www.example.com', true, [], 'without a bypass cookie'],
        ['http://www.example.com', true, ['www.example.com'], 'uses HTTP'],
    ] as const)('explains cookie delivery for %s, secret=%s, approvals=%j', (url, hasSecret, hostnames, expected) => {
        const notice = screenshotAccessNotice(url, { allowed_hostnames: [...hostnames], has_secret: hasSecret })
        if (expected === null) {
            expect(notice).toBeNull()
        } else {
            expect(notice).toContain(expected)
        }
    })

    it('keeps toolbar suggestions unapproved until the admin saves, and preserves drafts on failure', async () => {
        useMocks({
            get: { '/api/projects/:id/heatmap_screenshot/settings/': { allowed_hostnames: [], has_secret: true } },
            patch: {
                '/api/projects/:id/heatmap_screenshot/settings/': () => [
                    400,
                    { type: 'validation_error', code: 'invalid_input', detail: 'Enter an exact hostname.' },
                ],
            },
        })
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, app_urls: ['https://www.example.com'] })
        const logic = heatmapScreenshotSettingsLogic({ teamId: MOCK_DEFAULT_TEAM.id })
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ hostnames: [], settings: { allowed_hostnames: [], has_secret: true }, hasChanges: false })
        logic.actions.setHostnames(['https://www.example.com'])
        await expectLogic(logic, () => logic.actions.saveSettings())
            .toDispatchActions(['saveSettingsFailure'])
            .toMatchValues({
                hostnames: ['https://www.example.com'],
                settings: { allowed_hostnames: [], has_secret: true },
                hasChanges: true,
            })
        useMocks({
            patch: {
                '/api/projects/:id/heatmap_screenshot/settings/': {
                    allowed_hostnames: ['www.example.com'],
                    has_secret: true,
                },
            },
        })
        logic.actions.setHostnames(['www.example.com'])
        await expectLogic(logic, () => logic.actions.saveSettings())
            .toDispatchActions(['saveSettingsSuccess'])
            .toMatchValues({
                settings: { allowed_hostnames: ['www.example.com'], has_secret: true },
                hasChanges: false,
                saveError: null,
            })
        logic.unmount()
    })
})
