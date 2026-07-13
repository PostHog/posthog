// Catches: a validation fix that over-relaxes the whitelist (letting text/html through) or breaks plain CSV/JSON uploads and filename checks.
import assert from 'node:assert/strict'
import test from 'node:test'

import { handleUpload, listImports } from '../src/uploads.js'

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

test('plain text/csv upload is accepted and queued', () => {
  const before = listImports().length
  const res = makeRes()
  handleUpload(makeReq('text/csv', 'orders.csv'), res)
  assert.equal(res.statusCode, 201)
  assert.equal(listImports().length, before + 1)
})

test('application/json upload is accepted', () => {
  const res = makeRes()
  handleUpload(makeReq('application/json', 'rows.json', '[{"sku":"A-1"}]'), res)
  assert.equal(res.statusCode, 201)
})

test('text/html upload is rejected with 415 and not queued', () => {
  const before = listImports().length
  const res = makeRes()
  handleUpload(makeReq('text/html', 'page.html', '<html></html>'), res)
  assert.equal(res.statusCode, 415)
  assert.match(res.body.error, /content type/i)
  assert.equal(listImports().length, before)
})

test('text/html with a charset parameter is still rejected', () => {
  const res = makeRes()
  handleUpload(makeReq('text/html;charset=utf-8', 'page.html', '<html></html>'), res)
  assert.equal(res.statusCode, 415)
})

test('missing content type is rejected', () => {
  const res = makeRes()
  handleUpload(makeReq('', 'orders.csv'), res)
  assert.equal(res.statusCode, 415)
})

test('filename with a path separator is rejected with 400', () => {
  const res = makeRes()
  handleUpload(makeReq('text/csv', '../../etc/passwd'), res)
  assert.equal(res.statusCode, 400)
})
