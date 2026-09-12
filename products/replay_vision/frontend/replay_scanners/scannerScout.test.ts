import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { validateSkillName } from 'products/skills/frontend/skillConstants'

import type { ScannerScoutTemplate } from './scannerScout'
import {
    SCOUT_DISPLAY_NAME_MAX_LENGTH,
    isScannerScoutConfig,
    scannerScoutCreatePayload,
    scannerScoutTemplates,
    scoutBodyPlaceholders,
    scoutSkillName,
} from './scannerScout'

describe('scannerScout', () => {
    const scannerId = '0198B7C4-1111-2222-3333-444455556666'

    it('derives the skill name from the scanner and the template, never from the typed name', () => {
        // The skill name is an id: unique per team, fixed at creation, capped at 64 characters. It
        // used to be slugified from the typed name, which is what pushed that cap onto the name
        // field. The derivation no longer takes a name at all, so no name can overrun it.
        const name = scoutSkillName('Rage clicks on checkout', 'daily-digest', [])
        expect(name).toBe('signals-scout-rage-clicks-on-checkout-daily-digest')
        expect(validateSkillName(name)).toBeUndefined()
        expect(scoutSkillName('Rage clicks on checkout', 'daily-digest', [name])).toBe(`${name}-2`)
    })

    it('numbers a scout per scanner rather than across the team', () => {
        // Skill names are unique per team, so leaving the scanner out of the slug made the second
        // scanner's first daily digest `signals-scout-daily-digest-2`, and the number climbed with
        // every scanner the team set up.
        const first = scoutSkillName('Checkout rage clicks', 'daily-digest', [])
        const second = scoutSkillName('Signup drop-off', 'daily-digest', [first])
        expect(first).toBe('signals-scout-checkout-rage-clicks-daily-digest')
        expect(second).toBe('signals-scout-signup-drop-off-daily-digest')
    })

    it('keeps the template key whole when the scanner name would overrun the cap', () => {
        // Only the scanner gives way to the cap, and only inside the id. A scanner named past the
        // cap must still leave a valid skill name that says which template the scout came from —
        // cut mid-word, a slug ends in a hyphen, which fails skill name validation.
        for (const key of ['daily-digest', 'trend-watch', 'new-issues', 'scratch'] as const) {
            const name = scoutSkillName('x'.repeat(SCOUT_DISPLAY_NAME_MAX_LENGTH), key, [])
            expect(name.length).toBeLessThanOrEqual(64)
            expect(validateSkillName(name)).toBeUndefined()
            expect(name.endsWith(`-${key}`)).toBe(true)
        }
    })

    it('leads the default name with the scanner, since the id no longer carries it', () => {
        // The scout lands in the Signals fleet beside every other product's, where four scanners'
        // "Daily digest" is four rows of the same name.
        const templates = scannerScoutTemplates(scannerId, 'monitor', 'Rage clicks on checkout')
        expect(templates.map((template) => template.defaultName)).toEqual([
            'Rage clicks on checkout daily digest',
            'Rage clicks on checkout trend watch',
            'Rage clicks on checkout new issue watch',
            'Rage clicks on checkout custom scout',
        ])
        // A scanner can be unnamed, and " daily digest" is not a name.
        expect(scannerScoutTemplates(scannerId, 'monitor', '')[0].defaultName).toBe('Daily digest')
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
        const templates = scannerScoutTemplates(scannerId, 'monitor', 'Rage clicks')
        expect(templates).toHaveLength(4)
        const keys = templates.map((template) => template.key)
        expect(new Set(keys).size).toBe(keys.length)
        for (const template of templates) {
            expect(template.body).toContain(scannerId)
            expect(template.cron).toMatch(/^\d+ \d+ \* \* \*$/)
            // vision-scanners-get takes `id`; only the sibling vision-scanners-observations-* tools
            // take `scanner_id`. Pairing the get call with scanner_id fails validation on the first
            // move of every scheduled run.
            expect(template.body).toContain(`\`vision-scanners-get\` with id \`${scannerId}\``)
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
            scannerScoutTemplates(scannerId, type, 'Rage clicks').find((template) => template.key === 'trend-watch')!

        expect(trendFor('monitor').description).toContain('yes-rate')
        expect(trendFor('monitor').body).toContain('scanner_output_verdict')
        expect(trendFor('scorer').description).toContain('mean score')
        expect(trendFor('scorer').body).toContain('scanner_output_score')
        expect(trendFor('classifier').description).toContain('tag mix')
        expect(trendFor('summarizer').description).toContain('themes')
        // A scanner whose type hasn't loaded still gets a usable template rather than nothing.
        expect(scannerScoutTemplates(scannerId, undefined, 'Rage clicks')).toHaveLength(4)
    })

    it('gives the new-issue template a catalog to diff against, so "new" means something', () => {
        const newIssues = scannerScoutTemplates(scannerId, 'monitor', 'Rage clicks').find(
            (template) => template.key === 'new-issues'
        )!
        // Novelty needs remembered history: without the catalog every run reports everything.
        // The key is scanner-scoped so it matches what the first move searches on.
        expect(newIssues.body).toContain(`${scannerId}:pattern:known-issues`)
        // And it must not fire on a scanner edit that merely changed what gets reported.
        expect(newIssues.body).toContain('scanner_version')
    })

    it('stamps both tags and the reviewed name, prompt, and cron on the create payload', () => {
        const payload = scannerScoutCreatePayload('Checkout friction', {
            name: 'signals-scout-daily-digest',
            body: scannerScoutTemplates(scannerId, 'monitor', 'Rage clicks')[0].body,
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
