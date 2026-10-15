import { initKeaTests } from '~/test/init'

import { notebookChangesLogic } from './notebookChangesLogic'
import { NotebookVisitStorage } from './notebookVisitStorage'

const scope = JSON.stringify([1, 1, 'example-notebook'])

beforeEach(() => {
    initKeaTests()
    localStorage.clear()
})

test('compares with the previous visit while retaining the latest viewed version for the next visit', () => {
    let logic = notebookChangesLogic({ scope, markdown: '# First version' })
    logic.mount()
    expect(logic.values.hasChanges).toBe(false)
    logic.unmount()

    logic = notebookChangesLogic({ scope, markdown: '# Second version' })
    logic.mount()
    expect(logic.values.previousVisit?.markdown).toBe('# First version')
    expect(logic.values.hasChanges).toBe(true)
    logic.actions.setShowChanges(true)
    expect(logic.values.showChanges).toBe(true)

    notebookChangesLogic({ scope, markdown: '# Third version' })
    expect(logic.values.previousVisit?.markdown).toBe('# First version')
    logic.actions.dismissChanges()
    expect(logic.values.hasChanges).toBe(false)
    expect(logic.values.showChanges).toBe(false)
    logic.unmount()

    logic = notebookChangesLogic({ scope, markdown: '# Third version' })
    logic.mount()
    expect(logic.values.hasChanges).toBe(false)
    logic.unmount()
})

test('waits for loaded content and saves the latest version when the browser page closes', () => {
    NotebookVisitStorage.write(scope, '# Before')
    const logic = notebookChangesLogic({ scope, markdown: null })
    logic.mount()
    expect(logic.values.visitInitialized).toBe(false)
    notebookChangesLogic({ scope, markdown: '# Loaded' })
    expect(logic.values.hasChanges).toBe(true)
    window.dispatchEvent(new Event('pagehide'))
    expect(NotebookVisitStorage.read(scope)?.markdown).toBe('# Loaded')
    logic.unmount()
})

test.each([null, JSON.stringify([2, 1, 'example-notebook']), JSON.stringify([1, 2, 'example-notebook'])])(
    'does not show a previous visit across identities: %s',
    (otherScope) => {
        NotebookVisitStorage.write(scope, '# Private version')
        const logic = notebookChangesLogic({ scope: otherScope, markdown: '# Current' })
        logic.mount()
        expect(logic.values.hasChanges).toBe(false)
        expect(logic.values.previousVisit).toBeNull()
        logic.unmount()
    }
)

test('tolerates corrupt storage and evicts old or oversized snapshots', () => {
    localStorage.setItem('notebook-last-visits', '{broken')
    expect(NotebookVisitStorage.read(scope)).toBeNull()
    for (let index = 0; index < 11; index++) {
        NotebookVisitStorage.write(String(index), '# Version')
    }
    expect(NotebookVisitStorage.read('0')).toBeNull()
    expect(NotebookVisitStorage.read('10')?.markdown).toBe('# Version')
    NotebookVisitStorage.write('10', 'x'.repeat(500_001))
    expect(NotebookVisitStorage.read('10')).toBeNull()
})

test('keeps notebook visits usable when browser storage is unavailable', () => {
    const write = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new DOMException('Storage unavailable', 'QuotaExceededError')
    })
    try {
        expect(() => NotebookVisitStorage.write(scope, '# Version')).not.toThrow()
    } finally {
        write.mockRestore()
    }
})
