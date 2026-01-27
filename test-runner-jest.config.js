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
    // Explicitly set roots to exclude rust/ from Jest's scanning.
    // Without this, Jest scans the entire rootDir and detects Rust test snapshots
    // (*.snap files in rust/cymbal/tests/snapshots/) as "obsolete" because they
    // don't correspond to any JavaScript tests.
    roots: [
        '<rootDir>/frontend',
        '<rootDir>/products',
        '<rootDir>/common',
    ],
}
