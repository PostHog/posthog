from products.warehouse_sources.backend.temporal.data_imports.sources.attio.attio import validate_credentials


class TestValidateCredentials:
    def test_non_ascii_key_returns_actionable_message_without_leaking_encoding_error(self):
        # A non-latin-1 key can't be encoded into the Authorization header; the raw
        # UnicodeEncodeError ("'latin-1' codec can't encode ... ordinal not in range(256)")
        # must never surface to the user.
        valid, msg = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (msg or "")
        assert "latin-1" not in (msg or "")
        assert "ordinal not in range" not in (msg or "")
