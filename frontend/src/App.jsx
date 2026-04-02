import React from 'react'
import { formatDistanceToNow } from 'date-fns'

import { useWebSocket }  from './hooks/useWebSocket.js'
import { MetricsBar }    from './components/MetricsBar.jsx'
import { EquityCurve }   from './components/EquityCurve.jsx'
import { RegimePanel }   from './components/RegimePanel.jsx'
import { PairGrid }      from './components/PairGrid.jsx'
import { TradesPanel }   from './components/TradesPanel.jsx'
import { SignalLog }     from './components/SignalLog.jsx'
import { PnlByPair }     from './components/PnlByPair.jsx'
import { KillSwitch }    from './components/KillSwitch.jsx'

// ── Connection status pill ────────────────────────────────────────────────────
function ConnectionStatus({ connected, lastUpdate }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1 text-[9px]">
      <div
        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
        style={{
          background: connected ? '#00d4aa' : '#ef4444',
          animation:  connected ? 'pulse-green 2s infinite' : 'none',
        }}
      />
      <span style={{ color: connected ? '#00d4aa' : '#ef4444' }}>
        {connected ? 'LIVE' : 'DISCONNECTED'}
      </span>
      {lastUpdate && (
        <span className="text-muted">
          · {formatDistanceToNow(lastUpdate, { addSuffix: true })}
        </span>
      )}
    </div>
  )
}

// ── Header bar ────────────────────────────────────────────────────────────────
function Header({ connected, lastUpdate }) {
  return (
    <div
      className="flex items-center justify-between px-4 py-2 flex-shrink-0"
      style={{ borderBottom: '1px solid #2a3050', background: '#0d1122' }}
    >
      <div className="flex items-center gap-3">
        <span
          className="text-sm font-black tracking-[0.3em] uppercase"
          style={{ color: '#2196f3', textShadow: '0 0 20px rgba(33,150,243,0.5)' }}
        >
          FX1
        </span>
        <span className="text-[10px] text-text-secondary tracking-wider">
          USD Factor Residual · Hawkes Spread · M30 OANDA
        </span>
      </div>
      <ConnectionStatus connected={connected} lastUpdate={lastUpdate} />
    </div>
  )
}

// ── Main layout ───────────────────────────────────────────────────────────────
export default function App() {
  const { data, connected, lastUpdate } = useWebSocket()

  return (
    <div
      className="flex flex-col"
      style={{
        minHeight:  '100vh',
        background: '#0a0e1a',
        color:      '#e2e8f0',
      }}
    >
      {/* Header */}
      <Header connected={connected} lastUpdate={lastUpdate} />

      {/* Scrollable content */}
      <div
        className="flex-1 flex flex-col gap-2 p-2 overflow-y-auto"
        style={{ minHeight: 0 }}
      >
        {/* Row 1: Metrics bar */}
        <div className="flex-shrink-0">
          <MetricsBar data={data} />
        </div>

        {/* Row 2: Equity Curve (60%) + Regime Panel (40%) */}
        <div className="grid gap-2 flex-shrink-0" style={{ gridTemplateColumns: '3fr 2fr', height: 280 }}>
          <div style={{ minHeight: 0, height: '100%' }}>
            <EquityCurve data={data} />
          </div>
          <div style={{ minHeight: 0, height: '100%' }}>
            <RegimePanel data={data} />
          </div>
        </div>

        {/* Row 3: Pair Grid (60%) + Trades Panel (40%) */}
        <div className="grid gap-2 flex-shrink-0" style={{ gridTemplateColumns: '3fr 2fr', height: 360 }}>
          <div style={{ minHeight: 0, height: '100%' }}>
            <PairGrid data={data} />
          </div>
          <div style={{ minHeight: 0, height: '100%' }}>
            <TradesPanel data={data} />
          </div>
        </div>

        {/* Row 4: Signal Log (50%) + PnL by Pair (50%) */}
        <div className="grid gap-2 flex-shrink-0" style={{ gridTemplateColumns: '1fr 1fr', height: 280 }}>
          <div style={{ minHeight: 0, height: '100%' }}>
            <SignalLog data={data} />
          </div>
          <div style={{ minHeight: 0, height: '100%' }}>
            <PnlByPair data={data} />
          </div>
        </div>

        {/* Row 5: Kill Switch + controls */}
        <div className="flex-shrink-0">
          <KillSwitch data={data} />
        </div>
      </div>
    </div>
  )
}
