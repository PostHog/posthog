# Acme Importer

Bulk import service: customers and integrators push CSV or JSON files, we
queue them, parse them, and load the rows into the customer's workspace.

## Running

```bash
npm install
npm start
# server on http://localhost:4700
```

## API

- `POST /api/imports` - upload a file (raw body; `content-type` and `x-filename` headers)
- `GET /api/imports` - list queued imports
- `POST /api/imports/:id/process` - parse a queued import

Uploads are validated by content type before anything touches the parser.

## Layout

- `src/app.js` - express wiring
- `src/uploads.js` - upload endpoint handlers + import queue
- `src/validation.js` - upload validation rules
- `src/processor.js` - CSV/JSON parsing
