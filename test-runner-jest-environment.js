const { setupPage } = require('@storybook/test-runner')
const PlaywrightEnvironment = require('jest-playwright-preset/lib/PlaywrightEnvironment').default

class CustomEnvironment extends PlaywrightEnvironment {
    async setup() {
        await super.setup()
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
