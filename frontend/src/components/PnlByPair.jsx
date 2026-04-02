import React, { useMemo } from 'react'
import Plot from 'react-plotly.js'

const PLOT_BG  = '#0a0e1a'
const PAPER_BG = '#1a1f35'
const GRID_CLR = '#2a3050'
const FONT_CLR = '#94a3b8'

export function PnlByPair({ data }) {
  const tradeLog = data?.trade_log || []

  const { pairs, pnls } = useMemo(() => {
    const map = {}
    for (const entry of tradeLog) {
      if (entry.event !== 'close') continue
      const pair = entry.pair || 'UNKNOWN'
      const pnl  = entry.pnl != null ? Number(entry.pnl) : 0
      map[pair]  = (map[pair] || 0) + pnl
    }

    const sorted = Object.entries(map).sort((a, b) => a[1] - b[1])
    return {
      pairs: sorted.map(([p]) => p),
      pnls:  sorted.map(([, v]) => v),
    }
  }, [tradeLog])

  if (!pairs.length) {
    return (
      <div className="card flex items-center justify-center h-full text-muted text-xs">
        No fill events to compute P&L
      </div>
    )
  }

  const colors = pnls.map(v => (v >= 0 ? '#00d4aa' : '#ef4444'))

  const traces = [{
    type:         'bar',
    orientation:  'h',
    x:            pnls,
    y:            pairs,
    marker:       { color: colors },
    hovertemplate: '%{y}: %{x:,.2f} SGD<extra></extra>',
    text:         pnls.map(v => `${v >= 0 ? '+' : ''}${v.toFixed(0)}`),
    textposition: 'outside',
    textfont:     { size: 9, color: FONT_CLR },
  }]

  const layout = {
    paper_bgcolor: PAPER_BG,
    plot_bgcolor:  PLOT_BG,
    font:   { color: FONT_CLR, family: 'JetBrains Mono, monospace', size: 10 },
    margin: { t: 36, r: 60, b: 40, l: 72 },
    xaxis: {
      gridcolor:    GRID_CLR,
      zerolinecolor: '#3a4060',
      tickfont:     { size: 9 },
      tickformat:   ',.0f',
    },
    yaxis: {
      gridcolor:  'transparent',
      tickfont:   { size: 9 },
      automargin: true,
    },
    title: {
      text:    'Realized P&L by Pair (SGD)',
      font:    { size: 11, color: '#e2e8f0' },
      x:       0.02,
      xanchor: 'left',
    },
    bargap: 0.35,
  }

  return (
    <div className="card h-full">
      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: '100%' }}
        useResizeHandler
      />
    </div>
  )
}
