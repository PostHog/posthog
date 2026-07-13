// Catches: exact-match content-type whitelisting rejecting valid CSV uploads - Excel/Windows's application/vnd.ms-excel and text/csv with a charset parameter.
import assert from 'node:assert/strict'
import test from 'node:test'

import { handleUpload } from '../src/uploads.js'

function makeReq(contentType, filename, body = 'sku,qty\nA-1,3\n') {
  return {
    headers: {
      'content-type': contentType,
      'x-filename': filename,
      'x-account-id': 'acct_verify',
    },
    body: Buffer.from(body),
  }
}

function makeRes() {
  return {
    statusCode: null,
    body: null,
    status(code) {
      this.statusCode = code
      return this
    },
    json(payload) {
      this.body = payload
      return this
    },
  }
}

test('CSV uploaded from Excel on Windows (application/vnd.ms-excel) is accepted', () => {
  const res = makeRes()
  handleUpload(makeReq('application/vnd.ms-excel', 'orders.csv'), res)
  assert.equal(res.statusCode, 201, `expected 201, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.filename, 'orders.csv')
  assert.equal(res.body.status, 'queued')
})

test('text/csv with a charset parameter is accepted', () => {
  const res = makeRes()
  handleUpload(makeReq('text/csv;charset=utf-8', 'orders.csv'), res)
  assert.equal(res.statusCode, 201, `expected 201, got ${res.statusCode}: ${JSON.stringify(res.body)}`)
  assert.equal(res.body.status, 'queued')
})
