#!/usr/bin/env node
import fs from 'fs'
import path from 'path'

const args = process.argv.slice(2)
const getArg = (name) => {
    const arg = args.find((a) => a.startsWith(`--${name}=`))
    return arg ? arg.split('=')[1] : null
}

const baseFile = getArg('base')
const prFile = getArg('pr')
const outputFile = getArg('output')

if (!baseFile || !prFile || !outputFile) {
    console.error('Usage: compare-bundles.mjs --base=<file> --pr=<file> --output=<file>')
    process.exit(1)
}

function parsePackageName(filePath) {
    if (!filePath.includes('node_modules')) {
        return 'app'
    }
    const match = filePath.match(/node_modules\/\.pnpm\/([^/]+)/)
    if (match) {
        // Handle scoped packages like @posthog+icons@1.0.0
        let pkg = match[1]
        // Convert @scope+name format back to @scope/name
        if (pkg.startsWith('@')) {
            pkg = pkg.replace('+', '/')
        }
        // Remove version suffix
        const atIndex = pkg.lastIndexOf('@')
        if (atIndex > 0) {
            pkg = pkg.substring(0, atIndex)
        }
        return pkg
    }
    return 'unknown'
}

function analyzeBundle(metafile) {
    const outputs = metafile.outputs || {}
    const packageSizes = {}
    let totalSize = 0

    for (const [file, chunkInfo] of Object.entries(outputs)) {
        if (!file.endsWith('.js') || file.includes('.map')) continue
        totalSize += chunkInfo.bytes || 0

        if (!chunkInfo.inputs) continue
        for (const [inputFile, inputInfo] of Object.entries(chunkInfo.inputs)) {
            const size = inputInfo.bytesInOutput || 0
            const pkg = parsePackageName(inputFile)
            packageSizes[pkg] = (packageSizes[pkg] || 0) + size
        }
    }

    return { totalSize, packageSizes }
}

function formatSize(bytes) {
    if (bytes >= 1024 * 1024) {
        return (bytes / 1024 / 1024).toFixed(2) + ' MB'
    }
    return (bytes / 1024).toFixed(0) + ' KB'
}

function formatDiff(diff, base) {
    if (base === 0) return diff > 0 ? '🆕 new' : '-'
    const pct = ((diff / base) * 100).toFixed(1)
    const sign = diff > 0 ? '+' : ''
    return `${sign}${formatSize(diff)} (${sign}${pct}%)`
}

function getIcon(diff, threshold = 50 * 1024) {
    if (diff > threshold) return '🔴'
    if (diff > 0) return '🟡'
    if (diff < -threshold) return '🟢'
    if (diff < 0) return '🟢'
    return '⚪'
}

// Load metafiles
const baseMeta = JSON.parse(fs.readFileSync(baseFile, 'utf8'))
const prMeta = JSON.parse(fs.readFileSync(prFile, 'utf8'))

const baseAnalysis = analyzeBundle(baseMeta)
const prAnalysis = analyzeBundle(prMeta)

const totalDiff = prAnalysis.totalSize - baseAnalysis.totalSize

// Compute package diffs
const allPackages = new Set([...Object.keys(baseAnalysis.packageSizes), ...Object.keys(prAnalysis.packageSizes)])
const packageDiffs = []

for (const pkg of allPackages) {
    const baseSize = baseAnalysis.packageSizes[pkg] || 0
    const prSize = prAnalysis.packageSizes[pkg] || 0
    const diff = prSize - baseSize
    if (diff !== 0) {
        packageDiffs.push({ pkg, baseSize, prSize, diff })
    }
}

// Sort by absolute diff descending
packageDiffs.sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff))

// Generate markdown report
let report = `## 📦 Frontend Bundle Size

`

// Summary
const totalIcon = getIcon(totalDiff, 100 * 1024)
report += `### Summary

| Metric | Base | PR | Diff |
|--------|------|----|----- |
| **Total Size** | ${formatSize(baseAnalysis.totalSize)} | ${formatSize(prAnalysis.totalSize)} | ${totalIcon} ${formatDiff(totalDiff, baseAnalysis.totalSize)} |

`

// Package changes
if (packageDiffs.length > 0) {
    report += `### Package Changes

<details>
<summary>Show ${packageDiffs.length} packages with size changes</summary>

| Package | Base | PR | Diff |
|---------|------|----|----- |
`

    for (const { pkg, baseSize, prSize, diff } of packageDiffs.slice(0, 50)) {
        const icon = getIcon(diff)
        const pkgDisplay = pkg.length > 40 ? pkg.substring(0, 37) + '...' : pkg
        report += `| ${pkgDisplay} | ${formatSize(baseSize)} | ${formatSize(prSize)} | ${icon} ${formatDiff(diff, baseSize)} |\n`
    }

    if (packageDiffs.length > 50) {
        report += `| *...and ${packageDiffs.length - 50} more* | | | |\n`
    }

    report += `
</details>

`
}

// Top packages in PR (always show to help spot large deps like monaco)
const topPackages = Object.entries(prAnalysis.packageSizes)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)

report += `### Largest Packages

| Package | Size | % of Total |
|---------|------|------------|
`

for (const [pkg, size] of topPackages) {
    const pct = ((size / prAnalysis.totalSize) * 100).toFixed(1)
    const pkgDisplay = pkg.length > 40 ? pkg.substring(0, 37) + '...' : pkg
    report += `| ${pkgDisplay} | ${formatSize(size)} | ${pct}% |\n`
}

report += `
---
*Updated at ${new Date().toISOString()}*
`

fs.writeFileSync(outputFile, report)
console.log(`Report written to ${outputFile}`)
