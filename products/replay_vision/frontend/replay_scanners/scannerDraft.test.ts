import { readScannerDraft, writeScannerDraft } from './scannerDraft'
import { newScanner } from './scannerTemplates'

const STORAGE_KEY = 'replay-vision.new-scanner-draft'

describe('scannerDraft', () => {
    beforeEach(() => {
        localStorage.clear()
    })

    it('returns the timestamp it stored, so callers and storage agree', () => {
        const savedAt = writeScannerDraft(1, newScanner(null))
        expect(readScannerDraft(1)?.savedAt).toBe(savedAt)
    })

    it.each([
        ['returns the draft for the same team', 1, (draft: any) => draft, true],
        ['rejects a draft from another team', 2, (draft: any) => draft, false],
        [
            'rejects a stale draft',
            1,
            (draft: any) => ({ ...draft, savedAt: Date.now() - 8 * 24 * 60 * 60 * 1000 }),
            false,
        ],
        ['rejects a different schema version', 1, (draft: any) => ({ ...draft, version: 999 }), false],
        ['rejects unparseable storage', 1, () => 'not json', false],
    ])('%s', (_label, readTeamId, tamper, expectRestored) => {
        const scanner = { ...newScanner(null), name: 'Drafted scanner' }
        writeScannerDraft(1, scanner)
        const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
        const tampered = tamper(stored)
        localStorage.setItem(STORAGE_KEY, typeof tampered === 'string' ? tampered : JSON.stringify(tampered))
        expect(readScannerDraft(readTeamId)?.scanner.name ?? null).toBe(expectRestored ? 'Drafted scanner' : null)
    })
})
