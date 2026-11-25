async function submit() {
  const { task, draft, busy } = getState();
  if (busy || !draft.trim()) return;
  setState({busy:true, error:""});
  try {
    if (task) {
      const reply = await host.call("tasks","reply",{id:task.id,text:draft});
      setState(s => ({messages:s.messages.concat(reply.content)}));
    } else {
      const created = await host.call("tasks","create",{text:draft});
      setState({task:created});
    }
    setState(s => ({draft:s.draft === draft ? "" : s.draft}));
  } catch (e) { setState({error:e.message}); }
  finally { setState({busy:false}); }
}
async function refresh() {
  const {task,busy} = getState();
  if (!task || busy) return;
  setState({busy:true,error:""});
  try { setState({messages:await host.call("tasks","thread",{id:task.id})}); }
  catch (e) {setState({error:e.message});}
  finally {setState({busy:false});}
}
view({
  state:{task:null,draft:"",messages:[],busy:false,error:""},
  render(s) {
    const action=s.task ? "Add reply" : "Create task";
    return Page(Reading({gap:16},
      Header({title:s.task ? s.task.title : "New task",subtitle:"Local PostHog project"},
        s.task && IconButton("refresh-cw",{label:"Refresh discussion",disabled:s.busy,onClick:refresh})),
      s.task && Scroll({id:"discussion",gap:12}, ...(s.messages.length
        ? s.messages.map(text => Column({gap:2},Caption("You"),Text(text)))
        : [Caption("No replies yet.")])),
      Form({id:"compose"},Field({label:s.task ? "Reply" : "Description",for:"draft"},
        Input({id:"draft",label:s.task ? "Reply" : "Description",value:s.draft,placeholder:s.task ? "Add to the discussion…" : "What needs to be done?",
          onChange:draft=>setState({draft}),onSubmit:submit})),
        s.error && ErrorMessage(s.error),
        Row(Button(s.busy ? "Working…" : action,{id:"submit-task",variant:"primary",disabled:s.busy || !s.draft.trim(),onClick:submit})))));
  },
  inspect:s=>({task:s.task,messages:s.messages,busy:s.busy,error:s.error}),
});
