from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.artefact_schemas import ReportLink
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.report_links import (
    duplicate_root,
    has_open_or_merged_pull_request,
    incoming_links,
    linked_reports,
    outgoing_links,
)


class TestReportLinkReaders(BaseTest):
    def _report(self, title: str = "t") -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title=title,
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )

    def _link(
        self,
        source: SignalReport,
        target: SignalReport,
        kind: ReportLinkKind,
        reason: str | None = None,
    ) -> SignalReportArtefact:
        return SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(source.id),
            content=ReportLink(kind=kind, report_id=str(target.id), reason=reason),
            attribution=ArtefactAttribution.system(),
        )

    @parameterized.expand([(False,), (True,)])
    def test_the_same_edge_reads_identically_from_either_end(self, replica_reads):
        source, target = self._report("source"), self._report("target")
        self._link(source, target, ReportLinkKind.DEPENDS_ON, reason="needs the schema first")

        with patch(
            "posthog.dbrouter.ReplicaRouter.db_for_read",
            return_value="unavailable_replica" if replica_reads else "default",
        ):
            outgoing = outgoing_links(team_id=self.team.id, report_id=source.id)
            incoming = incoming_links(team_id=self.team.id, report_id=target.id)

        assert outgoing == incoming
        assert outgoing[0].source_id == str(source.id)
        assert outgoing[0].target_id == str(target.id)
        assert outgoing[0].kind == ReportLinkKind.DEPENDS_ON
        assert outgoing[0].reason == "needs the schema first"

    def test_an_uppercase_report_id_still_finds_its_incoming_edges(self):
        source, target = self._report("source"), self._report("target")
        self._link(source, target, ReportLinkKind.PART_OF)

        assert len(incoming_links(team_id=self.team.id, report_id=str(target.id).upper())) == 1

    @parameterized.expand([("outgoing",), ("incoming",)])
    def test_a_row_that_no_longer_parses_names_no_edge(self, direction: str):
        source, target = self._report("source"), self._report("target")
        good = self._link(source, target, ReportLinkKind.FOLLOW_UP_OF)
        SignalReportArtefact.objects.create(
            team_id=self.team.id,
            report_id=source.id,
            type=SignalReportArtefact.ArtefactType.REPORT_LINK,
            content=f'{{"kind": "invented_kind", "report_id": "{target.id}"}}',
        )

        edges = (
            outgoing_links(team_id=self.team.id, report_id=source.id)
            if direction == "outgoing"
            else incoming_links(team_id=self.team.id, report_id=target.id)
        )

        assert [edge.kind for edge in edges] == [ReportLinkKind.FOLLOW_UP_OF]
        assert good.id is not None

    def test_a_reason_that_quotes_the_uuid_is_not_an_edge_to_it(self):
        source, target, bystander = self._report("source"), self._report("target"), self._report("bystander")
        self._link(source, bystander, ReportLinkKind.DEPENDS_ON, reason=f"not the same as {target.id}")

        assert incoming_links(team_id=self.team.id, report_id=target.id) == []

    def test_a_deleted_source_makes_no_claim_unless_the_reader_asks_for_one(self):
        source, target = self._report("source"), self._report("target")
        self._link(source, target, ReportLinkKind.RECURRENCE_OF)
        source.status = SignalReport.Status.DELETED
        source.save(update_fields=["status"])

        assert incoming_links(team_id=self.team.id, report_id=target.id) == []
        assert len(incoming_links(team_id=self.team.id, report_id=target.id, include_deleted_sources=True)) == 1

    def test_links_never_cross_a_team(self):
        source = self._report("source")
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"), name="other")
        target = self._report("target")
        self._link(source, target, ReportLinkKind.PART_OF)

        assert incoming_links(team_id=other_team.id, report_id=target.id) == []
        assert outgoing_links(team_id=other_team.id, report_id=source.id) == []

    def test_a_duplicate_chain_resolves_to_its_root(self):
        root, middle, leaf = self._report("root"), self._report("middle"), self._report("leaf")
        self._link(middle, root, ReportLinkKind.DUPLICATE_OF)
        self._link(leaf, middle, ReportLinkKind.DUPLICATE_OF)

        assert duplicate_root(team_id=self.team.id, report_id=leaf.id) == str(root.id)
        assert duplicate_root(team_id=self.team.id, report_id=middle.id) == str(root.id)
        assert duplicate_root(team_id=self.team.id, report_id=root.id) == str(root.id)

    def test_a_chain_deeper_than_the_budget_stops_instead_of_walking_on(self):
        # Written straight to the table: `add_log` refuses a chain this deep, so only rows that
        # predate that validation, or a concurrent write, can put the reader in front of one.
        reports = [self._report(f"r{index}") for index in range(SignalReportArtefact.MAX_REPORT_LINK_GRAPH_LEVELS + 3)]
        for child, parent in zip(reports[1:], reports[:-1]):
            SignalReportArtefact.objects.create(
                team_id=self.team.id,
                report_id=child.id,
                type=SignalReportArtefact.ArtefactType.REPORT_LINK,
                content=ReportLink(kind=ReportLinkKind.DUPLICATE_OF, report_id=str(parent.id)).model_dump_json(),
            )

        root = duplicate_root(team_id=self.team.id, report_id=reports[-1].id)

        assert root != str(reports[0].id)
        assert root in {str(report.id) for report in reports}

    def test_only_a_kind_the_reader_asked_for_comes_back(self):
        source, target = self._report("source"), self._report("target")
        self._link(source, target, ReportLinkKind.DEPENDS_ON)
        self._link(source, target, ReportLinkKind.PART_OF)

        kinds = [
            edge.kind
            for edge in outgoing_links(team_id=self.team.id, report_id=source.id, kinds=(ReportLinkKind.PART_OF,))
        ]

        assert kinds == [ReportLinkKind.PART_OF]

    def test_a_deleted_link_target_is_not_offered_as_context(self):
        live, deleted = self._report("live"), self._report("deleted")
        deleted.status = SignalReport.Status.DELETED
        deleted.save(update_fields=["status"])

        found = linked_reports(team_id=self.team.id, report_ids=[str(live.id), str(deleted.id)])

        assert set(found) == {str(live.id)}

    @parameterized.expand(
        [
            ("open", True),
            ("draft", True),
            ("merged", True),
            ("closed", False),
            ("unknown", True),
        ]
    )
    def test_a_pull_request_counts_as_work_until_it_is_known_closed(self, pr_state: str, expected: bool):
        from products.signals.backend.artefact_schemas import PullRequestLink
        from products.signals.backend.models import SignalReportPullRequest

        report = self._report("with-pr")
        pr = SignalReportPullRequest.objects.create(
            team_id=self.team.id,
            repository="owner/repo",
            number=7,
            url="https://github.com/owner/repo/pull/7",
            state=pr_state,
        )
        link = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=PullRequestLink(url=pr.url),
            attribution=ArtefactAttribution.system(),
        )
        link.pull_request = pr
        link.save(update_fields=["pull_request"])

        with_work = has_open_or_merged_pull_request(team_id=self.team.id, report_ids=[str(report.id)])

        assert (str(report.id) in with_work) is expected
