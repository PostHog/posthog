# Deploy requirements manifest

A deploy requirements manifest lists what must be true before an image may roll out.
The build writes it into the image.
A check reads it before the new pods start, and the old pods keep serving until it passes.

Version 1 holds only schema requirements: Django migrations and sqlx migration versions.
The format has a `kind` per requirement, so other kinds can follow (see "Add a kind").

The contract is [`deploy-requirements.v1.schema.json`](deploy-requirements.v1.schema.json).
[`test_deploy_requirements.py`](test_deploy_requirements.py) holds both writers to it.

## Where it is

| Image                    | File                                    | Writer                                                                                   | Reader                                                                                                         |
| ------------------------ | --------------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Node (`Dockerfile.node`) | `/code/nodejs/schema-requirements.json` | `nodejs/src/schema-check/generate.ts`                                                    | `nodejs/src/schema-check/manifest.ts`, in the `node-schema-check` Sync hook                                    |
| Rust (`rust/Dockerfile`) | `/app/schema-requirements.json`         | `rust/bin/write-deploy-requirements`, from `sqlx_databases` in `.github/rust-images.yml` | `rust/bin/deploy-requirements-check` in the `sqlx-migrate` image, in the `deploy-requirements-check` Sync hook |

The file name stays `schema-requirements.json` in version 1, because the checks read old images too.
The Sync hooks are in PostHog/charts, `charts/posthog-app/templates/`.

## Fields

| Field            | Meaning                                                                                                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version` | Always `1`.                                                                                                                                                                                                               |
| `source_commit`  | The commit the image was built from, or `null` when the build does not know it.                                                                                                                                           |
| `digest`         | The first 12 hex characters of the SHA-256 of `requirements` as compact JSON (`JSON.stringify` in Node, `json.dumps(..., separators=(",", ":"))` in Python). It identifies the list in logs. Readers do not recompute it. |
| `requirements`   | A list of requirements. Each one has a `kind`.                                                                                                                                                                            |

## Kinds

**`django`**: a Django migration that must be applied on the main Postgres.
`database` is always `default`.
`app` and `migration` name the migration.
`replaces` is set when `migration` is a squash: the squash or every migration it replaces satisfies the requirement.

**`sqlx`**: migration versions that must be applied in one sqlx database.
`database` is the `rust/bin/migrate-entry` name (`persons`, `cyclotron-node`, `behavioral-cohorts`, `flags-read-store`).
`versions` lists every required version, ascending.
A version recorded as failed in `_sqlx_migrations` does not satisfy the requirement.
A newer applied version does not matter, so a rollback to an older image passes.

## Rules for readers

- An unknown `schema_version` or `kind` is an error, never a pass. A skipped requirement would report a pass for something that nothing checked.
- A missing file passes and is logged. The image is older than the manifest.
- Each reader applies its own extra rules. The Node reader requires at least one `django` requirement, because an empty list means the generator found nothing. The Rust reader treats a declared database without a URL as an error.

## Exit codes of the checks

`0` satisfied, `1` missing (the rollout waits), `2` the check cannot see the state.
A check in shadow mode logs the result and exits `0`.

## Add a kind

1. Add the kind to the schema and to the examples, and bump `schema_version` only if an old reader could misread the new kind as an old one.
2. Teach every reader the kind and ship the readers first. An old reader rejects the new kind, so it fails closed.
3. Teach the writers last.

## Add a writer or a reader

Add an example of the writer's output to `examples/`, or run the writer from the contract test like the Rust writer.
A reader adds a test that reads the examples.

## Prior art

No standard covers "this image needs this provider state". Score, OAM and CNAB declare that a dependency exists, that it is healthy, or which bundle version it has, not which migrations are applied.
Version 1 reuses standards where they fit: JSON Schema for the contract.
The manifest can later travel next to the image as an [OCI annotation](https://github.com/opencontainers/image-spec/blob/main/annotations.md) (`com.posthog.deploy-requirements`), or as the predicate of an [in-toto Statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) bound to the image digest.
Both need the file written before the image build, so that the build or a later step can attach it.
