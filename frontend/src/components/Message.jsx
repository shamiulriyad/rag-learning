export default function Message({ role, content }) {
  return (
    <div className={`message ${role}`}>
      <div className="bubble">{content}</div>
    </div>
  )
}
