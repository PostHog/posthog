VALID_FILTER_GROUP = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [{"key": "service.name", "operator": "exact", "value": "api", "type": "log_attribute"}],
        }
    ],
}
