// ./snapshot-resolver.js
const path = require('path')

// 👉 process.env.TEST_ROOT will only be available in --index-json or --stories-json mode.
// if you run this code without these flags, you will have to override it the test root, else it will break.
// e.g. process.env.TEST_ROOT = process.cwd()

module.exports = {
    resolveSnapshotPath: (testPath, snapshotExtension) => {
        // Save inside __snapshots__ folder at same level as test file
        const testDirectory = path.dirname(testPath)
        const testName = path.basename(testPath)
        return path.join(testDirectory, '__snapshots__', testName + snapshotExtension)
    },

    resolveTestPath: (snapshotFilePath, snapshotExtension) => {
        const testPath = snapshotFilePath.replace('__snapshots__/', '').replace(/\.snap$/, '')
        return testPath
    },

    testPathForConsistencyCheck: path.join(process.cwd(), 'example.test.js'),
}
