/**
 * Minimal server-sent-events reader for a POST body.
 *
 * EventSource cannot send a request body, and /api/chat needs one (question,
 * k, mode, filters), so the stream is read off fetch's ReadableStream and the
 * `event:`/`data:` frames are parsed here.
 */
export async function streamSSE(url, body, onEvent, signal) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok || !res.body) {
    // An error response is ordinary JSON, not a stream.
    const raw = await res.text()
    let detail = raw.slice(0, 300)
    try { detail = JSON.parse(raw).detail || detail } catch { /* keep raw */ }
    throw new Error(detail || `HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Frames are separated by a blank line. The last piece may be a partial
    // frame, so it stays in the buffer until more bytes arrive.
    const frames = buffer.split('\n\n')
    buffer = frames.pop()

    for (const frame of frames) {
      let event = 'message'
      const data = []
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trim())
      }
      if (!data.length) continue
      onEvent(event, JSON.parse(data.join('\n')))
    }
  }
}
