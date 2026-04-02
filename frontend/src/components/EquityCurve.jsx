import React, { useMemo } from 'react'
import Plot from 'react-plotly.js'

const PLOT_BG   = '#0a0e1a'
const PAPER_BG  = '#1a1f35'
const GRID_CLR  = '#2a3050'
const FONT_CLR  = '#94a3b8'

export function EquityCurve({ data }) {
  const tradeLog  = data?.trade_log  || []
  const account   = data?.account    || {}
  const metrics   = data?.metrics    || {}

  const { times, equity, drawdown } = useMemo(() => {
    const fills      = tradeLog.filter(e => e.event === 'fill')
    const netPnL     = metrics.net_pnl ?? 0
    const balance    = account.balance  ?? 0
    const initBal    = balance - netPnL

    if (!fills.length) return { times: [], equity: [], drawdown: [] }

    let running = initBal
    let peak    = initBal
    const times    = []
    const equity   = []
    const drawdown = []

    for (const f of fills) {
      const pnl = f.pnl != null ? Number(f.pnl) : 0
      running += pnl
      peak     = Math.max(peak, running)
      times.push(f.timestamp)
      equity.push(Number(running.toFixed(2)))
      drawdown.push(Number(((running - peak) / (Math.abs(peak) + 1e-9) * 100).toFixed(4)))
    }

    return { times, equity, drawdown }
  }, [tradeLog, account.balance, metrics.net_pnl])

  const traces = [
    {
      x:    times,
      y:    equity,
      type: 'scatter',
      mode: 'lines',
      name: 'Equity',
      line: { color: '#2196f3', width: 1.5 },
      hovertemplate: '%{x}<br>Equity: %{y:,.0f}<extra></extra>',
    },
    {
      x:    times,
      y:    drawdown,
      type: 'scatter',
      mode: 'lines',
      name: 'Drawdown %',
      yaxis: 'y2',
      line:  { color: '#ef444460', width: 1 },
      fill:  'tozeroy',
      fillcolor: '#ef444415',
      hovertemplate: '%{x}<br>DD: %{y:.2f}%<extra></extra>',
    },
  ]

  const layout = {
    paper_bgcolor: PAPER_BG,
    plot_bgcolor:  PLOT_BG,
    font:  { color: FONT_CLR, family: 'JetBrains Mono, monospace', size: 10 },
    margin: { t: 32, r: 48, b: 40, l: 64 },
    legend: { x: 0.01, y: 0.99, bgcolor: 'transparent', font: { size: 9 } },
    xaxis: {
      gridcolor:   GRID_CLR,
      zerolinecolor: GRID_CLR,
      tickfont:    { size: 9 },
      type:        'date',
    },
    yaxis: {
      gridcolor:   GRID_CLR,
      zerolinecolor: GRID_CLR,
      tickfont:    { size: 9 },
      tickformat:  ',.0f',
      title:       { text: 'Equity (SGD)', font: { size: 9 } },
    },
    yaxis2: {
      overlaying: 'y',
      side:       'right',
      gridcolor:  'transparent',
      tickfont:   { size: 9 },
      tickformat: '.1f',
      ticksuffix: '%',
      title:      { text: 'Drawdown %', font: { size: 9 } },
    },
    title: {
      text:  'Equity Curve',
      font:  { size: 11, color: '#e2e8f0' },
      x:     0.02,
      xanchor: 'left',
    },
  }

  if (!times.length) {
    return (
      <div className="card flex items-center justify-center h-full text-muted text-xs">
        No fill events in trade log yet
      </div>
    )
  }

  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%', height: '100%' }}
      useResizeHandler
    />
  )
}
