import { capture } from './analytics.js'
import { getImport } from './uploads.js'

export function parseCsv(text) {
  const lines = String(text).split(/\r?\n/).filter((line) => line.trim().length > 0)
  if (lines.length === 0) {
    return { headers: [], rows: [] }
  }
  const headers = lines[0].split(',').map((cell) => cell.trim())
  const rows = lines.slice(1).map((line) => {
    const cells = line.split(',').map((cell) => cell.trim())
    return Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? '']))
  })
  return { headers, rows }
}

export function handleProcess(req, res) {
  const record = getImport(Number(req.params.id))
  if (!record) {
    return res.status(404).json({ error: 'Import not found' })
  }
  const body = record.buffer?.toString('utf8') ?? ''
  const parsed = record.contentType.includes('json') ? { rows: JSON.parse(body || '[]') } : parseCsv(body)
  record.status = 'processed'
  capture(req.headers['x-account-id'] ?? 'anonymous', 'import_processed', {
    filename: record.filename,
    row_count: parsed.rows.length,
  })
  return res.json({ id: record.id, status: record.status, rowCount: parsed.rows.length })
}
