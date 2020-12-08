import { Readable } from 'stream'
import * as tar from 'tar-stream'
import AdmZip from 'adm-zip'
import * as zlib from 'zlib'
import { LogLevel } from './types'

/**
 * @param binary Buffer
 * returns readableInstanceStream Readable
 */
export function bufferToStream(binary: Buffer): Readable {
    const readableInstanceStream = new Readable({
        read() {
            this.push(binary)
            this.push(null)
        },
    })

    return readableInstanceStream
}

export async function getFileFromArchive(archive: Buffer, file: string): Promise<string | null> {
    try {
        return getFileFromZip(archive, file)
    } catch (e) {
        try {
            return await getFileFromTGZ(archive, file)
        } catch (e) {
            throw new Error(`Could not read archive as .zip or .tgz`)
        }
    }
}

export async function getFileFromTGZ(archive: Buffer, file: string): Promise<string | null> {
    const response = await new Promise((resolve: (value: string | null) => void, reject: (error?: Error) => void) => {
        const stream = bufferToStream(archive)
        const extract = tar.extract()

        let rootPath: string | null = null
        let fileData: string | null = null

        extract.on('entry', (header, stream, next) => {
            if (rootPath === null) {
                const rootPathArray = header.name.split('/')
                rootPathArray.pop()
                rootPath = rootPathArray.join('/')
            }
            if (header.name == `${rootPath}/${file}`) {
                stream.on('data', (chunk) => {
                    if (fileData === null) {
                        fileData = ''
                    }
                    fileData += chunk
                })
            }
            stream.on('end', () => next())
            stream.resume() // just auto drain the stream
        })

        extract.on('finish', function () {
            resolve(fileData)
        })

        extract.on('error', reject)

        const unzipStream = zlib.createUnzip()
        unzipStream.on('error', reject)

        stream.pipe(unzipStream).pipe(extract)
    })

    return response
}

export function getFileFromZip(archive: Buffer, file: string): string | null {
    const zip = new AdmZip(archive)
    const zipEntries = zip.getEntries() // an array of ZipEntry records
    let fileData

    if (zipEntries[0].entryName.endsWith('/')) {
        // if first entry is `pluginfolder/` (a folder!)
        const root = zipEntries[0].entryName
        fileData = zip.getEntry(`${root}${file}`)
    } else {
        // if first entry is `pluginfolder/index.js` (or whatever file)
        const rootPathArray = zipEntries[0].entryName.split('/')
        rootPathArray.pop()
        const root = rootPathArray.join('/')
        fileData = zip.getEntry(`${root}/${file}`)
    }

    if (fileData) {
        return fileData.getData().toString()
    }

    return null
}

export function setLogLevel(logLevel: LogLevel): void {
    for (const loopLevel of ['debug', 'info', 'log', 'warn', 'error', 'none']) {
        if (loopLevel === logLevel) {
            break
        }
        const originalFunction = (console as any)[loopLevel]._original || (console as any)[loopLevel]
        ;(console as any)[loopLevel] = () => {}
        ;(console as any)[loopLevel]._original = originalFunction
    }
}
