// Content types accepted for import uploads.
const ALLOWED_TYPES = ['text/csv', 'application/json', 'text/plain']

export function isAllowedUpload(contentType) {
  return ALLOWED_TYPES.includes(contentType)
}

export function isFilenameSane(filename) {
  return typeof filename === 'string' && filename.length > 0 && !filename.includes('/') && !filename.includes('\\')
}
