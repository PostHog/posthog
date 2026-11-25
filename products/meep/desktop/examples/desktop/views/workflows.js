async function readEntry(id = getState().recipe.id) {
  const entry = (await host.workflows.list()).find(item => item.id === id);
  if (!entry) throw Error("The workflow is no longer registered.");
  setState({recipe:entry.payload.definition, trace:entry.payload.lastTrace || null});
}

async function refresh() {
  if (getState().busy) return;
  setState({busy:true, error:""});
  try {
    await host.workflows.execute(getState().recipe.id);
  } catch (e) {
    setState({error:e.message});
  } finally {
    try { await readEntry(); }
    catch (e) { setState({error:e.message}); }
    setState({busy:false});
  }
}

async function closeEditor() {
  setState({editing:false});
  try { await readEntry(); }
  catch (e) { setState({error:e.message}); }
}

view({
  state:{busy:false, error:"", tab:0, trace:null, recipe:null, editing:false, step:null, selected:null},
  async init() {
    try {
      const definition = await host.call("recipes","initial",{});
      const entries = await host.workflows.list();
      if (!entries.some(entry => entry.id === definition.id))
        await host.workflows.register(definition);
      await readEntry(definition.id);
      await refresh();
    } catch (e) { setState({error:e.message}); }
  },
  render(s) {
    if (s.editing && s.recipe) return WorkflowEditor({
      id:"recipe-editor",definition:s.recipe,...(s.step ? {step:s.step} : {}),onClose:closeEditor
    });
    const count = host.data.count("runs");
    const edit = step => setState({editing:true,step});
    return Page(Reading({gap:12},
      Header({title:"Run history"},
        s.tab === 1
          ? Button("Edit definition",{id:"edit-workflow",disabled:s.busy || !s.recipe,onClick:()=>edit(null)})
          : Button(s.busy ? "Refreshing…" : "Refresh",{id:"run-workflow",disabled:s.busy || !s.recipe,onClick:refresh})),
      Tabs({id:"workflow-tabs",items:["Results","Steps"],selected:s.tab,underline:true,onChange:tab=>setState({tab})}),
      s.error && ErrorMessage(s.error),
      s.tab === 1
        ? (s.recipe ? WorkflowOutline({id:"history-steps",definition:s.recipe,...(s.trace ? {trace:s.trace} : {}),onEdit:edit,grow:true,minH:0}) : Loading())
        : count
          ? Column({gap:8},Table({id:"history-results",data:"runs",h:138,selected:s.selected,onRowClick:selected=>setState({selected}),columns:[
              {field:"outcome",title:"Status",w:104},
              {field:"duration",title:"Duration",w:80},
              {field:"shortId",title:"Run ID",kind:"mono",w:86}
            ]}),s.selected && ReadOnly("Run ID",s.selected))
          : (s.busy || (!s.recipe && !s.error)) ? Loading() : Empty("No recent runs", "Refresh to check for activity.")));
  },
  inspect:s=>({busy:s.busy,error:s.error,tab:s.tab,editing:s.editing,selected:s.selected,recipe:s.recipe,trace:s.trace,rows:host.data.rows("runs")}),
});
