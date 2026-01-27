module.exports = {
    resolveSnapshotPath: (testPath, snapshotExtension) => {
        const testFileName = path.basename(testPath)
        const snapshotFileName = `${testFileName}.${snapshotExtension}`
        return path.join(__dirname, '__snapshots__', snapshotFileName)
    },
}
