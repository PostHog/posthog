import { lazyImageBlobReducer } from 'lib/hooks/useUploadFiles'

const MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
export const SCREENSHOT_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']

/** Shrinks the screenshot for upload and returns it as a data URL. Throws an error with a message to show. */
export async function readScreenshot(file: File): Promise<string> {
    if (!SCREENSHOT_TYPES.includes(file.type)) {
        throw new Error('Use a PNG, JPEG, WebP or GIF image.')
    }
    const reduced = await lazyImageBlobReducer(file)
    if (reduced.size > MAX_SCREENSHOT_BYTES) {
        throw new Error('The screenshot is larger than 5 MB. Use a smaller image.')
    }
    return await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(new Error('Could not read the screenshot. Try a different image.'))
        reader.readAsDataURL(reduced)
    })
}
