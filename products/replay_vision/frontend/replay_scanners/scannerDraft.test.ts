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

    it('keeps the credit limit toggle on across the round trip while the amount is still empty', () => {
        const scanner = { ...newScanner(null), credit_limit_enabled: true, credit_limit: null }
        writeScannerDraft(1, scanner)
        const restored = readScannerDraft(1)?.scanner
        expect(restored?.credit_limit_enabled).toBe(true)
        expect(restored?.credit_limit).toBeNull()
    })

    it('restores a concrete credit limit as-is', () => {
        const scanner = { ...newScanner(null), credit_limit: 500 }
        writeScannerDraft(1, scanner)
        expect(readScannerDraft(1)?.scanner.credit_limit).toBe(500)
    })

    it('still restores an old draft carrying the retired empty-but-enabled marker', () => {
        writeScannerDraft(1, { ...newScanner(null), name: 'Old draft' })
        const stored = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...stored, creditLimitEmptyButEnabled: true }))
        expect(readScannerDraft(1)?.scanner.name).toBe('Old draft')
    })
})
