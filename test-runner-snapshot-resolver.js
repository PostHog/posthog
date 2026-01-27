/**
 * Custom snapshot resolver for Storybook test-runner.
 *
 * This resolver prevents Jest from detecting Rust test snapshots (in rust/cymbal/tests/snapshots/)
 * as "obsolete" during Storybook visual regression tests.
 *
 * The Storybook test-runner uses jest-image-snapshot which stores snapshots as .png files
 * in frontend/__snapshots__/, but Jest's built-in snapshot system still scans for .snap files
 * and reports any it finds as obsolete if they weren't used in the current test run.
 *
 * This resolver restricts snapshot resolution to only the frontend/__snapshots__ directory,
 * preventing Jest from finding the Rust .snap files.
 */
const path = require('path')

module.exports = {
    // Resolves from test path to snapshot path
    resolveSnapshotPath: (testPath, snapshotExtension) => {
        // Storybook tests use jest-image-snapshot which handles its own snapshot paths
        // This is just for Jest's built-in snapshot system
        return testPath.replace(/\.([tj]sx?)$/, `${snapshotExtension}`)
    },

    // Resolves from snapshot path to test path
    // Returning null for paths outside frontend/__snapshots__ prevents Jest from
    // considering those snapshots as part of this test run
    resolveTestPath: (snapshotFilePath, snapshotExtension) => {
        // Ignore any .snap files outside of frontend/__snapshots__
        // This prevents Rust snapshots from being detected as obsolete
        if (!snapshotFilePath.includes('frontend/__snapshots__')) {
            return null
        }
        return snapshotFilePath.replace(snapshotExtension, '.js')
    },

    // Example test path for Jest to verify the resolver works
    testPathForConsistencyCheck: 'frontend/src/example.test.js',
}
