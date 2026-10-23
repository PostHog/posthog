import {
    ATTACHMENT_MAX_SIZE_BYTES,
    addPickedFiles,
    contentTypeFor,
    MAX_ATTACHMENTS_PER_MESSAGE,
    PDF_ATTACHMENT_MAX_SIZE_BYTES,
    pickNotice,
} from './attachmentRules'
import type { PendingAttachment, PickedFile } from './types'

function picked(name: string, size: number | null = 100): PickedFile {
    return { uri: `file:///picked/${name}`, name, size }
}

function counter(): () => string {
    let next = 0
    return () => {
        next += 1
        return `id-${next}`
    }
}

describe('attachment rules', () => {
    test.each([
        ['shot.PNG', 'image/png'],
        ['notes.md', 'text/markdown'],
        ['archive.tar.gz', 'application/octet-stream'],
        ['Makefile', 'application/octet-stream'],
    ])('%s is sent as %s', (name, contentType) => {
        expect(contentTypeFor(name)).toBe(contentType)
    })

    test.each<[string, PickedFile, string | null]>([
        ['a PDF at its limit', picked('a.pdf', PDF_ATTACHMENT_MAX_SIZE_BYTES), null],
        ['a PDF one byte over', picked('a.pdf', PDF_ATTACHMENT_MAX_SIZE_BYTES + 1), 'too_large'],
        ['an image past the PDF limit', picked('a.png', PDF_ATTACHMENT_MAX_SIZE_BYTES + 1), null],
        ['an image one byte over', picked('a.png', ATTACHMENT_MAX_SIZE_BYTES + 1), 'too_large'],
        ['an empty file', picked('a.txt', 0), 'empty'],
        ['a file with no size', picked('a.txt', null), 'unreadable'],
    ])('%s', (_name, file, reason) => {
        const pick = addPickedFiles([], [file], counter())
        expect(pick.rejected.map((rejection) => rejection.reason)).toEqual(reason ? [reason] : [])
        expect(pick.added).toHaveLength(reason ? 0 : 1)
    })

    test('fills the free slots in pick order and says how many were left off', () => {
        const current = Array.from({ length: MAX_ATTACHMENTS_PER_MESSAGE - 2 }, (_, index) => ({
            id: `old-${index}`,
        })) as PendingAttachment[]
        const pick = addPickedFiles(
            current,
            [picked('empty.txt', 0), picked('one.png'), picked('two.csv'), picked('three.txt')],
            counter()
        )

        expect(pick.added).toEqual([
            {
                id: 'id-1',
                uri: 'file:///picked/one.png',
                name: 'one.png',
                size: 100,
                contentType: 'image/png',
                isImage: true,
            },
            {
                id: 'id-2',
                uri: 'file:///picked/two.csv',
                name: 'two.csv',
                size: 100,
                contentType: 'text/csv',
                isImage: false,
            },
        ])
        expect(pick.leftOff).toBe(1)
        expect(pickNotice(pick)).toBe('empty.txt is empty. Only 10 files fit in one message, so 1 was left off.')
    })
})
