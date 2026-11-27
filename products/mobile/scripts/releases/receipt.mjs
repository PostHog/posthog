export const receiptAssetName = 'mobile-release-receipt.json'

export function renderReleaseNotes(receipt, repository) {
    const { request, result, commit, runUrl } = receipt
    const tag = encodeURIComponent(`mobile-release/${request.id}`)
    const lines = [request.notes.trim(), '', `**Version:** ${request.runtimeVersion} · **Status:** Pre-release`, '']
    if (request.kind === 'native') {
        lines.push('## Build submissions', '', '| Platform | Destination | Submission |', '| --- | --- | --- |')
        for (const build of result.submittedBuilds) {
            const platform = build.platform === 'ios' ? 'iOS' : 'Android'
            const destination = build.platform === 'ios' ? 'TestFlight' : 'Google Play internal testing'
            lines.push(`| ${platform} | ${destination} | Completed |`)
        }
        lines.push('', 'Store processing may still be pending before these builds become available to testers.', '')
    } else {
        lines.push('## Update', '', 'Published to the production channel for iOS and Android.', '')
    }
    lines.push(
        `[Source commit ${commit.slice(0, 7)}](https://github.com/${repository}/commit/${commit}) · [Release workflow](${runUrl})`,
        '',
        `[Release receipt (JSON)](https://github.com/${repository}/releases/download/${tag}/${receiptAssetName})`,
        ''
    )
    return lines.join('\n')
}
