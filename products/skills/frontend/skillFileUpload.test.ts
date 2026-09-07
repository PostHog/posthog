import { collectFilesFromDrop } from './skillFileUpload'

function fileEntry(name: string, fullPath: string): FileSystemFileEntry {
    return {
        isFile: true,
        isDirectory: false,
        name,
        fullPath,
        file: (resolve: (file: File) => void) => resolve(new File([`content of ${name}`], name)),
    } as unknown as FileSystemFileEntry
}

function unreadableFileEntry(name: string, fullPath: string): FileSystemFileEntry {
    return {
        isFile: true,
        isDirectory: false,
        name,
        fullPath,
        file: (_resolve: (file: File) => void, reject: (error: Error) => void) => reject(new Error('not readable')),
    } as unknown as FileSystemFileEntry
}

function directoryEntry(name: string, fullPath: string, children: FileSystemEntry[]): FileSystemDirectoryEntry {
    return {
        isFile: false,
        isDirectory: true,
        name,
        fullPath,
        createReader: () => {
            // Serve children one per readEntries call, like Chrome batches large directories
            let served = 0
            return {
                readEntries: (resolve: (entries: FileSystemEntry[]) => void) => {
                    resolve(served < children.length ? [children[served++]] : [])
                },
            }
        },
    } as unknown as FileSystemDirectoryEntry
}

function dropOf(entries: (FileSystemEntry | null)[]): DataTransfer {
    return {
        items: entries.map((entry) => ({
            webkitGetAsEntry: () => entry,
            getAsFile: () => null,
        })),
        files: [],
    } as unknown as DataTransfer
}

describe('collectFilesFromDrop', () => {
    it('recurses dropped folders, draining batched directory listings and skipping hidden or unreadable files', async () => {
        const scripts = directoryEntry('scripts', '/scripts', [
            fileEntry('setup.sh', '/scripts/setup.sh'),
            fileEntry('run.py', '/scripts/run.py'),
            fileEntry('.DS_Store', '/scripts/.DS_Store'),
            unreadableFileEntry('locked.txt', '/scripts/locked.txt'),
            directoryEntry('nested', '/scripts/nested', [fileEntry('deep.txt', '/scripts/nested/deep.txt')]),
        ])

        const uploads = await collectFilesFromDrop(dropOf([scripts, fileEntry('guide.md', '/guide.md')]))

        expect(uploads.map((u) => u.path)).toEqual([
            'scripts/setup.sh',
            'scripts/run.py',
            'scripts/nested/deep.txt',
            'guide.md',
        ])
        expect(uploads[0].file.name).toBe('setup.sh')
    })

    it('falls back to the flat file list when the entry API is unavailable', async () => {
        const dataTransfer = {
            items: [],
            files: [new File(['a'], 'a.txt'), new File(['b'], '.hidden')],
        } as unknown as DataTransfer

        const uploads = await collectFilesFromDrop(dataTransfer)

        expect(uploads.map((u) => u.path)).toEqual(['a.txt'])
    })
})
