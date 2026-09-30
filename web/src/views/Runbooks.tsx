import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";

/** Minimal markdown for the runbooks: #, ##, numbered and bulleted lists, paragraphs. */
function Markdown({ text }: { text: string }) {
  const blocks: JSX.Element[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(<Tag key={blocks.length}>{list.items.map((t, i) => <li key={i}>{t}</li>)}</Tag>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const ordered = /^\d+\.\s/.test(line);
    if (ordered || line.startsWith("- ")) {
      const item = line.replace(/^(\d+\.|-)\s/, "");
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push(item);
      continue;
    }
    flush();
    if (!line) continue;
    if (line.startsWith("## ")) blocks.push(<h2 key={blocks.length}>{line.slice(3)}</h2>);
    else if (line.startsWith("# ")) blocks.push(<h1 key={blocks.length}>{line.slice(2)}</h1>);
    else blocks.push(<p key={blocks.length}>{line}</p>);
  }
  flush();
  return <div className="md">{blocks}</div>;
}

export function Runbooks() {
  const [books] = useLoad((s) => api.runbooks(s), []);
  const [id, setId] = useState<string | null>(null);
  const current = books?.find((b) => b.id === id) ?? books?.[0];
  return (
    <div className="view">
      <header className="view-head">
        <span className="eyebrow">Runbooks</span>
        <div className="row"><h1 className="display">What the agent reads.</h1></div>
        <p className="lead">The agent searches these with BM25 by symptom or exact error message, the way an engineer searches the wiki mid-incident.</p>
      </header>
      <section className="rb">
        <div className="card">
          <ul className="table-list">
            {books?.map((b) => (
              <li key={b.id}>
                <button className={current?.id === b.id ? "on" : undefined} onClick={() => setId(b.id)}><span>{b.title}</span></button>
              </li>
            ))}
          </ul>
        </div>
        <div className="card">{current && <Markdown text={current.markdown} />}</div>
      </section>
    </div>
  );
}
