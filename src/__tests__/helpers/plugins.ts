import { Plugin, PluginAttachmentDB, PluginConfig } from '../../types'
import fs from 'fs'
import path from 'path'
import os from 'os'
import AdmZip from 'adm-zip'

export const plugin60: Plugin = {
    id: 60,
    name: 'test-maxmind-plugin',
    description: 'Ingest GeoIP data via MaxMind',
    url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
    config_schema: {
        localhostIP: {
            hint: 'Useful if testing locally',
            name: 'IP to use instead of 127.0.0.1',
            type: 'string',
            order: 2,
            default: '',
            required: false,
        },
        maxmindMmdb: {
            hint: 'The "GeoIP2 City" or "GeoLite2 City" database file',
            name: 'GeoIP .mddb database',
            type: 'attachment',
            order: 1,
            markdown:
                'Sign up for a [MaxMind.com](https://www.maxmind.com) account, download and extract the database and then upload the `.mmdb` file below',
            required: true,
        },
    },
    tag: '0.0.2',
    archive: createZipBuffer('test-maxmind-plugin', {
        indexJs:
            'function processEvent (event) { if (event.properties) { event.properties.processed = true } return event }',
    }),
    error: undefined,
}

export const pluginAttachment1: PluginAttachmentDB = {
    id: 1,
    key: 'maxmindMmdb',
    content_type: 'application/octet-stream',
    file_name: 'test.txt',
    file_size: 4,
    contents: Buffer.from('test'),
    plugin_config_id: 39,
    team_id: 2,
}

export const pluginConfig39: PluginConfig = {
    id: 39,
    team_id: 2,
    plugin_id: 60,
    enabled: true,
    order: 0,
    config: { localhostIP: '94.224.212.175' },
    error: undefined,
}

function createZipBuffer(name: string, { indexJs, pluginJson }: { indexJs?: string; pluginJson?: string }): Buffer {
    const zip = new AdmZip()
    if (indexJs) {
        zip.addFile('testplugin/index.js', Buffer.alloc(indexJs.length, indexJs))
    }
    if (pluginJson) {
        zip.addFile('testplugin/plugin.json', Buffer.alloc(pluginJson.length, pluginJson))
    } else {
        zip.addFile(
            'testplugin/plugin.json',
            Buffer.from(
                JSON.stringify({
                    name,
                    description: 'just for testing',
                    url: 'http://example.com/plugin',
                    config: {},
                    main: 'index.js',
                })
            )
        )
    }
    return zip.toBuffer()
}

export const mockPluginWithArchive = (indexJs: string, pluginJson?: string): Plugin => ({
    ...plugin60,
    archive: createZipBuffer('posthog-maxmind-plugin', { indexJs, pluginJson }),
})

export const mockJestWithIndex = (
    indexJs: string
): {
    getPluginRows: Plugin[]
    getPluginConfigRows: PluginConfig[]
    getPluginAttachmentRows: PluginAttachmentDB[]
} => ({
    getPluginRows: [mockPluginWithArchive(indexJs)],
    getPluginConfigRows: [pluginConfig39],
    getPluginAttachmentRows: [pluginAttachment1],
})

export function mockPluginTempFolder(indexJs: string, pluginJson?: string): [Plugin, () => void] {
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'foo-'))

    fs.writeFileSync(path.join(folder, 'index.js'), indexJs)
    fs.writeFileSync(
        path.join(folder, 'plugin.json'),
        pluginJson ||
            JSON.stringify({
                name: 'posthog-maxmind-plugin',
                description: 'just for testing',
                url: 'http://example.com/plugin',
                config: {},
                main: 'index.js',
            })
    )
    return [
        { ...plugin60, url: `file:${folder}`, archive: null },
        () => {
            fs.rmdirSync(folder, { recursive: true })
        },
    ]
}
