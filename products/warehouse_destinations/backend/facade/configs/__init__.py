"""Typed config classes of the destinations, one module per destination type.

Every module here except `base.py` is generated from a `DestinationSpec` by
`pnpm generate:destination-configs`. Never edit a generated module by hand: change the spec in
`destinations/<name>/spec.py` and run the command again.

A caller imports a class directly, for example `configs.postgres.PostgresDestinationConfig`, or
parses stored settings with `api.parse_destination_config`.
"""
