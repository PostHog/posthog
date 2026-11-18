import { fetchSnapshotBlocks } from '@/api/snapshots'

import { WebReplayPlayer } from './WebReplayPlayer'

jest.mock('@/api/snapshots')

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
