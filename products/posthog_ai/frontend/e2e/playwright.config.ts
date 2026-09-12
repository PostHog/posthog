import { defineConfig } from '@playwright/test'

import regular from '../../../../playwright/playwright.config'

export default defineConfig({
    ...regular,
    testDir: '.',
    testMatch: 'recovery.ai.spec.ts',
    testIgnore: [],
    workers: 1,
    fullyParallel: false,
    timeout: 180_000,
    expect: { ...regular.expect, timeout: 60_000 },
    outputDir: `${process.env.AI_E2E_OUTPUT}/browser`,
    reporter: [
        ['list'],
        ['html', { outputFolder: `${process.env.AI_E2E_OUTPUT}/report`, open: 'never' }],
        ['junit', { outputFile: `${process.env.AI_E2E_OUTPUT}/junit.xml` }],
    ],
    use: { ...regular.use, baseURL: process.env.AI_E2E_BASE_URL, trace: 'on' },
})
