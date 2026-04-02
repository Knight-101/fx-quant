import React, { useMemo } from 'react'
import Plot from 'react-plotly.js'
import { formatDistanceToNow, parseISO } from 'date-fns'
import { RegimeBadge } from './MetricsBar.jsx'

const PLOT_BG  = '#1a1f35'
const PAPER_BG = '#1a1f35'

export function RegimePanel({ data }) {
  const regime      = data?.regime       || 'unknown'
  const diagnostics = data?.diagnostics  || {}
  const pending     = data?.pending_orders || []
  const ts          = data?.ts

  const hmm = useMemo(() => {
    const counts = diagnostics.hmm_state_counts || {}
    const labels = Object.keys(counts)
    const values = Object.values(counts)
    const total  = values.reduce((a, b) => a + b, 0) || 1
    const colors = {
      idiosyncratic: '#00d4aa',
      transitional:  '#f59e0b',
      macro:         '#ef4444',
    }
    return {
      labels,
      values,
      pcts:   values.map(v => ((v / total) * 100).toFixed(1)),
      colors: labels.map(l => colors[l] || '#6b7280'),
    }
  }, [diagnostics.hmm_state_counts])

  const pieData = [{
    type:              'pie',
    labels:            hmm.labels,
    values:            hmm.values,
    marker:            { colors: hmm.colors },
    textinfo:          'percent',
    textfont:          { size: 9, color: '#e2e8f0' },
    hovertemplate:     '%{label}: %{value} bars (%{percent})<extra></extra>',
    hole:              0.55,
  }]

  const pieLayout = {
    paper_bgcolor: PAPER_BG,
    plot_bgcolor:  PLOT_BG,
    font:   { color: '#94a3b8', family: 'JetBrains Mono, monospace', size: 9 },
    margin: { t: 16, r: 16, b: 16, l: 16 },
    showlegend: true,
    legend: {
      font:    { size: 9 },
      bgcolor: 'transparent',
      x:       1.0,
      xanchor: 'right',
      y:       0.5,
    },
    annotations: [{
      text:     'HMM',
      x:        0.5, y: 0.5,
      font:     { size: 10, color: '#94a3b8' },
      showarrow: false,
    }],
  }

  const formatExpiry = (ts) => {
    try {
      return formatDistanceToNow(parseISO(ts), { addSuffix: true })
    } catch {
      return ts
    }
  }

  return (
    <div className="card flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="text-xs font-bold tracking-wider text-text-primary">REGIME</span>
        <RegimeBadge regime={regime} />
      </div>

      {/* HMM pie */}
      <div className="flex-1 min-h-0" style={{ minHeight: 140, maxHeight: 200 }}>
        <Plot
          data={pieData}
          layout={pieLayout}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: '100%', height: '100%' }}
          useResizeHandler
        />
      </div>

      {/* Pending orders */}
      <div className="px-3 py-2 border-t border-border flex-shrink-0">
        <div className="text-[10px] font-bold tracking-widest text-text-secondary mb-1 uppercase">
          Pending Orders ({pending.length})
        </div>
        {pending.length === 0 ? (
          <div className="text-[10px] text-muted">No pending orders</div>
        ) : (
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {pending.map((o, i) => (
              <div
                key={i}
                className="flex items-center justify-between text-[10px] py-0.5"
                style={{ borderBottom: '1px solid #2a305040' }}
              >
                <span className="font-bold text-accent">{o.pair}</span>
                <span className="text-text-secondary font-mono">#{o.order_id}</span>
                <span className="text-warning">{formatExpiry(o.expires_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Last update */}
      {ts && (
        <div className="px-3 py-1 border-t border-border flex-shrink-0">
          <span className="text-[9px] text-muted">
            Updated {formatDistanceToNow(new Date(ts), { addSuffix: true })}
          </span>
        </div>
      )}
    </div>
  )
}
