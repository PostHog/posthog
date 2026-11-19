"""The connection settings of the Postgres destination.

The generated class is `facade/configs/postgres.py:PostgresDestinationConfig`. A target's
namespace is the schema, so the schema and the table are not settings here.

This module must not import the Postgres client: the registry reads it without loading psycopg.
"""

from products.warehouse_destinations.backend.facade.destination_spec import (
    DestinationFieldInput,
    DestinationFieldInputType,
    DestinationFieldIntegration,
    DestinationFieldSelect,
    DestinationFieldSelectOption,
    DestinationSpec,
)
from products.warehouse_destinations.backend.facade.enums import DestinationType

# The `kind` of the integrations that hold Postgres connection details.
POSTGRESQL_INTEGRATION_KIND = "postgresql"
DEFAULT_PORT = 5432
DEFAULT_SSL_MODE = "require"

POSTGRES_SPEC = DestinationSpec(
    destinationType=DestinationType.POSTGRES,
    label="Postgres",
    fields=[
        DestinationFieldInput(
            type=DestinationFieldInputType.TEXT,
            name="database",
            label="Database",
            required=True,
            secret=False,
            placeholder="postgres",
        ),
        DestinationFieldSelect(
            name="auth_method",
            label="Connect with",
            required=True,
            defaultValue="integration",
            options=[
                DestinationFieldSelectOption(
                    value="integration",
                    label="A saved Postgres connection",
                    fields=[
                        DestinationFieldIntegration(
                            name="integration_id",
                            label="Connection",
                            integrationKind=POSTGRESQL_INTEGRATION_KIND,
                            required=True,
                        ),
                    ],
                ),
                DestinationFieldSelectOption(
                    value="credentials",
                    label="Host and credentials",
                    fields=[
                        DestinationFieldInput(
                            type=DestinationFieldInputType.TEXT,
                            name="host",
                            label="Host",
                            required=True,
                            secret=False,
                            placeholder="db.example.com",
                        ),
                        DestinationFieldInput(
                            type=DestinationFieldInputType.NUMBER,
                            name="port",
                            label="Port",
                            required=True,
                            secret=False,
                            default=DEFAULT_PORT,
                        ),
                        DestinationFieldInput(
                            type=DestinationFieldInputType.TEXT,
                            name="user",
                            label="User",
                            required=True,
                            secret=False,
                        ),
                        DestinationFieldInput(
                            type=DestinationFieldInputType.PASSWORD,
                            name="password",
                            label="Password",
                            required=True,
                            secret=True,
                        ),
                        DestinationFieldSelect(
                            name="ssl_mode",
                            label="SSL mode",
                            required=True,
                            defaultValue=DEFAULT_SSL_MODE,
                            caption="How the connection uses TLS. The verify modes need a trusted server certificate.",
                            options=[
                                DestinationFieldSelectOption(value="prefer", label="Prefer"),
                                DestinationFieldSelectOption(value="require", label="Require"),
                                DestinationFieldSelectOption(value="verify-ca", label="Verify CA"),
                                DestinationFieldSelectOption(value="verify-full", label="Verify full"),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    ],
)
