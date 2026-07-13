import { capture } from './analytics.js'
import { isAllowedUpload, isFilenameSane } from './validation.js'

const imports = []
let nextId = 1

export function handleUpload(req, res) {
  const contentType = req.headers['content-type'] ?? ''
  const filename = req.headers['x-filename'] ?? `upload-${nextId}`
  const accountId = req.headers['x-account-id'] ?? 'anonymous'

  if (!isFilenameSane(filename)) {
    return res.status(400).json({ error: 'Invalid filename' })
  }
  if (!isAllowedUpload(contentType)) {
    capture(accountId, 'import_rejected', { content_type: contentType, filename })
    return res.status(415).json({ error: `Unsupported content type: ${contentType}` })
  }

  const buffer = Buffer.isBuffer(req.body) ? req.body : Buffer.from(String(req.body ?? ''))
  const record = {
    id: nextId++,
    filename,
    contentType,
    buffer,
    bytes: buffer.length,
    status: 'queued',
  }
  imports.push(record)
  capture(accountId, 'import_uploaded', {
    filename,
    content_type: contentType,
    bytes: record.bytes,
  })
  return res.status(201).json({ id: record.id, filename: record.filename, status: record.status })
}

export function handleList(req, res) {
  return res.json({ imports: imports.map(({ id, filename, status }) => ({ id, filename, status })) })
}

export function getImport(id) {
  return imports.find((record) => record.id === id) ?? null
}

export function listImports() {
  return imports.slice()
}
