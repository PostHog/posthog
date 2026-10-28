from parameterized import parameterized

from products.warehouse_sources.backend.logic.column_sensitivity import classify_column_sensitivity
from products.warehouse_sources.backend.types import WarehouseColumnSensitivity as S


class TestClassifyColumnSensitivity:
    @parameterized.expand(
        [
            ("email", "character varying", S.EMAIL),
            ("customerEmail", "String", S.EMAIL),
            ("email_address", "text", S.EMAIL),
            ("phone_number", "varchar(32)", S.PHONE),
            ("mobilePhone", None, S.PHONE),
            ("phone", "bigint", S.PHONE),
            ("first_name", "text", S.NAME),
            ("LastName", "String", S.NAME),
            ("username", "citext", S.NAME),
            ("billing_address_line1", "text", S.ADDRESS),
            ("postal_code", "text", S.ADDRESS),
            ("shipping_address", "jsonb", S.ADDRESS),
            ("date_of_birth", "date", S.DATE_OF_BIRTH),
            ("birthdate", "timestamp without time zone", S.DATE_OF_BIRTH),
            ("dob", "String", S.DATE_OF_BIRTH),
            ("ip_address", "inet", S.IP_ADDRESS),
            ("client_ip", "String", S.IP_ADDRESS),
            ("IPAddress", "text", S.IP_ADDRESS),
            ("access_token", "text", S.TOKEN),
            ("api_key", "varchar", S.TOKEN),
            ("password_hash", "text", S.SECRET),
            ("client_secret", "String", S.SECRET),
            ("card_number", "varchar(19)", S.CARD_NUMBER),
            ("creditCardNumber", "numeric", S.CARD_NUMBER),
            ("email_verified", "text", None),
            ("email_status", "text", None),
            ("token_type", "text", None),
            ("user_id", "uuid", None),
            ("phone_country_code", "text", None),
            ("card_last4", "text", None),
            ("card_brand", "text", None),
            ("mac_address", "text", None),
            ("has_email", "boolean", None),
            ("email_opened_at", "timestamp with time zone", None),
            ("tokens_used", "Int64", None),
            ("password_changed_at", "DateTime64(6)", None),
            ("ip_score", "Float64", None),
            ("name", "text", None),
            ("company_name", "text", None),
            ("gzip_size", "integer", None),
            ("", "text", None),
        ]
    )
    def test_classifies_from_name_and_type(self, column_name: str, data_type: str | None, expected: S | None) -> None:
        assert classify_column_sensitivity(column_name, data_type) == expected
