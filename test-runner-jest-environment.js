const { setupPage } = require('@storybook/test-runner')
const PlaywrightEnvironment = require('jest-playwright-preset/lib/PlaywrightEnvironment').default

// Webkit intermittently exceeds the default 30s page.goto timeout when navigating
// to Storybook iframe URLs in CI. This causes ~1.5% of webkit runs to fail with
// "page.goto: Timeout 30000ms exceeded" on random stories. Doubling the navigation
// timeout for webkit eliminates these flaky failures without affecting chromium.
// See: https://github.com/PostHog/posthog/pull/46640 (diagnostics)
// See: https://github.com/PostHog/posthog/pull/46952 (worker reduction)
const WEBKIT_NAVIGATION_TIMEOUT_MS = 60000

class CustomEnvironment extends PlaywrightEnvironment {
    async setup() {
        await super.setup()

        // Increase navigation timeout for webkit in CI to prevent flaky page.goto timeouts.
        // The test-runner's setupPage() calls page.goto() which uses the default 30s timeout.
        // Webkit is more sensitive to resource contention on GitHub Actions runners.
        const browserName = this.global.browserName
        if (browserName === 'webkit' && process.env.CI) {
            this.global.context.setDefaultNavigationTimeout(WEBKIT_NAVIGATION_TIMEOUT_MS)
        }

        await setupPage(this.global.page, this.global.context)
    }

    async teardown() {
        await super.teardown()
    }

    async handleTestEvent(event) {
        if (event.name === 'test_done' && event.test.errors.length > 0) {
            // Take screenshots on test failures - these become Actions artifacts
            const parentName = event.test.parent.parent.name.replace(/\W/g, '-').toLowerCase()
            const specName = event.test.parent.name.replace(/\W/g, '-').toLowerCase()
            await this.global.page
                .locator('body, main')
                .last()
                .screenshot({
                    path: `frontend/__snapshots__/__failures__/${parentName}--${specName}.png`,
                })
        }
        await super.handleTestEvent(event)
    }
}

module.exports = CustomEnvironment
