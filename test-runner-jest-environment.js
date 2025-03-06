const { setupPage } = require('@storybook/test-runner')
const PlaywrightEnvironment = require('jest-playwright-preset/lib/PlaywrightEnvironment').default
const fs = require('fs')
const path = require('path')

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
            const failuresDir = path.join('frontend', '__snapshots__', '__failures__')

            // Ensure failures directory exists
            // we don't want to commit failure snapshots to the repo
            // so this dir is in .gitignore
            // which means it doesn't exist in CI
            // so we need to create it here
            if (!fs.existsSync(failuresDir)) {
                fs.mkdirSync(failuresDir, { recursive: true })
            }

            // artifacts action insists on unique names
            // so we'll add a timestamp to the end of the filename
            const timestamp = new Date().toISOString().replace(/[-:Z]/g, '')

            await this.global.page
                .locator('body, main')
                .last()
                .screenshot({
                    path: path.join(failuresDir, `${parentName}--${specName}-${timestamp}.png`),
                })
        }
        await super.handleTestEvent(event)
    }
}

module.exports = CustomEnvironment
