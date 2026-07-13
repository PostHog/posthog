import express from 'express'

import { handleProcess } from './processor.js'
import { handleList, handleUpload } from './uploads.js'

export function createApp() {
  const app = express()
  app.use(express.raw({ type: () => true, limit: '20mb' }))
  app.post('/api/imports', handleUpload)
  app.get('/api/imports', handleList)
  app.post('/api/imports/:id/process', handleProcess)
  return app
}
