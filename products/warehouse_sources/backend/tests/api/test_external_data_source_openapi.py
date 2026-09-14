from drf_spectacular.generators import SchemaGenerator

UPDATE_WEBHOOK_INPUTS_PATH = "/api/projects/{project_id}/external_data_sources/{id}/update_webhook_inputs/"


class TestUpdateWebhookInputsOpenApiContract:
    def test_request_body_holds_only_the_webhook_inputs(self) -> None:
        # Without an explicit request schema the action inherits the source serializer, so the
        # generated MCP tool loses `inputs` and demands source credentials the endpoint ignores.
        schema = SchemaGenerator().get_schema(request=None, public=True)
        body = schema["paths"][UPDATE_WEBHOOK_INPUTS_PATH]["post"]["requestBody"]
        ref = body["content"]["application/json"]["schema"]["$ref"]
        component = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]

        assert set(component["properties"]) == {"inputs"}
        assert component["required"] == ["inputs"]
        assert component["properties"]["inputs"]["additionalProperties"] == {"type": "string"}
