from django.test import SimpleTestCase

from parameterized import parameterized

from products.notebooks.backend.python_analysis import analyze_python_globals


class TestAnalyzePythonGlobalsUsed(SimpleTestCase):
    @parameterized.expand(
        [
            # A ref read before it is reassigned is still an input: `df` must be re-materialized
            # every run, else the node runs against the mutated frame left by its previous run.
            ("reassigned_after_read", "df.columns = ['a', 'b']\ndf = df.assign(x=1)", ["df"]),
            ("read_then_reassigned_via_call", "out = df.agg('sum')\ndf = df.head()", ["df"]),
            # A name created before it is read is a genuine local, not an input — materializing it
            # would clobber the user's own frame.
            ("assigned_before_read", "import pandas as pd\ndf = pd.DataFrame()\ndf.head()", []),
            # Loop, function, walrus, and match-capture locals must not leak in as phantom inputs.
            ("loop_variable", "for col in df.columns:\n    print(df[col].sum())", ["df"]),
            ("function_local", "def f():\n    x = 1\n    return x + df.iloc[0]", ["df"]),
            ("walrus_local", "if (rows := len(df)):\n    print(rows)", ["df"]),
            ("match_capture", "match df.shape:\n    case (rows, cols):\n        print(rows, cols)", ["df"]),
        ]
    )
    def test_used_globals(self, _name: str, code: str, expected: list[str]) -> None:
        self.assertEqual(analyze_python_globals(code).used, expected)
