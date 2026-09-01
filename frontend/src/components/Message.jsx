function Sources({ sources }) {
  if (!sources || sources.length === 0) {
    return null
  }

  return (
    <div className="sources">
      <span className="sources-label">Sources</span>
      <ul>
        {sources.map((s, i) => (
          <li key={i}>
            {s.source} {s.page != null && <>&middot; page {s.page}</>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function Message({ role, content, sources }) {
  return (
    <div className={`message ${role}`}>
      <div className="bubble">{content}</div>
      {role === 'assistant' && <Sources sources={sources} />}
    </div>
  )
}
