### SQL in an analysis

When the deliverable is a notebook, build the analysis in it as you go, not after. Create the notebook first with a title and the question, then add each query that a reported number depends on as a SQL cell (`notebooks-add-cell` with `cell_type: 'sql'`). Every run returns the columns and a row preview: read them before you write the prose that interprets them. Use `execute-sql` only for throwaway checks the notebook does not rely on, like confirming a table's columns.

{fix_in_place}

- Don't retype a cell's result as a markdown table. The cell already shows the table; the prose says what it means.
- To chart a result, set `visualization` on the SQL cell. Don't save a separate SQL insight for a chart that lives in the notebook; save an insight only when the user wants it outside the notebook.
{run_later}
