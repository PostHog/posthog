const { getJestConfig } = require('@storybook/test-runner')

/**
 * @type {import('@jest/types').Config.InitialOptions}
 */
module.exports = {
    // The default configuration comes from @storybook/test-runner
    ...getJestConfig(),
    /** Add your own overrides below
     * @see https://jestjs.io/docs/configuration
     */
    forceExit: true,
    // For jest-image-snapshot, see https://github.com/americanexpress/jest-image-snapshot#removing-outdated-snapshots
    reporters: ['default', 'jest-image-snapshot/src/outdated-snapshot-reporter.js'],
    testEnvironment: './test-runner-jest-environment.js',
}
