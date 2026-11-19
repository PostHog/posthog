from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.flags import flag_calls_only_in_flag_evaluations

if TYPE_CHECKING:
    from posthog.models import Team


@frozen
class FlagCalls:
    """The table that holds a team's flag calls, and the fields there that a scan of them filters and groups by.

    A scan that reads `person_id` pins PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS, so that events read the stored
    person id, as flag_evaluations does.
    """

    table: tuple[str, ...]
    only_calls: ast.Expr
    flag_key: ast.Expr
    response: ast.Expr
    person_id: ast.Expr

    @classmethod
    def of(cls, team: "Team") -> "FlagCalls":
        # Ingestion writes no flag calls to events for some teams of an organization on FLAG_EVALUATIONS_ONLY, and the
        # native JSON events table holds none. The flag_evaluations swap can't move such a scan, because there
        # `person_id` applies person merges. So the scan reads `flag_evaluations` by name. Otherwise events holds every
        # flag call, and flag_evaluations only those of the teams that ingestion writes there.
        if not flag_calls_only_in_flag_evaluations(team):
            return cls(
                table=("events",),
                only_calls=parse_expr("event = '$feature_flag_called'"),
                flag_key=parse_expr("properties.$feature_flag"),
                response=parse_expr("toString(properties.$feature_flag_response)"),
                person_id=ast.Field(chain=["person_id"]),
            )
        return cls(
            table=("posthog", "flag_evaluations"),
            only_calls=ast.Constant(value=True),
            flag_key=ast.Field(chain=["flag_key"]),
            response=ast.Field(chain=["response"]),
            person_id=ast.Field(chain=["flag_evaluation_person_id"]),
        )

    def actor_column(self, group_type_index: int | None) -> ast.Expr:
        return self.person_id if group_type_index is None else ast.Field(chain=[f"$group_{group_type_index}"])
