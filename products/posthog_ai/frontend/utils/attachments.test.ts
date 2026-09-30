import {
    ATTACHMENT_MAX_SIZE_BYTES,
    PDF_ATTACHMENT_MAX_SIZE_BYTES,
    attachmentRejectionReason,
    formatFileSize,
    inferContentType,
    isImageAttachment,
    maxSizeBytesFor,
} from './attachments'

function fileOfSize(name: string, size: number): File {
    const file = new File(['x'], name)
    Object.defineProperty(file, 'size', { value: size })
    return file
}

describe('inferContentType', () => {
    it.each([
        ['screenshot.png', 'image/png'],
        ['SCREENSHOT.PNG', 'image/png'],
        ['report.pdf', 'application/pdf'],
        ['notes.md', 'text/markdown'],
        ['rows.csv', 'text/csv'],
    ])('reads %s as %s', (name, contentType) => {
        expect(inferContentType(name)).toBe(contentType)
    })

    it('falls back to a binary type for an unknown or absent extension', () => {
        expect(inferContentType('mystery.qqq')).toBe('application/octet-stream')
        expect(inferContentType('Makefile')).toBe('application/octet-stream')
    })

    it('ignores what the browser claims the file is', () => {
        const file = new File(['# notes'], 'notes.md', { type: 'application/octet-stream' })
        expect(inferContentType(file.name)).toBe('text/markdown')
    })
})

describe('isImageAttachment', () => {
    it('recognizes the raster types an agent can look at', () => {
        expect(isImageAttachment('a.png')).toBe(true)
        expect(isImageAttachment('a.jpeg')).toBe(true)
        expect(isImageAttachment('a.webp')).toBe(true)
    })

    it('does not treat a document as an image', () => {
        expect(isImageAttachment('a.pdf')).toBe(false)
        expect(isImageAttachment('a.csv')).toBe(false)
    })
})

describe('maxSizeBytesFor', () => {
    it('holds PDFs to the lower ceiling the model accepts', () => {
        expect(maxSizeBytesFor('spec.pdf')).toBe(PDF_ATTACHMENT_MAX_SIZE_BYTES)
        expect(maxSizeBytesFor('spec.png')).toBe(ATTACHMENT_MAX_SIZE_BYTES)
    })
})

describe('attachmentRejectionReason', () => {
    it('accepts a file inside the limit', () => {
        expect(attachmentRejectionReason(fileOfSize('a.png', 1024))).toBeNull()
    })

    it('rejects an empty file', () => {
        expect(attachmentRejectionReason(fileOfSize('a.png', 0))).toBe('a.png is empty')
    })

    it('rejects a file over the general limit and names the limit', () => {
        expect(attachmentRejectionReason(fileOfSize('a.png', ATTACHMENT_MAX_SIZE_BYTES + 1))).toBe(
            'a.png is over the 30MB limit'
        )
    })

    it('rejects a PDF over the PDF limit while the same size passes as a PNG', () => {
        const size = PDF_ATTACHMENT_MAX_SIZE_BYTES + 1
        expect(attachmentRejectionReason(fileOfSize('spec.pdf', size))).toBe('spec.pdf is over the 10MB limit for PDFs')
        expect(attachmentRejectionReason(fileOfSize('spec.png', size))).toBeNull()
    })
})

describe('formatFileSize', () => {
    it.each([
        [512, '512 B'],
        [2048, '2 KB'],
        [1024 * 1024 * 3.5, '3.5 MB'],
    ])('renders %s bytes as %s', (bytes, formatted) => {
        expect(formatFileSize(bytes)).toBe(formatted)
    })
})
