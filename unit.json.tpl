{
    "settings": {
        "http": {
            "max_body_size": 22020096
        }
    },
    "listeners": {
        "*:8000": {
            "pass": "applications/posthog"
        },
        "*:8001": {
            "pass": "routes/metrics"
        },
        "*:8181": {
            "pass": "routes/status"
        }
    },
    "routes": {
        "metrics": [
            {
                "match": {
                    "uri": ["/metrics"]
                },
                "action": {
                    "pass": "applications/metrics"
                }
            }
        ],
        "status": [
            {
                "match": {
                    "uri": ["/status"]
                },
                "action": {
                    "proxy": "http://unix:/var/run/control.unit.sock"
                }
            }
        ]
    },
    "applications": {
        "posthog": {
            "type": "python 3.12",
            "processes": $NGINX_UNIT_APP_PROCESSES,
            "working_directory": "/code",
            "path": ".",
            "module": "posthog.$NGINX_UNIT_PYTHON_PROTOCOL",
            "protocol": "$NGINX_UNIT_PYTHON_PROTOCOL",
            "user": "nobody",
            "limits": {
                "requests": 7500
            }
        },
        "metrics": {
            "type": "python 3.12",
            "processes": 1,
            "working_directory": "/code/bin",
            "path": ".",
            "module": "unit_metrics",
            "user": "nobody"
        }
    }
}
