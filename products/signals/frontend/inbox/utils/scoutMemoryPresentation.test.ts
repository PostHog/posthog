import { linkReportIdsInNote, scratchpadEntryBody, scratchpadEntryTitle } from './scoutMemoryPresentation'

const REPORT_ID = '01a0918c-51db-73c3-a1f1-177d5990cf1e'
const OTHER_ID = '01a0918c-51db-73c3-a1f1-177d5990cf99'

describe('scoutMemoryPresentation', () => {
    describe('linkReportIdsInNote', () => {
        const reports = new Map([[REPORT_ID, { id: REPORT_ID, title: 'fix(web-vitals): LCP regression on /pricing' }]])

        it('names a resolved report by title and links it', () => {
            const linked = linkReportIdsInNote(`Suggested reviewers changed on ${REPORT_ID}.`, reports)
            expect(linked).toContain('[LCP regression on /pricing](')
            expect(linked).toContain(REPORT_ID)
            expect(linked).not.toContain(`on ${REPORT_ID}`)
        })

        it('truncates an id no report resolves for, rather than wrapping the whole uuid', () => {
            expect(linkReportIdsInNote(`Dismissed ${OTHER_ID} as noise.`, reports)).toBe(
                'Dismissed `01a0918c…` as noise.'
            )
        })

        it('leaves an id that already sits in a link target alone', () => {
            const note = `See [the report](/project/2/inbox/reports/${REPORT_ID}).`
            expect(linkReportIdsInNote(note, reports)).toBe(note)
        })

        it('matches an id whatever case it was written in', () => {
            expect(linkReportIdsInNote(REPORT_ID.toUpperCase(), reports)).toContain('LCP regression on /pricing')
        })
    })

    describe('scratchpadEntryTitle', () => {
        it('uses the entry’s opening heading, without its hashes', () => {
            expect(scratchpadEntryTitle('## Baseline p75 per top page\n\n/pricing 2.1s', 'key')).toBe(
                'Baseline p75 per top page'
            )
        })

        it('falls back to the key for an entry that opens into prose', () => {
            expect(scratchpadEntryTitle('/pricing 2.1s, /docs 1.6s', 'baseline:web-vitals')).toBe('baseline:web-vitals')
        })

        it('falls back to the key for an entry with no content', () => {
            expect(scratchpadEntryTitle(null, 'baseline:web-vitals')).toBe('baseline:web-vitals')
        })
    })

    describe('scratchpadEntryBody', () => {
        it('drops the heading the title already shows', () => {
            expect(scratchpadEntryBody('# Known regressions\n\nTwo open reports.')).toBe('Two open reports.')
        })

        it('keeps a body that never had a heading', () => {
            expect(scratchpadEntryBody('Two open reports.')).toBe('Two open reports.')
        })
    })
})
