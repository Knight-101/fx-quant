import React, { useRef, useEffect } from 'react'
import { format } from 'date-fns'

const EVENT_CFG = {
  order_placed: { label: 'ORDER', color: '#f59e0b', bg: '#f59e0b20' },
  fill:         { label: 'FILL',  color: '#00d4aa', bg: '#00d4aa20' },
  skip:         { label: 'SKIP',  color: '#6b7280', bg: '#6b728020' },
}

function LogEntry({ entry }) {
  const ev  = entry.event || 'order_placed'
  const cfg = EVENT_CFG[ev] || EVENT_CFG.order_placed

  const fmt = (ts) => {
    try { return format(new Date(ts), 'MM-dd HH:mm:ss') } catch { return ts }
  }

  const dir   = Number(entry.direction ?? 0)
  const arrow = dir > 0 ? '▲' : dir < 0 ? '▼' : '—'
  const arrowColor = dir > 0 ? '#00d4aa' : dir < 0 ? '#ef4444' : '#6b7280'

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5"
      style={{ borderBottom: '1px solid #2a305030' }}
    >
      {/* Time */}
      <span className="text-[9px] text-muted tabular-nums w-28 flex-shrink-0">
        {fmt(entry.timestamp)}
      </span>

      {/* Event badge */}
      <span
        className="text-[8px] font-bold px-1.5 py-0.5 rounded flex-shrink-0"
        style={{ color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.color}40` }}
      >
        {cfg.label}
      </span>

      {/* Pair */}
      <span className="text-[10px] font-bold text-accent flex-shrink-0 w-16">
        {entry.pair || '—'}
      </span>

      {/* Direction */}
      <span className="flex-shrink-0" style={{ color: arrowColor, fontSize: 10 }}>
        {arrow}
      </span>

      {/* Key data */}
      <div className="flex gap-2 flex-wrap text-[9px] text-text-secondary min-w-0">
        {entry.z_score != null && (
          <span>z={Number(entry.z_score).toFixed(2)}</span>
        )}
        {entry.units != null && (
          <span>u={Number(entry.units).toLocaleString()}</span>
        )}
        {entry.limit_price != null && (
          <span>@{Number(entry.limit_price).toFixed(5)}</span>
        )}
        {entry.fill_price != null && (
          <span className="text-success">fill@{Number(entry.fill_price).toFixed(5)}</span>
        )}
        {entry.regime && (
          <span className="text-muted capitalize">[{entry.regime}]</span>
        )}
      </div>
    </div>
  )
}

export function SignalLog({ data }) {
  const tradeLog = data?.trade_log || []
  const recent   = tradeLog.slice(-20).reverse()
  const listRef  = useRef(null)

  return (
    <div className="card flex flex-col h-full overflow-hidden">
      <div className="px-3 py-2 border-b border-border flex-shrink-0">
        <span className="text-xs font-bold tracking-wider text-text-primary">SIGNAL LOG</span>
        <span className="ml-2 text-[9px] text-muted">last 20 events</span>
      </div>
      <div ref={listRef} className="flex-1 overflow-y-auto">
        {recent.length === 0 ? (
          <div className="text-[10px] text-muted p-3">No events yet</div>
        ) : (
          recent.map((entry, i) => (
            <LogEntry key={i} entry={entry} />
          ))
        )}
      </div>
    </div>
  )
}
