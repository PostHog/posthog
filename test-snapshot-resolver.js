// ./snapshot-resolver.js
const path = require('path')

// 👉 process.env.TEST_ROOT will only be available in --index-json or --stories-json mode.
// if you run this code without these flags, you will have to override it the test root, else it will break.
// e.g. process.env.TEST_ROOT = process.cwd()

module.exports = {
    resolveSnapshotPath: (testPath, snapshotExtension) =>
        path.join(process.cwd(), '__snapshots__', path.basename(testPath) + snapshotExtension),
    resolveTestPath: (snapshotFilePath, snapshotExtension) =>
        path.join(process.env.TEST_ROOT, path.basename(snapshotFilePath, snapshotExtension)),
    testPathForConsistencyCheck: path.join(process.env.TEST_ROOT, 'example.test.js'),
}
