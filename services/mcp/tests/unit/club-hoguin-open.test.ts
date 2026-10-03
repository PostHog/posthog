import { afterEach, describe, expect, it } from 'vitest'

import { clubHoguinOpenHandler } from '@/tools/games/clubHoguinOpen'
import type { Context } from '@/tools/types'

const context = {} as Context

describe('club-hoguin-open', () => {
    const before = process.env.CLUB_HOGUIN_URL

    afterEach(() => {
        if (before === undefined) {
            delete process.env.CLUB_HOGUIN_URL
        } else {
            process.env.CLUB_HOGUIN_URL = before
        }
    })

    it('hands out the town and embed addresses without a doubled slash', async () => {
        process.env.CLUB_HOGUIN_URL = 'https://club.example.com/'
        const result = await clubHoguinOpenHandler(context, {})
        expect(result.url).toBe('https://club.example.com/')
        expect(result.embedUrl).toBe('https://club.example.com/?embed=1')
    })

    // The regression: a server without the town must say so, not hand out an empty or localhost link.
    it('refuses when the town is not configured', async () => {
        delete process.env.CLUB_HOGUIN_URL
        await expect(clubHoguinOpenHandler(context, {})).rejects.toThrow('CLUB_HOGUIN_URL')
    })
})
