import React, { useMemo } from 'react'

const PAIRS = ['EUR_USD', 'GBP_USD', 'AUD_USD', 'NZD_USD', 'USD_CAD', 'USD_CHF', 'USD_JPY']

const Z_THRESHOLD = 1.5

function ZBar({ z }) {
  const clamped = Math.max(-3, Math.min(3, z))
  const pct     = Math.abs(clamped) / 3 * 100
  const isLong  = clamped > 0   // positive z → long signal
  const color   = clamped > 0 ? '#00d4aa' : clamped < 0 ? '#ef4444' : '#2a3050'

  return (
    <div className="flex items-center gap-1 w-full">
      {/* negative side */}
      <div className="flex-1 flex justify-end">
        <div
          style={{
            width:        `${isLong ? 0 : pct}%`,
            height:       6,
            background:   color,
            borderRadius: '2px 0 0 2px',
            transition:   'width 0.4s',
          }}
        />
      </div>
      {/* center axis */}
      <div className="w-px h-4 bg-border flex-shrink-0" />
      {/* positive side */}
      <div className="flex-1">
        <div
          style={{
            width:        `${isLong ? pct : 0}%`,
            height:       6,
            background:   color,
            borderRadius: '0 2px 2px 0',
            transition:   'width 0.4s',
          }}
        />
      </div>
    </div>
  )
}

function PairCard({ pair, signal, hasOpenTrade, hasPending }) {
  const z       = signal ? Number(signal.z_score ?? 0) : null
  const hasSignal = z !== null && Math.abs(z) >= Z_THRESHOLD
  const regime  = signal?.regime  || 'unknown'
  const kappa   = signal?.kappa
  const dir     = signal?.direction

  const dirLabel = dir === 1 ? 'LONG' : dir === -1 ? 'SHORT' : null
  const dirColor = dir === 1 ? '#00d4aa' : dir === -1 ? '#ef4444' : '#6b7280'

  const highlight = hasOpenTrade || hasPending

  return (
    <div
      className="card flex flex-col gap-1 p-2"
      style={{
        border: highlight
          ? '1px solid #2196f360'
          : hasSignal
          ? '1px solid #00d4aa30'
          : '1px solid #2a3050',
        background: highlight ? '#1e2a4020' : '#1a1f35',
        transition: 'all 0.3s',
      }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold text-text-primary">{pair}</span>
        <div className="flex items-center gap-1">
          {hasSignal && (
            <span
              className="text-[8px] font-bold px-1 py-0.5 rounded"
              style={{ background: '#00d4aa20', color: '#00d4aa', border: '1px solid #00d4aa40' }}
            >
              SIGNAL
            </span>
          )}
          {hasOpenTrade && (
            <span
              className="text-[8px] font-bold px-1 py-0.5 rounded"
              style={{ background: '#2196f320', color: '#2196f3', border: '1px solid #2196f340' }}
            >
              OPEN
            </span>
          )}
          {hasPending && !hasOpenTrade && (
            <span
              className="text-[8px] font-bold px-1 py-0.5 rounded"
              style={{ background: '#f59e0b20', color: '#f59e0b', border: '1px solid #f59e0b40' }}
            >
              PENDING
            </span>
          )}
        </div>
      </div>

      {/* Z-score bar */}
      {z !== null ? (
        <>
          <ZBar z={z} />
          <div className="flex items-center justify-between">
            <span
              className="text-[10px] font-bold tabular-nums"
              style={{ color: z > 0 ? '#00d4aa' : z < 0 ? '#ef4444' : '#6b7280' }}
            >
              z = {z.toFixed(2)}
            </span>
            {dirLabel && (
              <span
                className="text-[9px] font-bold"
                style={{ color: dirColor }}
              >
                {dirLabel}
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="text-[9px] text-muted py-1">no signal</div>
      )}

      {/* Bottom row: regime + kappa */}
      <div className="flex items-center justify-between mt-0.5">
        <span className="text-[9px] text-text-secondary capitalize">{regime}</span>
        {kappa != null && (
          <span className="text-[9px] text-muted">
            κ={Number(kappa).toFixed(3)}
          </span>
        )}
      </div>
    </div>
  )
}

export function PairGrid({ data }) {
  const signals     = data?.recent_signals   || []
  const openTrades  = data?.open_trades      || []
  const pending     = data?.pending_orders   || []

  const signalMap = useMemo(() => {
    const m = {}
    for (const s of signals) {
      const key = s.pair || s.instrument
      if (key) m[key] = s
    }
    return m
  }, [signals])

  const openPairs    = useMemo(() => new Set(openTrades.map(t => t.instrument)), [openTrades])
  const pendingPairs = useMemo(() => new Set(pending.map(p => p.pair)), [pending])

  return (
    <div className="card flex flex-col h-full overflow-hidden">
      <div className="px-3 py-2 border-b border-border flex-shrink-0">
        <span className="text-xs font-bold tracking-wider text-text-primary">PAIR SIGNALS</span>
      </div>
      <div
        className="flex-1 grid grid-cols-2 gap-2 p-2 overflow-y-auto"
        style={{ gridTemplateRows: 'auto' }}
      >
        {PAIRS.map(pair => (
          <PairCard
            key={pair}
            pair={pair}
            signal={signalMap[pair] || null}
            hasOpenTrade={openPairs.has(pair)}
            hasPending={pendingPairs.has(pair)}
          />
        ))}
      </div>
    </div>
  )
}
