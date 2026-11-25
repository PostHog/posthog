async function increment() {
  const count = await host.call("counter", "add", { count: getState().count });
  setState({ count });
}

view({
  state: { count: 0 },
  render: state => Page(Column(
    Heading("Counter"),
    Text(String(state.count)),
    Button("Add one", { id: "increment", onClick: increment })
  )),
  commands: { increment }
});
