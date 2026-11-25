const articles = [
  ["Designing for interruption", "Interaction design", false],
  ["The shape of a good list", "Interface notes", false],
  ["Working with small windows", "Desktop patterns", true],
];
view({
  state: { read: articles.map(article => article[2]), filter: 0 },
  render(s) {
    const rows = articles.map(([title, subject], i) => ({ title, subject, i }))
      .filter(row => !s.filter || !s.read[row.i]);
    return Page(Reading({gap: 16},
      Header({title: "Reading list", subtitle: "Saved articles"}),
      Tabs({id: "filter", items: ["All articles", "Unread"], selected: s.filter,
        onChange: filter => setState({filter})}),
      Scroll({gap: 0}, ...rows.map(({title, subject, i}) =>
        Row({gap:12,py:10,border:"bottom"},
          Column({gap:3,grow:true}, Text(title), Caption(subject)),
          Button(s.read[i] ? "Mark unread" : "Mark read", {
            id:"article-" + i, variant:"secondary",
            onClick: () => setState(st => ({read: st.read.map((v, n) => i === n ? !v : v)}))
          }))),
        !rows.length && Empty("All caught up", "Choose All articles to see your reading list."))));
  },
  inspect: s => ({read:s.read, filter:s.filter}),
});
