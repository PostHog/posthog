# Working in `rust/cyclotron-node-migrations/`

These migrations own the `cyclotron_node` database, which backs the Node cyclotron job queue.
Read [Keep rows small](../../nodejs/src/cdp/services/cyclotron-v2/README.md#keep-rows-small-no-file-or-blob-storage) before you add a table or column here.

- **The cyclotron database holds no file or blob payloads.**
  A new table or column must not store large or variable-size bytes, such as email attachments, rendered bodies, exports or files from users.
  Put those bytes in object storage and keep only the key and the metadata in the row.
  Queue rows are inserted and deleted at a high rate, and large values in PostgreSQL go to TOAST, which only vacuum reclaims.
  That pattern bloats the database that every queue dequeues from.
- **Do not edit a migration that has been applied.**
  sqlx stores a checksum of each migration and refuses to run when a file changes.
  Add a new migration instead.
