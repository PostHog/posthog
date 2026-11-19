import { fetchSnapshotBlocks, fetchSnapshotRange } from '@/api/snapshots'
import { demoReplaySnapshots } from '@/demo/replays'

import { WebReplayPlayer } from './WebReplayPlayer'

jest.mock('@/api/snapshots')

test('passes local demo snapshots to the page without calling either snapshots endpoint', () => {
    jest.clearAllMocks()
    const start = 1000
    const session = 'demo-replay-invite'
    const snapshots = demoReplaySnapshots(session, start)
    expect(snapshots).toBeDefined()
    const player = new WebReplayPlayer(session, start, snapshots)
    const scripts: string[] = []
    try {
        player.attach({ inject: (script) => scripts.push(script) })
        player.onPageMessage(JSON.stringify({ type: 'loaded' }))
        player.prepare(0, null, true)
        player.onPageMessage(JSON.stringify({ type: 'need', requestId: 1, from: 0, to: 0 }))

        expect(scripts[0]).toContain('"sources":[{"startTs":1000,"endTs":25000}]')
        expect(scripts[2]).toContain('"type":"blocks","requestId":1')
        expect(scripts[2]).toContain('Invite sent to blake@example.com')
        expect(fetchSnapshotBlocks).not.toHaveBeenCalled()
        expect(fetchSnapshotRange).not.toHaveBeenCalled()
    } finally {
        player.destroy()
    }
})

test('retries playback when snapshots become available after an empty listing', async () => {
    jest.mocked(fetchSnapshotBlocks)
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([{ index: 0, startTs: 1000, endTs: 4000 }])
    const scripts: string[] = []
    const player = new WebReplayPlayer('recording', 1000)
    player.attach({ inject: (script) => scripts.push(script) })
    player.onPageMessage(JSON.stringify({ type: 'loaded' }))
    player.prepare(1, null, true)

    await Promise.resolve()
    expect(player.status).toBe('error')

    player.retry()
    await Promise.resolve()
    expect(player.status).toBe('loading')
    expect(scripts[0]).toContain('"sources":[{"startTs":1000,"endTs":4000}]')
    expect(scripts[1]).toContain('"targetTs":2000')
    player.destroy()
})
