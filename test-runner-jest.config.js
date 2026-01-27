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
    // Block Jest from scanning rust/ directory entirely via haste config.
    // This prevents Rust test snapshots (*.snap files in rust/cymbal/tests/snapshots/)
    // from being detected as "obsolete" during Storybook visual regression tests.
    // Neither modulePathIgnorePatterns, roots, nor snapshotResolver prevent this -
    // haste.blockList is the only config that blocks Jest's file system scanning.
    haste: {
        blockList: [/[\\/]rust[\\/]/],
    },
}
