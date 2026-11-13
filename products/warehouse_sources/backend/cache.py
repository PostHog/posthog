from typing import Any

from django_redis.pool import ConnectionFactory
from redis import ConnectionPool


class WarehouseSourceCatalogConnectionFactory(ConnectionFactory):
    # Django Redis keys pools by URL, so a separate map keeps this alias's socket deadlines.
    _pools: dict[str, ConnectionPool] = {}

    def get_connection_pool(self, params: dict[str, Any]) -> ConnectionPool:
        pool = super().get_connection_pool(params)
        pool.connection_kwargs["socket_connect_timeout"] = params["socket_connect_timeout"]
        pool.connection_kwargs["socket_timeout"] = params["socket_timeout"]
        return pool
