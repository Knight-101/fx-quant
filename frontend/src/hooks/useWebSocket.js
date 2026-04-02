import { useState, useEffect, useRef, useCallback } from 'react'

const MAX_BACKOFF_MS = 30_000
const BASE_BACKOFF_MS = 1_000

export function useWebSocket() {
  const [data, setData]           = useState(null)
  const [connected, setConnected] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)

  const wsRef       = useRef(null)
  const backoffRef  = useRef(BASE_BACKOFF_MS)
  const mountedRef  = useRef(true)
  const timerRef    = useRef(null)

  const connect = useCallback(() => {
    if (!mountedRef.current) return

    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url   = `${proto}://${location.host}/ws`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) return
      setConnected(true)
      backoffRef.current = BASE_BACKOFF_MS
    }

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return
      try {
        const parsed = JSON.parse(ev.data)
        setData(parsed)
        setLastUpdate(new Date())
      } catch {
        // ignore malformed frames
      }
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setConnected(false)
      const delay = backoffRef.current
      backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS)
      timerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      clearTimeout(timerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
    }
  }, [connect])

  return { data, connected, lastUpdate }
}
