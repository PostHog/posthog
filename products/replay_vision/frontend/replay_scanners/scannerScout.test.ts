import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { validateSkillName } from 'products/skills/frontend/skillConstants'

import { ScoutTemplateKeyEnumApi } from '../generated/api.schemas'
import type { ScannerScoutTemplateKey } from './scannerScout'
import {
    SCOUT_DISPLAY_NAME_MAX_LENGTH,
    isScannerScoutConfig,
    isTemplateScout,
    scannerScoutCreatePayload,
    scoutSkillName,
} from './scannerScout'

describe('scannerScout', () => {
    const scannerId = '0198B7C4-1111-2222-3333-444455556666'

    it('derives the skill name from the scanner and the template, never from the typed name', () => {
        // The skill name is an id: unique per team, fixed at creation, capped at 64 characters.
        // Because the derivation takes no name at all, no typed name can overrun the cap.
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
        // cap must still leave a valid skill name that says which template the scout came from:
        // cut mid-word, a slug ends in a hyphen, which fails skill name validation. The keys come
        // from the generated enum, so a new template joins the invariant without a change here.
        for (const key of Object.values(ScoutTemplateKeyEnumApi)) {
            const name = scoutSkillName('x'.repeat(SCOUT_DISPLAY_NAME_MAX_LENGTH), key, [])
            expect(name.length).toBeLessThanOrEqual(64)
            expect(validateSkillName(name)).toBeUndefined()
            expect(name.endsWith(`-${key}`)).toBe(true)
        }
    })

    it('fits the cap when a template key alone leaves no room for the scanner', () => {
        // No current key is this long, but the clamp must subtract the 14-char prefix, not just the
        // collision suffix: a 60-char key plus the prefix would otherwise reach 75 against a 64 cap.
        const longKey = 'x'.repeat(60) as ScannerScoutTemplateKey
        expect(scoutSkillName('Rage clicks on checkout', longKey, []).length).toBeLessThanOrEqual(64)
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

    it.each([
        { skillName: 'signals-scout-checkout-root-cause', expected: true },
        // A second scanner with the same name gets a collision suffix, and is still a root cause scout.
        { skillName: 'signals-scout-checkout-root-cause-2', expected: true },
        { skillName: 'signals-scout-checkout-daily-digest', expected: false },
        { skillName: 'signals-scout-root-cause-checkout-daily-digest', expected: false },
    ])('recognizes $skillName as a root cause scout: $expected', ({ skillName, expected }) => {
        // A missed match makes the prompt offer a second scout for the same question.
        expect(isTemplateScout(skillName, 'root-cause')).toBe(expected)
    })

    it('asks the server to keep a template scout in step, and only variant analysis for a record schema', () => {
        // Without the key the server cannot tell an untouched template body from a hand-written one,
        // so the scout would never pick up later template edits.
        const digest = scannerScoutCreatePayload('Checkout test', {
            name: 'n',
            body: 'b',
            cron: '0 9 * * *',
            templateKey: 'daily-digest',
        })
        expect(digest.template_key).toBe('daily-digest')
        expect(digest).not.toHaveProperty('variant_analysis')
        const variants = scannerScoutCreatePayload('Checkout test', {
            name: 'n',
            body: 'b',
            cron: '0 9 * * *',
            templateKey: 'variant-analysis',
        })
        expect(variants.variant_analysis).toBe(true)
    })

    it('stamps both tags and the reviewed name, prompt, and cron on the create payload', () => {
        const payload = scannerScoutCreatePayload('Checkout friction', {
            name: 'signals-scout-daily-digest',
            body: `Read \`vision-scanners-get\` with id \`${scannerId}\` first.`,
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
        // Only the variant analysis template asks the server for the record schema the variants view reads.
        expect(payload).not.toHaveProperty('variant_analysis')
        expect(payload).not.toHaveProperty('template_key')
        expect(payload.config?.enabled).toBe(true)
        expect(payload.config?.emit).toBe(true)
    })
})
