def pluck(list_of_dicts, key, child_key=None):
    return [pluck(d[key], child_key) if child_key else d[key] for d in list_of_dicts]


def pad(retention_result: list[list[int]]) -> list[list[int]]:
    """
    changes the old 'triangle' format to the new 'matrix' format
    after retention updates
    """
    result = []
    max_length = max(len(row) for row in retention_result)

    for row in retention_result:
        if len(row) < max_length:
            row.extend([0] * (max_length - len(row)))

        result.append(row)

    return result
