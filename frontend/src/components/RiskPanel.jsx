import React, { useMemo } from 'react'
import Plot from 'react-plotly.js'

const PLOT_BG  = '#0a0e1a'
const PAPER_BG = '#1a1f35'
const GRID_CLR = '#2a3050'
const FONT_CLR = '#94a3b8'

function RiskMetric({ label, value, color, sub, hint }) {
  return (
    <div
      className="flex flex-col gap-0.5 p-2 rounded"
      style={{ background: '#0d1122', border: '1px solid #2a3050' }}
    >
      <span className="text-[9px] tracking-widest uppercase text-text-secondary">{label}</span>
      <span className="text-sm font-bold tabular-nums" style={{ color: color || '#e2e8f0' }}>
        {value}
      </span>
      {sub && <span className="text-[9px] text-muted">{sub}</span>}
      {hint && <span className="text-[8px]" style={{ color: '#4a5580' }}>{hint}</span>}
    </div>
  )
}

function ratioColor(v, goodAbove = 1.0) {
  if (v === null || v === undefined || isNaN(v)) return '#6b7280'
  return v >= goodAbove ? '#00d4aa' : v >= goodAbove * 0.5 ? '#f59e0b' : '#ef4444'
}

export function RiskPanel({ data }) {
  const metrics = data?.metrics || {}
  const pnls    = metrics.pnl_list || []

  const sharpe   = metrics.sharpe       ?? null
  const sortino  = metrics.sortino      ?? null
  const calmar   = metrics.calmar       ?? null
  const skewness = metrics.skewness     ?? null
  const kurt     = metrics.kurtosis     ?? null
  const var95    = metrics.var_95       ?? null
  const maxDD    = metrics.max_drawdown ?? null

  // Skewness interpretation
  const skewHint = skewness === null ? '' :
    skewness > 0.3  ? 'right tail: few large wins' :
    skewness < -0.3 ? 'left tail: few large losses' :
                      'roughly symmetric'

  // Distribution chart
  const { wins, losses } = useMemo(() => {
    const w = pnls.filter(p => p >= 0)
    const l = pnls.filter(p => p < 0)
    return { wins: w, losses: l }
  }, [pnls])

  const hasData = pnls.length >= 3

  const traces = hasData ? [
    {
      type:      'histogram',
      x:         losses,
      name:      'Loss',
      marker:    { color: '#ef444488', line: { color: '#ef4444', width: 1 } },
      xbins:     { size: 500 },
      hovertemplate: '%{x:,.0f} SGD: %{y} trades<extra></extra>',
    },
    {
      type:      'histogram',
      x:         wins,
      name:      'Win',
      marker:    { color: '#00d4aa88', line: { color: '#00d4aa', width: 1 } },
      xbins:     { size: 500 },
      hovertemplate: '%{x:,.0f} SGD: %{y} trades<extra></extra>',
    },
    // Mean line
    {
      type: 'scatter',
      mode: 'lines',
      x:    [metrics.expectancy ?? 0, metrics.expectancy ?? 0],
      y:    [0, 10],
      line: { color: '#f59e0b', width: 1, dash: 'dot' },
      name: 'Expectancy',
      hovertemplate: 'Expectancy: %{x:,.0f} SGD<extra></extra>',
    },
  ] : []

  const layout = {
    paper_bgcolor: PAPER_BG,
    plot_bgcolor:  PLOT_BG,
    barmode:       'overlay',
    font:    { color: FONT_CLR, family: 'JetBrains Mono, monospace', size: 9 },
    margin:  { t: 28, r: 12, b: 36, l: 40 },
    xaxis: {
      title:      { text: 'P&L (SGD)', font: { size: 9 } },
      gridcolor:  GRID_CLR,
      zerolinecolor: '#3a4060',
      tickformat: ',.0f',
      tickfont:   { size: 8 },
    },
    yaxis: {
      title:    { text: 'Trades', font: { size: 9 } },
      gridcolor: GRID_CLR,
      tickfont: { size: 8 },
    },
    legend: {
      font:        { size: 8 },
      orientation: 'h',
      x: 0, y: 1.12,
      bgcolor: 'transparent',
    },
    title: {
      text:    'P&L Distribution',
      font:    { size: 10, color: '#e2e8f0' },
      x:       0.5,
      xanchor: 'center',
      y:       0.98,
    },
    annotations: skewness !== null ? [{
      x: 0.98, y: 0.95,
      xref: 'paper', yref: 'paper',
      text: `skew ${skewness >= 0 ? '+' : ''}${skewness?.toFixed(2)} · ${skewHint}`,
      showarrow: false,
      font: { size: 8, color: skewness > 0.3 ? '#00d4aa' : skewness < -0.3 ? '#ef4444' : '#f59e0b' },
      align: 'right',
    }] : [],
  }

  const fmtSGD = v => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toLocaleString('en-SG', { maximumFractionDigits: 0 })}`
  const fmt2   = v => v == null ? '—' : Number(v).toFixed(2)

  return (
    <div
      className="card flex flex-col h-full overflow-hidden"
      style={{ minHeight: 0 }}
    >
      <div className="px-3 py-2 border-b border-border flex-shrink-0">
        <span className="text-xs font-bold tracking-wider text-text-primary">RISK METRICS</span>
      </div>

      <div className="flex flex-1 gap-2 p-2 overflow-hidden" style={{ minHeight: 0 }}>
        {/* Left: metrics grid */}
        <div className="flex flex-col gap-1.5 flex-shrink-0" style={{ width: 220 }}>
          <div className="grid grid-cols-2 gap-1.5">
            <RiskMetric
              label="Sharpe"
              value={fmt2(sharpe)}
              color={ratioColor(sharpe, 1.0)}
              hint="ret / total vol"
            />
            <RiskMetric
              label="Sortino"
              value={fmt2(sortino)}
              color={ratioColor(sortino, 1.0)}
              hint="ret / downside vol"
            />
            <RiskMetric
              label="Calmar"
              value={fmt2(calmar)}
              color={ratioColor(calmar, 1.0)}
              hint="ann.ret / max DD"
            />
            <RiskMetric
              label="Max DD"
              value={`${((maxDD ?? 0) * 100).toFixed(2)}%`}
              color={maxDD == null ? '#6b7280' : maxDD > -0.02 ? '#00d4aa' : maxDD > -0.05 ? '#f59e0b' : '#ef4444'}
              hint="peak-to-trough"
            />
            <RiskMetric
              label="Skewness"
              value={skewness != null ? `${skewness >= 0 ? '+' : ''}${fmt2(skewness)}` : '—'}
              color={skewness == null ? '#6b7280' : skewness > 0 ? '#00d4aa' : '#ef4444'}
              hint={skewHint}
            />
            <RiskMetric
              label="Kurtosis"
              value={kurt != null ? fmt2(kurt) : '—'}
              color={kurt == null ? '#6b7280' : Math.abs(kurt) < 1 ? '#00d4aa' : '#f59e0b'}
              hint="excess (fat tails)"
            />
          </div>
          <RiskMetric
            label="VaR 95%"
            value={fmtSGD(var95)}
            color={var95 == null ? '#6b7280' : var95 >= 0 ? '#6b7280' : '#ef4444'}
            sub="SGD"
            hint="worst 5th-pct trade"
          />
        </div>

        {/* Right: distribution chart */}
        <div className="flex-1" style={{ minWidth: 0, minHeight: 0 }}>
          {hasData ? (
            <Plot
              data={traces}
              layout={layout}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: '100%', height: '100%' }}
              useResizeHandler
            />
          ) : (
            <div className="flex items-center justify-center h-full text-muted text-xs">
              Need ≥ 3 closed trades for distribution
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
