import pytest

from parameterized import parameterized

from products.merge_queue.backend.grammar.evaluator import PRFacts, evaluate
from products.merge_queue.backend.grammar.parser import Atom, AtomKind, GrammarError, parse


def _facts(*, approved=True, checks_green=True, files=(), labels=()) -> PRFacts:
    return PRFacts(approved, checks_green, frozenset(files), frozenset(labels))


class TestParse:
    @parameterized.expand(
        [
            ("approved", (Atom(AtomKind.APPROVED),)),
            ("checks-green", (Atom(AtomKind.CHECKS_GREEN),)),
            ("files~=frontend/**", (Atom(AtomKind.FILES_GLOB, value="frontend/**"),)),
            ("label=automerge", (Atom(AtomKind.LABEL, value="automerge"),)),
            ("!approved", (Atom(AtomKind.APPROVED, negated=True),)),
            ("not approved", (Atom(AtomKind.APPROVED, negated=True),)),
            (
                "approved checks-green files~=ee/**",
                (Atom(AtomKind.APPROVED), Atom(AtomKind.CHECKS_GREEN), Atom(AtomKind.FILES_GLOB, value="ee/**")),
            ),
        ]
    )
    def test_parse_valid(self, source, expected_atoms):
        assert parse(source).atoms == expected_atoms

    @parameterized.expand(
        [
            ("empty", ""),
            ("whitespace", "   "),
            ("unknown", "merge-me"),
            ("bare files", "files~="),
            ("bare label", "label="),
            ("dangling not", "approved not"),
            ("double not", "not not approved"),
            ("dangling bang", "!"),
        ]
    )
    def test_parse_rejects_malformed(self, _name, source):
        with pytest.raises(GrammarError):
            parse(source)


class TestEvaluate:
    @parameterized.expand(
        [
            ("approved true", "approved", {"approved": True}, True),
            ("approved false", "approved", {"approved": False}, False),
            ("negation flips", "!approved", {"approved": False}, True),
            ("checks-green missing", "checks-green", {"checks_green": False}, False),
            ("glob matches nested", "files~=frontend/**", {"files": ["frontend/src/app.tsx"]}, True),
            ("glob no match", "files~=frontend/**", {"files": ["ee/api.py"]}, False),
            ("not glob excludes", "!files~=ee/**", {"files": ["ee/api.py"]}, False),
            ("label present", "label=automerge", {"labels": ["automerge"]}, True),
            ("label absent", "label=automerge", {"labels": ["wip"]}, False),
        ]
    )
    def test_single_term(self, _name, source, facts_kwargs, expected):
        assert evaluate(source, _facts(**facts_kwargs)) is expected

    def test_implicit_and_requires_all(self):
        eligible = "approved checks-green !label=wip"
        assert evaluate(eligible, _facts(approved=True, checks_green=True, labels=[])) is True
        # one failing conjunct fails the whole predicate
        assert evaluate(eligible, _facts(approved=True, checks_green=True, labels=["wip"])) is False
        assert evaluate(eligible, _facts(approved=False, checks_green=True, labels=[])) is False
