import React from 'react'

function Metric({ label, value, sub, color }) {
  return (
    <div className="flex flex-col items-center px-3 py-2 min-w-0">
      <span className="text-[10px] tracking-widest uppercase text-text-secondary mb-0.5 whitespace-nowrap">
        {label}
      </span>
      <span
        className="text-sm font-bold tabular-nums"
        style={{ color: color || '#e2e8f0' }}
      >
        {value}
      </span>
      {sub && (
        <span className="text-[9px] text-muted mt-0.5">{sub}</span>
      )}
    </div>
  )
}

function Divider() {
  return <div className="w-px h-8 bg-border self-center mx-1" />
}

export function MetricsBar({ data }) {
  if (!data) {
    return (
      <div className="card flex items-center justify-center h-14 text-muted text-xs tracking-wider">
        Connecting to FX1 backend…
      </div>
    )
  }

  const acct    = data.account    || {}
  const metrics = data.metrics    || {}
  const running = data.trader_running
  const kill    = data.kill_switch

  const balance   = acct.balance          ?? 0
  const nav       = acct.nav              ?? 0
  const unrealPnL = acct.unrealized_pnl   ?? 0
  const currency  = acct.currency         || 'SGD'

  const fmtMoney = (v) => {
    const sign = v >= 0 ? '+' : ''
    return `${sign}${Number(v).toLocaleString('en-SG', { maximumFractionDigits: 0 })}`
  }

  const fmtBig = (v) =>
    Number(v).toLocaleString('en-SG', { maximumFractionDigits: 0 })

  const winRatePct    = ((metrics.win_rate ?? 0) * 100).toFixed(1)
  const maxDDPct      = ((metrics.max_drawdown ?? 0) * 100).toFixed(2)
  const profitFactor  = metrics.profit_factor ?? 0
  const sharpe        = metrics.sharpe        ?? 0
  const netPnL        = metrics.net_pnl       ?? 0
  const totalTrades   = metrics.total_trades  ?? 0
  const avgWin        = metrics.avg_win       ?? 0
  const avgLoss       = metrics.avg_loss      ?? 0
  const expectancy    = metrics.expectancy    ?? 0

  return (
    <div
      className="card flex items-center flex-wrap gap-0 overflow-hidden"
      style={{ minHeight: 56 }}
    >
      {/* System badge */}
      <div className="flex items-center gap-2 px-4 py-2 border-r border-border">
        <span className="text-xs font-black tracking-[0.25em] uppercase text-accent">FX1</span>
        <span className="text-[10px] text-text-secondary">USD Factor + Hawkes</span>
      </div>

      {/* Trader status */}
      <div className="flex items-center gap-2 px-3 py-2 border-r border-border">
        <div
          className="w-2 h-2 rounded-full"
          style={{
            background: running ? '#00d4aa' : '#ef4444',
            animation: running ? 'pulse-green 2s infinite' : 'none',
          }}
        />
        <span
          className="text-[10px] font-bold tracking-widest uppercase"
          style={{ color: running ? '#00d4aa' : '#ef4444' }}
        >
          {running ? 'RUNNING' : 'STOPPED'}
        </span>
        {kill && (
          <span className="text-[10px] font-bold tracking-widest uppercase text-danger ml-1">
            · KILL ARMED
          </span>
        )}
      </div>

      <Metric
        label={`Balance (${currency})`}
        value={fmtBig(balance)}
        color="#e2e8f0"
      />
      <Divider />
      <Metric
        label="NAV"
        value={fmtBig(nav)}
        color="#e2e8f0"
      />
      <Divider />
      <Metric
        label="Unrealized P&L"
        value={fmtMoney(unrealPnL)}
        color={unrealPnL >= 0 ? '#00d4aa' : '#ef4444'}
        sub={currency}
      />
      <Divider />
      <Metric
        label="Realized P&L"
        value={fmtMoney(netPnL)}
        color={netPnL >= 0 ? '#00d4aa' : '#ef4444'}
        sub={currency}
      />
      <Divider />
      <Metric
        label="Trades"
        value={totalTrades}
        color="#e2e8f0"
      />
      <Divider />
      <Metric
        label="Win Rate"
        value={`${winRatePct}%`}
        color={parseFloat(winRatePct) >= 50 ? '#00d4aa' : '#f59e0b'}
      />
      <Divider />
      <Metric
        label="Avg Win"
        value={fmtMoney(avgWin)}
        color="#00d4aa"
        sub={currency}
      />
      <Divider />
      <Metric
        label="Avg Loss"
        value={fmtMoney(avgLoss)}
        color="#ef4444"
        sub={currency}
      />
      <Divider />
      <Metric
        label="Expectancy"
        value={fmtMoney(expectancy)}
        color={expectancy >= 0 ? '#00d4aa' : '#ef4444'}
        sub={currency}
      />
      <Divider />
      <Metric
        label="Profit Factor"
        value={profitFactor.toFixed(2)}
        color={profitFactor >= 1 ? '#00d4aa' : '#ef4444'}
      />
      <Divider />
      <Metric
        label="Max DD"
        value={`${maxDDPct}%`}
        color={parseFloat(maxDDPct) < -2 ? '#ef4444' : '#f59e0b'}
      />
      <Divider />
      <Metric
        label="Sharpe"
        value={sharpe.toFixed(2)}
        color={sharpe >= 1.5 ? '#00d4aa' : sharpe >= 0.8 ? '#f59e0b' : '#ef4444'}
      />

      {/* Regime badge — far right */}
      <div className="ml-auto flex items-center gap-2 px-4 py-2 border-l border-border">
        <span className="text-[10px] text-text-secondary">REGIME</span>
        <RegimeBadge regime={data.regime} />
      </div>
    </div>
  )
}

export function RegimeBadge({ regime }) {
  const r = (regime || 'unknown').toLowerCase()
  const cfg = {
    idiosyncratic: { color: '#00d4aa', label: 'IDIOSYNCRATIC' },
    transitional:  { color: '#f59e0b', label: 'TRANSITIONAL' },
    macro:         { color: '#ef4444', label: 'MACRO' },
    halted:        { color: '#ef4444', label: 'HALTED' },
    unknown:       { color: '#6b7280', label: 'UNKNOWN' },
  }
  const { color, label } = cfg[r] || cfg.unknown
  return (
    <span
      className="text-[10px] font-bold tracking-widest uppercase px-2 py-0.5 rounded"
      style={{ color, background: `${color}20`, border: `1px solid ${color}40` }}
    >
      {label}
    </span>
  )
}
