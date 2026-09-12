import { defineConfig } from '@playwright/test'

import regular from '../../../../playwright/playwright.config'

export default defineConfig({
    ...regular,
    testDir: '.',
    testMatch: process.env.AI_E2E_SURFACE === '1' ? 'flows-*.spec.ts' : '*.ai.spec.ts',
    testIgnore: [],
    workers: 1,
    fullyParallel: false,
    timeout: process.env.AI_E2E_SURFACE === '1' ? 45_000 : 180_000,
    expect: { ...regular.expect, timeout: process.env.AI_E2E_SURFACE === '1' ? 10_000 : 60_000 },
    outputDir: `${process.env.AI_E2E_OUTPUT}/browser`,
    reporter: [
        ['list'],
        ['html', { outputFolder: `${process.env.AI_E2E_OUTPUT}/report`, open: 'never' }],
        ['junit', { outputFile: `${process.env.AI_E2E_OUTPUT}/junit.xml` }],
    ],
    use: { ...regular.use, baseURL: process.env.AI_E2E_BASE_URL, trace: 'on' },
})
