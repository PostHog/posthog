INSERT INTO
    job_queue (
        errors,
        metadata,
        attempted_at,
        last_attempt_finished_at,
        parameters,
        queue,
        status,
        target
    )
VALUES
    -- team:1, hogFunctionId:2, completed in hour 20
    (
        NULL,
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, completed in hour 20 (purposeful duplicate)
    (
        NULL,
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, completed in hour 21 (different hour)
    (
        NULL,
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 21:01:18.799371+00',
        '2023-12-19 21:01:18.799371+00',
        '{}',
        'hoghooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:3, completed in hour 20 (different hogFunctionId)
    (
        NULL,
        '{"teamId": 1, "hogFunctionId": "3"}',
        '2023-12-19 20:01:18.80335+00',
        '2023-12-19 20:01:18.80335+00',
        '{}',
        'hoghooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, completed but in a different queue
    (
        NULL,
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'not-hoghooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:2, hogFunctionId:4, completed in hour 20 (different team)
    (
        NULL,
        '{"teamId": 2, "hogFunctionId": "4"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, failed in hour 20
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, failed in hour 20 (purposeful duplicate)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, failed in hour 20 (different error)
    (
        ARRAY ['{"type":"ConnectionError","details":{"error":{"name":"Connection Error"}}}'::jsonb],
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, failed in hour 21 (different hour)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 21:01:18.799371+00',
        '2023-12-19 21:01:18.799371+00',
        '{}',
        'hoghooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:3, failed in hour 20 (different hogFunctionId)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"teamId": 1, "hogFunctionId": "3"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, failed but in a different queue
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'not-hoghooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:2, hogFunctionId:4, failed in hour 20 (purposeful duplicate)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"teamId": 2, "hogFunctionId": "4"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'hoghooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, hogFunctionId:2, available
    (
        NULL,
        '{"teamId": 1, "hogFunctionId": "2"}',
        '2023-12-19 20:01:18.799371+00',
        '2023-12-19 20:01:18.799371+00',
        '{"body": "hello world", "headers": {}, "method": "POST", "url": "https://myhost/endpoint"}',
        'hoghooks',
        'available',
        'https://myhost/endpoint'
    );