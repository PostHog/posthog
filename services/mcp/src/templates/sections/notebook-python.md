### Python in an analysis

When an analysis needs Python — dataframe manipulation, statistics, clustering, forecasting, plotting, anything SQL can't express — run it in a notebook Python cell (`notebooks-add-cell` with `cell_type: 'python'`), not in a runtime the user can't see. The point is transparency: the code, its output, and its errors sit in the document next to the result, and the user can read, edit, and re-run them. A number produced in a hidden interpreter is one they have to take on faith.

Do this by default, without being asked, whenever the Python is part of the analysis being delivered. Create a notebook for it if none exists yet. Python cells read upstream cells' dataframes by name, so the usual shape is: SQL cell pulls the data → Python cell analyzes it → markdown cell says what it means. The sandbox has pandas, numpy, scipy, scikit-learn, and matplotlib.

The exception is throwaway scratch work that isn't part of the deliverable, like a quick sanity check on a figure. If a computation is load-bearing for a conclusion you report, it belongs in a cell.

To refresh a notebook somebody already wrote, use `notebooks-run` rather than re-running the cells one at a time. It runs every SQL and Python cell in document order and can set the notebook's variables in the same call, so a report for a new time window is one call.
