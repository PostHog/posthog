import assert from 'node:assert/strict'
import test from 'node:test'
import { renderReleaseNotes } from './receipt.mjs'

test('release notes preserve authored Markdown and keep bookkeeping in the receipt attachment', () => {
    const notes = 'A chart update.\n\n### What to verify\n\n- Open a saved chart\n- Change its date range'
    const receipt = {
        request: { id: 'chart-update', kind: 'native', runtimeVersion: '2.0.0', notes },
        commit: 'a'.repeat(40),
        runUrl: 'https://example.com/release-run',
        result: { submittedBuilds: [{ platform: 'ios', id: 'invented-build-id' }] },
        recovery: { state: 'complete' },
        native: { certificateFingerprint: 'invented-certificate-fingerprint' },
    }
    const rendered = renderReleaseNotes(receipt, 'example/project')
    assert.ok(rendered.startsWith(`${notes}\n\n`))
    assert.match(rendered, /\*\*Version:\*\* 2\.0\.0/)
    assert.match(rendered, /Store processing may still be pending/)
    assert.match(rendered, /https:\/\/github\.com\/example\/project\/commit\/a{40}/)
    assert.match(rendered, /\[Release workflow\]\(https:\/\/example\.com\/release-run\)/)
    assert.match(rendered, /releases\/download\/mobile-release%2Fchart-update\/mobile-release-receipt\.json/)
    assert.doesNotMatch(rendered, /invented-build-id|certificateFingerprint|recovery/)
})
