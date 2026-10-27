import ssl

from unittest.mock import patch

from pymongo import MongoClient

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_documentdb.source import AwsDocumentDBSource

_MONGO_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.mongo"

# The shape the DocumentDB console hands out, naming a bundle file on the customer's machine.
_CONSOLE_CONNECTION_STRING = (
    "mongodb://user:pw@docdb-cluster.cluster-abc123.us-east-1.docdb.amazonaws.com:27017/"
    "?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false"
)


def test_console_connection_string_opens_a_client_that_trusts_the_aws_ca() -> None:
    source = AwsDocumentDBSource()
    config = source.parse_config({"connection_string": _CONSOLE_CONNECTION_STRING, "database_name": "app"})

    with patch(f"{_MONGO_MODULE}.MongoClient") as client_class:
        source.get_server_metadata(config, team_id=1)

    args, kwargs = client_class.call_args
    MongoClient(*args, **{**kwargs, "connect": False}).close()
    trusted = ssl.create_default_context(cafile=kwargs["tlsCAFile"]).get_ca_certs()
    assert any("Amazon Web Services, Inc." in str(cert["subject"]) for cert in trusted)
