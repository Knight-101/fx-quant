import React, { useState } from 'react'
import { format } from 'date-fns'

async function postApi(path) {
  const r = await fetch(path, { method: 'POST' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export function KillSwitch({ data }) {
  const [loading, setLoading] = useState('')
  const [error,   setError]   = useState(null)

  const killArmed    = data?.kill_switch     ?? false
  const running      = data?.trader_running  ?? false
  const lastTs       = data?.ts

  const fmt = (ts) => {
    try { return format(new Date(ts), 'yyyy-MM-dd HH:mm:ss') } catch { return ts || '—' }
  }

  const handle = async (action) => {
    setLoading(action)
    setError(null)
    try {
      await postApi(`/api/${action}`)
    } catch (e) {
      setError(`${action} failed: ${e.message}`)
    } finally {
      setLoading('')
    }
  }

  return (
    <div className="card flex flex-wrap items-center gap-4 px-4 py-3">
      {/* Kill switch */}
      <div className="flex items-center gap-3">
        {!killArmed ? (
          <button
            onClick={() => handle('kill')}
            disabled={loading === 'kill'}
            className="px-4 py-2 rounded font-bold text-xs tracking-widest uppercase transition-all"
            style={{
              background:  loading === 'kill' ? '#7f1d1d' : '#dc2626',
              color:       'white',
              border:      '1px solid #ef4444',
              cursor:      loading ? 'not-allowed' : 'pointer',
              boxShadow:   '0 0 12px rgba(220,38,38,0.3)',
            }}
          >
            {loading === 'kill' ? 'ARMING...' : 'KILL SWITCH'}
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <div
              className="px-3 py-2 rounded font-bold text-xs tracking-widest uppercase"
              style={{
                background: '#7f1d1d',
                color:      '#ef4444',
                border:     '1px solid #ef4444',
                boxShadow:  '0 0 12px rgba(220,38,38,0.5)',
              }}
            >
              KILL ARMED
            </div>
            <button
              onClick={() => handle('disarm')}
              disabled={loading === 'disarm'}
              className="px-3 py-2 rounded font-bold text-xs tracking-widest uppercase transition-all"
              style={{
                background: '#052e16',
                color:      '#00d4aa',
                border:     '1px solid #00d4aa',
                cursor:     loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading === 'disarm' ? 'DISARMING...' : 'DISARM'}
            </button>
          </div>
        )}
      </div>

      {/* Divider */}
      <div className="w-px h-8 bg-border" />

      {/* Trader start/stop */}
      <div className="flex items-center gap-3">
        <div
          className="flex items-center gap-1.5 text-[10px]"
        >
          <div
            className="w-2 h-2 rounded-full"
            style={{
              background: running ? '#00d4aa' : '#6b7280',
              animation:  running ? 'pulse-green 2s infinite' : 'none',
            }}
          />
          <span style={{ color: running ? '#00d4aa' : '#6b7280' }} className="font-bold uppercase tracking-widest">
            Trader {running ? 'Running' : 'Stopped'}
          </span>
        </div>

        {!running ? (
          <button
            onClick={() => handle('trader/start')}
            disabled={!!loading}
            className="px-3 py-1.5 rounded font-bold text-[10px] tracking-widest uppercase transition-all"
            style={{
              background: '#052e16',
              color:      '#00d4aa',
              border:     '1px solid #00d4aa60',
              cursor:     loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading === 'trader/start' ? 'STARTING...' : 'START TRADER'}
          </button>
        ) : (
          <button
            onClick={() => handle('trader/stop')}
            disabled={!!loading}
            className="px-3 py-1.5 rounded font-bold text-[10px] tracking-widest uppercase transition-all"
            style={{
              background: '#1c0a0a',
              color:      '#ef4444',
              border:     '1px solid #ef444460',
              cursor:     loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading === 'trader/stop' ? 'STOPPING...' : 'STOP TRADER'}
          </button>
        )}
      </div>

      {/* Divider */}
      <div className="w-px h-8 bg-border" />

      {/* Last bar time */}
      <div className="text-[10px] text-text-secondary">
        <span className="text-muted mr-1">Last snapshot:</span>
        <span className="tabular-nums">{fmt(lastTs)}</span>
      </div>

      {/* Error */}
      {error && (
        <div className="text-[10px] text-danger ml-2">{error}</div>
      )}
    </div>
  )
}
