import { getDocumentAsync } from 'expo-document-picker'
import { File } from 'expo-file-system'
import { launchImageLibraryAsync, UIImagePickerPreferredAssetRepresentationMode } from 'expo-image-picker'

import type { PickedFile } from './types'

function lastPathSegment(uri: string): string {
    const segment = uri.split(/[?#]/)[0]?.split('/').filter(Boolean).at(-1) ?? ''
    try {
        return decodeURIComponent(segment)
    } catch {
        return segment
    }
}

/** Some platforms leave out the size, so the file on disk answers. Null when it cannot be read. */
function sizeOf(uri: string, reported: number | undefined): number | null {
    if (typeof reported === 'number') {
        return reported
    }
    try {
        return new File(uri).size
    } catch {
        return null
    }
}

/**
 * iOS names a converted photo after its original, such as `IMG_0001.HEIC` for a JPEG, and the content type comes
 * from the name. The extension of the file the picker wrote wins. A web pick has a `data:` or `blob:` URI with no
 * file name in it, so only its own name counts.
 */
function photoName(fileName: string | null | undefined, uri: string): string {
    const written = uri.startsWith('file:') ? lastPathSegment(uri) : ''
    const writtenExtension = written.includes('.') ? written.split('.').at(-1) : undefined
    const base = fileName?.trim() || written || 'photo'
    if (!writtenExtension) {
        return base
    }
    const stem = base.includes('.') ? base.slice(0, base.lastIndexOf('.')) : base
    return `${stem}.${writtenExtension.toLowerCase()}`
}

export async function pickPhotos(selectionLimit: number): Promise<PickedFile[]> {
    const result = await launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsMultipleSelection: true,
        selectionLimit,
        // A HEIC photo arrives as a JPEG, which the agent and the web thread can read.
        preferredAssetRepresentationMode: UIImagePickerPreferredAssetRepresentationMode.Compatible,
    })
    if (result.canceled) {
        return []
    }
    return result.assets.map((asset) => ({
        uri: asset.uri,
        name: photoName(asset.fileName, asset.uri),
        size: sizeOf(asset.uri, asset.file?.size ?? asset.fileSize),
        ...(asset.file ? { webFile: asset.file } : {}),
    }))
}

export async function pickFiles(): Promise<PickedFile[]> {
    const result = await getDocumentAsync({ type: '*/*', multiple: true, copyToCacheDirectory: true })
    if (result.canceled) {
        return []
    }
    return result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.name || lastPathSegment(asset.uri) || 'file',
        size: sizeOf(asset.uri, asset.file?.size ?? asset.size),
        ...(asset.file ? { webFile: asset.file } : {}),
    }))
}
