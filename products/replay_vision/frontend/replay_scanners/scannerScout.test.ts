import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScannerScoutTemplate } from './scannerScout'
import {
    scoutNameToSkillName,
    isScannerScoutConfig,
    scannerScoutCreatePayload,
    scannerScoutTemplates,
    scoutBodyPlaceholders,
} from './scannerScout'

describe('scannerScout', () => {
    const scannerId = '0198B7C4-1111-2222-3333-444455556666'

    it('slugifies user names into valid, unique skill names and humanizes them back', () => {
        const name = scoutNameToSkillName('Checkout friction (weekly)', 'Rage clicks', [])
        expect(name).toBe('signals-scout-rage-clicks-checkout-friction-weekly')
        expect(name).toMatch(/^signals-scout-[a-z0-9-]+$/)
        expect(scoutNameToSkillName('Checkout friction (weekly)', 'Rage clicks', [name])).toBe(`${name}-2`)
        expect(scoutNameToSkillName('', 'Rage clicks', [])).toBe('signals-scout-rage-clicks-digest')
        expect(scoutNameToSkillName('x'.repeat(100), 'Rage clicks', []).length).toBeLessThanOrEqual(64)
    })

    it('numbers a scout per scanner rather than across the team', () => {
        // Skill names are unique per team, so deriving one from the label alone made the second
        // scanner's first daily digest `signals-scout-daily-digest-2`, and the number climbed with
        // every scanner the team set up.
        const first = scoutNameToSkillName('Daily digest', 'Checkout rage clicks', [])
        const second = scoutNameToSkillName('Daily digest', 'Signup drop-off', [first])
        expect(first).toBe('signals-scout-checkout-rage-clicks-daily-digest')
        expect(second).toBe('signals-scout-signup-drop-off-daily-digest')
    })

    it('keeps the label whole when the scanner name would overrun the cap', () => {
        // The label is what tells two scouts on one scanner apart; the scanner name is context.
        const name = scoutNameToSkillName('new issue watch', 'x'.repeat(80), [])
        expect(name.length).toBeLessThanOrEqual(64)
        expect(name.endsWith('-new-issue-watch')).toBe(true)
    })

    it('claims only the scouts recorded as belonging to this scanner', () => {
        const config = (source_product: string, source_id: string): SignalScoutConfigApi =>
            ({ source_product, source_id }) as SignalScoutConfigApi
        expect(isScannerScoutConfig(config('replay_vision', scannerId.toLowerCase()), scannerId)).toBe(true)
        // Another scanner's scout, and a scout a person created directly, both stay out.
        expect(isScannerScoutConfig(config('replay_vision', '0198b7c4-9999-2222-3333-444455556666'), scannerId)).toBe(
            false
        )
        expect(isScannerScoutConfig(config('', ''), scannerId)).toBe(false)
    })

    it('gives every template a distinct key, its own cron, and a body scoped to the scanner', () => {
        const templates = scannerScoutTemplates(scannerId, 'monitor')
        expect(templates).toHaveLength(4)
        const keys = templates.map((template) => template.key)
        expect(new Set(keys).size).toBe(keys.length)
        for (const template of templates) {
            expect(template.body).toContain(scannerId)
            expect(template.cron).toMatch(/^\d+ \d+ \* \* \*$/)
        }
        for (const template of templates) {
            expect(template.defaultName.trim()).not.toBe('')
        }
        // The scratch body ships the machinery filled in and the judgment blank, so a user who
        // saves it unedited gets a scout asking for instructions rather than a silently vague one.
        const scratch = templates.find((template) => template.key === 'scratch')!
        expect(scratch.body).toContain('vision-scanners-observations-list')
        // Unfilled slots block the create button, so the scratch body must trip that gate and the
        // ready-made ones must not.
        expect(scoutBodyPlaceholders(scratch.body).length).toBeGreaterThan(0)
        for (const template of templates.filter((candidate) => candidate.key !== 'scratch')) {
            expect(scoutBodyPlaceholders(template.body)).toEqual([])
        }
    })

    it('writes the trend template for the one output the scanner actually emits', () => {
        const trendFor = (type: 'monitor' | 'scorer' | 'classifier' | 'summarizer'): ScannerScoutTemplate =>
            scannerScoutTemplates(scannerId, type).find((template) => template.key === 'trend-watch')!

        expect(trendFor('monitor').description).toContain('yes-rate')
        expect(trendFor('monitor').body).toContain('scanner_output_verdict')
        expect(trendFor('scorer').description).toContain('mean score')
        expect(trendFor('scorer').body).toContain('scanner_output_score')
        expect(trendFor('classifier').description).toContain('tag mix')
        expect(trendFor('summarizer').description).toContain('themes')
        // A scanner whose type hasn't loaded still gets a usable template rather than nothing.
        expect(scannerScoutTemplates(scannerId, undefined)).toHaveLength(4)
    })

    it('gives the new-issue template a catalog to diff against, so "new" means something', () => {
        const newIssues = scannerScoutTemplates(scannerId, 'monitor').find((template) => template.key === 'new-issues')!
        // Novelty needs remembered history: without the catalog every run reports everything.
        // The key is scanner-scoped so it matches what the first move searches on.
        expect(newIssues.body).toContain(`${scannerId}:pattern:known-issues`)
        // And it must not fire on a scanner edit that merely changed what gets reported.
        expect(newIssues.body).toContain('scanner_version')
    })

    it('stamps both tags and the reviewed name, prompt, and cron on the create payload', () => {
        const payload = scannerScoutCreatePayload('Checkout friction', {
            name: 'signals-scout-daily-digest',
            body: scannerScoutTemplates(scannerId, 'monitor')[0].body,
            cron: '30 7 * * *',
        })
        expect(payload.name).toBe('signals-scout-daily-digest')
        expect(payload.body).toContain(scannerId)
        expect(payload.description).toContain('Checkout friction')
        // The scanner is not in the payload at all: the endpoint records it from the URL it checked
        // the caller's access against, so a body cannot claim a scanner the caller can't edit.
        expect(JSON.stringify(payload)).not.toContain(scannerId.toLowerCase())
        // Slack rides on the platform's own delivery, which posts the one report each run files.
        expect(payload.config?.output_destinations).toEqual({})
        expect(payload.config?.run_cron_schedule).toBe('30 7 * * *')
        expect(payload.config?.enabled).toBe(true)
        expect(payload.config?.emit).toBe(true)
    })
})
