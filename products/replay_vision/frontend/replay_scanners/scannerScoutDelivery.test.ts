import { SCOUT_REPORT_EMITTED_EVENT, scoutWebhookDestinationPayload, webhookUrlError } from './scannerScoutDelivery'

describe('scannerScoutDelivery', () => {
    const skillName = 'signals-scout-daily-digest'

    it('delivers once per run, and only for a report that reached the inbox', () => {
        const payload = scoutWebhookDestinationPayload(skillName, 'Daily digest', 'https://example.com/hook')
        expect(payload.template_id).toBe('template-webhook')
        // Emit fires once per run and carries the whole report. Edits carry only what they touched
        // and can fire several times in one run, so watching them would deliver blanks and repeats.
        expect(payload.filters?.events?.map((event) => event.id)).toEqual([SCOUT_REPORT_EMITTED_EVENT])
        expect(payload.filters?.properties).toMatchObject([
            { key: 'skill_name', value: skillName },
            { key: 'outcome', value: 'surfaced' },
        ])
        const inputs = payload.inputs as Record<string, { value: any }>
        expect(inputs.url.value).toBe('https://example.com/hook')
        expect(inputs.method.value).toBe('POST')
        // The digest itself rides through, so a consumer needs no follow-up fetch.
        expect(inputs.body.value.digest).toMatchObject({
            title: '{event.properties.title}',
            summary: '{event.properties.summary}',
            url: '{event.properties.report_url}',
        })
    })

    it('rejects URLs that would leak digests or credentials', () => {
        expect(webhookUrlError('https://example.com/hook')).toBeNull()
        expect(webhookUrlError('http://example.com/hook')).toBe('The URL must start with https://')
        expect(webhookUrlError('https://user:pass@example.com/hook')).toBe('The URL must not embed credentials')
        expect(webhookUrlError('not a url')).toBe('Enter a valid URL')
    })
})
