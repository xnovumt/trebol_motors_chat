import { useState, useRef, useEffect } from 'react'
import './App.css'

const SUGERENCIAS = [
  'camioneta diésel barata en buen estado',
  '¿cuáles están en estado excelente?',
  'camioneta con menos kilómetros',
]

function relPct(d) {
  return Math.max(0, Math.min(100, Math.round((1 - Number(d)) * 100)))
}

function Fuentes({ sources }) {
  if (!sources?.length) return null
  return (
    <div className="sources">
      <h3>Fuentes</h3>
      {sources.map((s) => {
        const ids = Object.entries(s.ids || {}).map(([k, v]) => `${k}: ${v}`).join(' · ')
        const pct = relPct(s.dist)
        return (
          <div className="src" key={s.n}>
            <div className="src-top">
              <span className="tag">[{s.n}] {ids || 'fila'}</span>
              <span className="rel" title={`Relevancia (distancia ${s.dist})`}>
                <span className="relbar"><i style={{ width: `${pct}%` }} /></span>{pct}%
              </span>
            </div>
            <p>{s.texto}</p>
          </div>
        )
      })}
    </div>
  )
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scroller = useRef(null)

  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, loading])

  async function ask(q) {
    const text = q.trim()
    if (!text || loading) return
    setMessages((m) => [...m, { role: 'user', text }])
    setInput('')
    setLoading(true)
    try {
      const r = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `Error ${r.status}`)
      setMessages((m) => [...m, { role: 'bot', text: data.answer, sources: data.sources }])
    } catch (err) {
      setMessages((m) => [...m, {
        role: 'bot', error: true,
        text: `No se pudo responder: ${err.message}. ¿Está corriendo Ollama y server.py?`,
      }])
    } finally {
      setLoading(false)
    }
  }

  function onSubmit(e) {
    e.preventDefault()
    ask(input)
  }
  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      ask(input)
    }
  }

  return (
    <>
      <header className="topbar">
        <div className="logo" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 17H3v-5l2-5h10l4 5h2v5h-2" /><circle cx="7.5" cy="17.5" r="2" /><circle cx="16.5" cy="17.5" r="2" /></svg>
        </div>
        <div>
          <h1>Trébol Motors</h1>
          <p><span className="dot" />Asistente de vehículos · RAG local</p>
        </div>
      </header>

      <main className="chat" ref={scroller} role="log" aria-live="polite" aria-label="Conversación">
        <div className="wrap">
          {messages.length === 0 && (
            <div className="empty">
              <p className="big">Pregunta sobre tus vehículos</p>
              <p>Respuestas con fuentes citadas, directo desde tu Supabase.</p>
              <div className="chips">
                {SUGERENCIAS.map((s) => (
                  <button className="chip" type="button" key={s} onClick={() => ask(s)}>{s}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div className={`msg ${m.role}`} key={i}>
              <div className={`avatar ${m.role === 'user' ? 'you' : 'bot'}`} aria-hidden="true">
                {m.role === 'user' ? 'Tú' : 'IA'}
              </div>
              <div className={`bubble${m.error ? ' err' : ''}`}>
                {m.text}
                {m.role === 'bot' && !m.error && <Fuentes sources={m.sources} />}
              </div>
            </div>
          ))}

          {loading && (
            <div className="msg bot">
              <div className="avatar bot" aria-hidden="true">IA</div>
              <div className="bubble typing"><span /><span /><span /></div>
            </div>
          )}
        </div>
      </main>

      <footer className="composer">
        <form onSubmit={onSubmit}>
          <label htmlFor="q" className="sr-only">Tu pregunta</label>
          <textarea
            id="q" rows="1" placeholder="Escribe tu pregunta…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button className="send" type="submit" disabled={loading || !input.trim()} aria-label="Enviar pregunta">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="19" x2="12" y2="5" /><polyline points="5 12 12 5 19 12" /></svg>
          </button>
        </form>
      </footer>
    </>
  )
}
