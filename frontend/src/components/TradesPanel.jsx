import React, { useState } from 'react'
import { formatDistanceToNow, parseISO, format } from 'date-fns'

const TAB_OPEN    = 'open'
const TAB_PENDING = 'pending'
const TAB_HISTORY = 'history'

function TabBtn({ id, active, count, onClick }) {
  return (
    <button
      onClick={() => onClick(id)}
      className="px-3 py-1.5 text-[10px] font-bold tracking-widest uppercase transition-colors"
      style={{
        color:           active ? '#2196f3' : '#6b7280',
        borderBottom:    active ? '2px solid #2196f3' : '2px solid transparent',
        background:      'transparent',
        cursor:          'pointer',
      }}
    >
      {id} {count != null ? <span className="ml-1 opacity-70">({count})</span> : null}
    </button>
  )
}

function OpenTradesTable({ trades }) {
  if (!trades.length) {
    return <div className="text-[10px] text-muted p-3">No open trades</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px]">
        <thead>
          <tr style={{ borderBottom: '1px solid #2a3050' }}>
            <th className="text-left px-2 py-1.5 text-text-secondary font-medium">Instrument</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Units</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Open Price</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Unrealized P&L</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Margin</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const upl = parseFloat(t.unrealizedPL ?? 0)
            return (
              <tr key={i} style={{ borderBottom: '1px solid #2a305040' }}>
                <td className="px-2 py-1.5 font-bold text-accent">{t.instrument}</td>
                <td
                  className="px-2 py-1.5 text-right tabular-nums"
                  style={{ color: Number(t.currentUnits) > 0 ? '#00d4aa' : '#ef4444' }}
                >
                  {Number(t.currentUnits).toLocaleString()}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-text-secondary">
                  {Number(t.price ?? t.openPrice ?? 0).toFixed(5)}
                </td>
                <td
                  className="px-2 py-1.5 text-right tabular-nums font-bold"
                  style={{ color: upl >= 0 ? '#00d4aa' : '#ef4444' }}
                >
                  {upl >= 0 ? '+' : ''}{upl.toFixed(2)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-text-secondary">
                  {Number(t.marginUsed ?? 0).toLocaleString('en-SG', { maximumFractionDigits: 0 })}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function PendingTable({ pending }) {
  if (!pending.length) {
    return <div className="text-[10px] text-muted p-3">No pending orders</div>
  }
  const formatExpiry = (ts) => {
    try { return formatDistanceToNow(parseISO(ts), { addSuffix: true }) } catch { return ts }
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px]">
        <thead>
          <tr style={{ borderBottom: '1px solid #2a3050' }}>
            <th className="text-left px-2 py-1.5 text-text-secondary font-medium">Pair</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Order ID</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Expires</th>
          </tr>
        </thead>
        <tbody>
          {pending.map((o, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #2a305040' }}>
              <td className="px-2 py-1.5 font-bold text-warning">{o.pair}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-text-secondary font-mono">
                #{o.order_id}
              </td>
              <td className="px-2 py-1.5 text-right text-warning">
                {formatExpiry(o.expires_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function HistoryTable({ tradeLog }) {
  const fills = tradeLog.filter(e => e.event === 'fill').slice().reverse()
  if (!fills.length) {
    return <div className="text-[10px] text-muted p-3">No fill events yet</div>
  }
  const fmt = (ts) => {
    try { return format(new Date(ts), 'MM-dd HH:mm') } catch { return ts }
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px]">
        <thead>
          <tr style={{ borderBottom: '1px solid #2a3050' }}>
            <th className="text-left px-2 py-1.5 text-text-secondary font-medium">Time</th>
            <th className="text-left px-2 py-1.5 text-text-secondary font-medium">Pair</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Dir</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Units</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Fill Price</th>
            <th className="text-right px-2 py-1.5 text-text-secondary font-medium">Z</th>
          </tr>
        </thead>
        <tbody>
          {fills.map((f, i) => {
            const dir = Number(f.direction ?? 0)
            return (
              <tr key={i} style={{ borderBottom: '1px solid #2a305040' }}>
                <td className="px-2 py-1.5 tabular-nums text-muted">{fmt(f.timestamp)}</td>
                <td className="px-2 py-1.5 font-bold text-accent">{f.pair}</td>
                <td
                  className="px-2 py-1.5 text-right font-bold"
                  style={{ color: dir > 0 ? '#00d4aa' : '#ef4444' }}
                >
                  {dir > 0 ? '▲ LONG' : '▼ SHORT'}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-text-secondary">
                  {Number(f.units ?? 0).toLocaleString()}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-text-secondary">
                  {f.fill_price != null ? Number(f.fill_price).toFixed(5) : '—'}
                </td>
                <td
                  className="px-2 py-1.5 text-right tabular-nums"
                  style={{ color: Number(f.z_score ?? 0) > 0 ? '#00d4aa' : '#ef4444' }}
                >
                  {f.z_score != null ? Number(f.z_score).toFixed(2) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function TradesPanel({ data }) {
  const [tab, setTab] = useState(TAB_OPEN)

  const openTrades = data?.open_trades    || []
  const pending    = data?.pending_orders || []
  const tradeLog   = data?.trade_log      || []

  return (
    <div className="card flex flex-col h-full overflow-hidden">
      {/* Tabs */}
      <div
        className="flex items-center border-b border-border flex-shrink-0"
        style={{ background: '#141929' }}
      >
        <TabBtn id={TAB_OPEN}    active={tab === TAB_OPEN}    count={openTrades.length} onClick={setTab} />
        <TabBtn id={TAB_PENDING} active={tab === TAB_PENDING} count={pending.length}    onClick={setTab} />
        <TabBtn id={TAB_HISTORY} active={tab === TAB_HISTORY} count={null}              onClick={setTab} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {tab === TAB_OPEN    && <OpenTradesTable trades={openTrades} />}
        {tab === TAB_PENDING && <PendingTable    pending={pending} />}
        {tab === TAB_HISTORY && <HistoryTable    tradeLog={tradeLog} />}
      </div>
    </div>
  )
}
