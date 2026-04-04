import React from 'react'

function HeroMetric({ label, value, sub, color }) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-3 flex-1 min-w-0">
      <span className="text-[11px] tracking-[0.18em] uppercase text-text-secondary mb-1 whitespace-nowrap">
        {label}
      </span>
      <span
        className="text-xl font-bold tabular-nums leading-none"
        style={{ color: color || '#e2e8f0' }}
      >
        {value}
      </span>
      {sub && (
        <span className="text-[10px] text-muted mt-1">{sub}</span>
      )}
    </div>
  )
}

function Divider() {
  return <div className="w-px self-stretch my-3 bg-border flex-shrink-0" />
}

export function MetricsBar({ data }) {
  if (!data) {
    return (
      <div className="card flex items-center justify-center h-20 text-muted text-sm tracking-wider">
        Connecting to FX1 backend…
      </div>
    )
  }

  const acct    = data.account    || {}
  const metrics = data.metrics    || {}
  const running = data.trader_running
  const kill    = data.kill_switch

  const balance   = acct.balance        ?? 0
  const nav       = acct.nav            ?? 0
  const unrealPnL = acct.unrealized_pnl ?? 0
  const currency  = acct.currency       || 'SGD'

  const fmtMoney = (v) => {
    const sign = v >= 0 ? '+' : ''
    return `${sign}${Number(v).toLocaleString('en-SG', { maximumFractionDigits: 0 })}`
  }
  const fmtBig = (v) =>
    Number(v).toLocaleString('en-SG', { maximumFractionDigits: 0 })

  const winRatePct  = ((metrics.win_rate   ?? 0) * 100).toFixed(1)
  const maxDDPct    = ((metrics.max_drawdown ?? 0) * 100).toFixed(2)
  const sharpe      = metrics.sharpe       ?? 0
  const netPnL      = metrics.net_pnl      ?? 0
  const totalTrades = metrics.total_trades ?? 0

  return (
    <div
      className="card flex items-stretch overflow-x-auto"
      style={{ minHeight: 88 }}
    >
      {/* System badge */}
      <div
        className="flex flex-col justify-center gap-1.5 px-5 py-3 flex-shrink-0"
        style={{ borderRight: '1px solid #2a3050', minWidth: 140 }}
      >
        <div className="flex items-center gap-2">
          <span className="text-base font-black tracking-[0.25em] uppercase text-accent">FX1</span>
          {kill && (
            <span className="text-[10px] font-bold text-danger tracking-wider">KILL</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{
              background: running ? '#00d4aa' : '#ef4444',
              animation:  running ? 'pulse-green 2s infinite' : 'none',
            }}
          />
          <span
            className="text-[11px] font-bold tracking-widest uppercase"
            style={{ color: running ? '#00d4aa' : '#ef4444' }}
          >
            {running ? 'RUNNING' : 'STOPPED'}
          </span>
        </div>
        <span className="text-[9px] text-muted tracking-wide">M30 · OANDA</span>
      </div>

      {/* Hero metrics — flex-1 so they stretch to fill available width */}
      <div className="flex flex-1 items-stretch">
        <HeroMetric label={`Balance (${currency})`} value={fmtBig(balance)} />
        <Divider />
        <HeroMetric label="NAV" value={fmtBig(nav)} />
        <Divider />
        <HeroMetric
          label="Unrealized P&L"
          value={fmtMoney(unrealPnL)}
          sub={currency}
          color={unrealPnL >= 0 ? '#00d4aa' : '#ef4444'}
        />
        <Divider />
        <HeroMetric
          label="Realized P&L"
          value={fmtMoney(netPnL)}
          sub={currency}
          color={netPnL >= 0 ? '#00d4aa' : '#ef4444'}
        />
        <Divider />
        <HeroMetric
          label="Win Rate"
          value={`${winRatePct}%`}
          color={parseFloat(winRatePct) >= 50 ? '#00d4aa' : '#f59e0b'}
        />
        <Divider />
        <HeroMetric label="Trades" value={totalTrades} />
        <Divider />
        <HeroMetric
          label="Max DD"
          value={`${maxDDPct}%`}
          color={parseFloat(maxDDPct) < -5 ? '#ef4444' : parseFloat(maxDDPct) < -2 ? '#f59e0b' : '#00d4aa'}
        />
        <Divider />
        <HeroMetric
          label="Sharpe"
          value={sharpe.toFixed(2)}
          color={sharpe >= 1.5 ? '#00d4aa' : sharpe >= 0.8 ? '#f59e0b' : '#ef4444'}
        />
      </div>

      {/* Regime — far right */}
      <div
        className="ml-auto flex items-center gap-3 px-5 py-3 flex-shrink-0"
        style={{ borderLeft: '1px solid #2a3050' }}
      >
        <span className="text-[11px] text-text-secondary tracking-widest uppercase">Regime</span>
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
      className="text-sm font-bold tracking-widest uppercase px-3 py-1.5 rounded"
      style={{ color, background: `${color}20`, border: `1px solid ${color}50` }}
    >
      {label}
    </span>
  )
}
