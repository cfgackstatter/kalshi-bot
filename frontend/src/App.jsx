import { useState, useEffect } from 'react'
import axios from 'axios'
import './App.css'

const API = 'http://localhost:8000/api'

// ── Tiny reusable components ──────────────────────────────────────────────────

const FilterBtn = ({ active, onClick, children }) => (
  <button className={`filter-btn ${active ? 'active' : ''}`} onClick={onClick}>
    {children}
  </button>
)

const Modal = ({ title, onClose, children }) => (
  <div className="modal-overlay" onClick={onClose}>
    <div className="modal" onClick={e => e.stopPropagation()}>
      <div className="modal-header">
        <h3>{title}</h3>
        <button onClick={onClose}>✕</button>
      </div>
      {children}
    </div>
  </div>
)

// ── Strategy parameter definitions ───────────────────────────────────────────

const GENERAL_PARAMS = [
  { key: 'scan_frequency',          label: 'Scan Frequency (min)',   type: 'number', step: 1,   scale: 1    },
  { key: 'max_pending_age_minutes', label: 'Max Pending Age (min)',  type: 'number', step: 1,   scale: 1    },
  { key: 'order_at_bid',            label: 'Order at Bid (maker)',   type: 'boolean'                        },
  { key: 'estimated_edge',          label: 'Estimated Edge %',       type: 'number', step: 0.1, scale: 0.01 },
  { key: 'kelly_fraction',          label: 'Kelly Fraction %',       type: 'number', step: 1,   scale: 0.01 },
  { key: 'max_position_pct',        label: 'Max Position %',         type: 'number', step: 1,   scale: 0.01 },
]

const COMBINED_GENERAL_PARAMS = [
  { key: 'scan_frequency',          label: 'Scan Frequency (min)',   type: 'number', step: 1 },
  { key: 'max_pending_age_minutes', label: 'Max Pending Age (min)',  type: 'number', step: 1 },
  { key: 'prefer_mode',             label: 'Allocation Mode',        type: 'select',
    options: [
      { value: 'score', label: 'Best score (¢/hr)' },
      { value: 'momentum_first', label: 'Momentum first' },
      { value: 'bonding_first', label: 'Bonding first' },
    ]},
  { key: 'score_hysteresis',        label: 'Score Hysteresis',       type: 'number', step: 0.05 },
  { key: 'max_open_positions',      label: 'Max Open Positions',     type: 'number', step: 1 },
  { key: 'max_positions_per_series', label: 'Max Positions / Series', type: 'number', step: 1 },
  { key: 'kelly_fraction',          label: 'Kelly Fraction %',       type: 'number', step: 1, scale: 0.01 },
  { key: 'max_position_pct',        label: 'Max Position %',         type: 'number', step: 1, scale: 0.01 },
  { key: 'order_at_bid',            label: 'Order at Bid (maker)',   type: 'boolean' },
  { key: 'rebuy_cooldown_seconds',  label: 'Rebuy Cooldown (sec)',   type: 'number', step: 30 },
  { key: 'ticker_exclude_substrings', label: 'Exclude Tickers (csv)', type: 'text' },
]

const STRATEGY_PARAMS = {
  bonding: [
    { key: 'min_probability',           label: 'Min Ask (¢)',               type: 'number', step: 1    },
    { key: 'max_time_to_expiry',        label: 'Max Time to Expiry (hrs)',  type: 'number', step: 0.01 },
    { key: 'max_spread',                label: 'Max Spread (¢)',            type: 'number', step: 1    },
    { key: 'min_volume',                label: 'Min Volume',                type: 'number', step: 1    },
    { key: 'stability_seconds',         label: 'Ask Stability (sec)',       type: 'number', step: 15   },
    { key: 'min_net_if_win_cents',      label: 'Min Net if Win (¢)',        type: 'number', step: 1    },
    { key: 'max_open_positions',        label: 'Max Open Positions',        type: 'number', step: 1    },
    { key: 'max_positions_per_series',  label: 'Max Positions / Series',    type: 'number', step: 1    },
    { key: 'rebuy_cooldown_seconds',    label: 'Rebuy Cooldown (sec)',      type: 'number', step: 30   },
    { key: 'hold_to_settlement',        label: 'Hold to Settlement',        type: 'boolean'            },
    { key: 'thesis_break_mid',          label: 'Thesis Break Mid (¢)',      type: 'number', step: 1    },
    { key: 'maker_min_minutes_to_expiry', label: 'Maker if ≥ Min Left',   type: 'number', step: 1    },
    { key: 'ticker_exclude_substrings', label: 'Exclude Tickers (csv)',     type: 'text'               },
  ],
  momentum: [
    { key: 'momentum_window_minutes', label: 'Momentum Window (min)',  type: 'number', step: 1   },
    { key: 'recent_window_seconds',   label: 'Recent Slope Window (s)', type: 'number', step: 15 },
    { key: 'min_slope_cents_per_min',  label: 'Min Slope ¢/min',        type: 'number', step: 0.5 },
    { key: 'momentum_tstat_threshold', label: 'Momentum t-stat',       type: 'number', step: 0.1 },
    { key: 'min_upside_cents',        label: 'Min Upside (¢)',         type: 'number', step: 1   },
    { key: 'min_upside_ratio',        label: 'Min Upside Ratio (%)',   type: 'number', step: 1, scale: 0.01 },
    { key: 'max_entry_mid',           label: 'Max Entry Mid (¢)',      type: 'number', step: 1   },
    { key: 'min_entry_price_cents',   label: 'Min Entry Price (¢)',    type: 'number', step: 1   },
    { key: 'max_entry_price_cents',   label: 'Max Entry Price (¢)',    type: 'number', step: 1   },
    { key: 'take_profit_cents',       label: 'Take Profit (¢)',        type: 'number', step: 1   },
    { key: 'stop_loss_cents',         label: 'Stop Loss (¢)',          type: 'number', step: 1   },
    { key: 'max_hold_minutes',        label: 'Max Hold (min)',         type: 'number', step: 5   },
    { key: 'exit_on_flip',            label: 'Exit on Momentum Flip',  type: 'boolean'           },
    { key: 'flip_tstat_threshold',    label: 'Flip t-stat',            type: 'number', step: 0.1 },
    { key: 'min_hold_seconds_before_flip', label: 'Min Hold Before Flip (s)', type: 'number', step: 30 },
    { key: 'max_open_positions',      label: 'Max Open Positions',     type: 'number', step: 1   },
    { key: 'max_positions_per_series', label: 'Max Positions / Series', type: 'number', step: 1  },
    { key: 'rebuy_cooldown_seconds',  label: 'Rebuy Cooldown (sec)',   type: 'number', step: 30  },
    { key: 'min_time_to_expiry',      label: 'Min Time to Expiry (hr)',type: 'number', step: 0.25},
    { key: 'max_time_to_expiry',      label: 'Max Time to Expiry (hr)',type: 'number', step: 0.25},
    { key: 'max_spread',              label: 'Max Spread (¢)',         type: 'number', step: 1   },
    { key: 'min_volume',              label: 'Min Volume',             type: 'number', step: 10  },
    { key: 'ticker_exclude_substrings', label: 'Exclude Tickers (csv)', type: 'text'             },
  ],
  // Nested under config.bonding / config.momentum (shared risk is COMBINED_GENERAL)
  combinedBonding: [
    { key: 'min_probability',           label: 'Min Ask (¢)',               type: 'number', step: 1    },
    { key: 'max_time_to_expiry',        label: 'Max Time to Expiry (hrs)',  type: 'number', step: 0.01 },
    { key: 'max_spread',                label: 'Max Spread (¢)',            type: 'number', step: 1    },
    { key: 'min_volume',                label: 'Min Volume',                type: 'number', step: 1    },
    { key: 'stability_seconds',         label: 'Ask Stability (sec)',       type: 'number', step: 15   },
    { key: 'min_net_if_win_cents',      label: 'Min Net if Win (¢)',        type: 'number', step: 1    },
    { key: 'estimated_edge',            label: 'Estimated Edge %',          type: 'number', step: 0.1, scale: 0.01 },
    { key: 'hold_to_settlement',        label: 'Hold to Settlement',        type: 'boolean'            },
    { key: 'thesis_break_mid',          label: 'Thesis Break Mid (¢)',      type: 'number', step: 1    },
    { key: 'maker_min_minutes_to_expiry', label: 'Maker if ≥ Min Left',   type: 'number', step: 1    },
  ],
  combinedMomentum: [
    { key: 'momentum_window_minutes', label: 'Momentum Window (min)',  type: 'number', step: 1   },
    { key: 'recent_window_seconds',   label: 'Recent Slope Window (s)', type: 'number', step: 15 },
    { key: 'min_slope_cents_per_min',  label: 'Min Slope ¢/min',        type: 'number', step: 0.5 },
    { key: 'momentum_tstat_threshold', label: 'Momentum t-stat',       type: 'number', step: 0.1 },
    { key: 'estimated_edge',          label: 'Base Edge %',            type: 'number', step: 0.1, scale: 0.01 },
    { key: 'min_upside_cents',        label: 'Min Upside (¢)',         type: 'number', step: 1   },
    { key: 'max_entry_mid',           label: 'Max Entry Mid (¢)',      type: 'number', step: 1   },
    { key: 'min_entry_price_cents',   label: 'Min Entry Price (¢)',    type: 'number', step: 1   },
    { key: 'max_entry_price_cents',   label: 'Max Entry Price (¢)',    type: 'number', step: 1   },
    { key: 'take_profit_cents',       label: 'Take Profit (¢)',        type: 'number', step: 1   },
    { key: 'stop_loss_cents',         label: 'Stop Loss (¢)',          type: 'number', step: 1   },
    { key: 'max_hold_minutes',        label: 'Max Hold (min)',         type: 'number', step: 5   },
    { key: 'exit_on_flip',            label: 'Exit on Momentum Flip',  type: 'boolean'           },
    { key: 'min_hold_seconds_before_flip', label: 'Min Hold Before Flip (s)', type: 'number', step: 30 },
    { key: 'min_time_to_expiry',      label: 'Min Time to Expiry (hr)',type: 'number', step: 0.25},
    { key: 'max_time_to_expiry',      label: 'Max Time to Expiry (hr)',type: 'number', step: 0.25},
    { key: 'max_spread',              label: 'Max Spread (¢)',         type: 'number', step: 1   },
    { key: 'min_volume',              label: 'Min Volume',             type: 'number', step: 10  },
  ],
}

// ── ParamField: single editable config row ────────────────────────────────────

const ParamField = ({ def, value, onChange }) => {
  // Display value: divide stored value by scale (0.25 → 25 for display)
  const displayVal = (def.type === 'number' && def.scale)
    ? (value ?? 0) / def.scale
    : String(value ?? '')

  const handleChange = (e) => {
    const raw = def.type === 'number' ? parseFloat(e.target.value) : e.target.value
    // Store value: multiply by scale (25 → 0.25 for storage)
    const stored = (def.type === 'number' && def.scale) ? raw * def.scale : raw
    onChange(def.key, stored)
  }

  if (def.type === 'boolean') return (
    <div className="param-row">
      <label>{def.label}</label>
      <input type="checkbox" checked={!!value}
        onChange={e => onChange(def.key, e.target.checked)} />
    </div>
  )

  if (def.type === 'select') return (
    <div className="param-row">
      <label>{def.label}</label>
      <select value={value ?? def.options?.[0]?.value} onChange={e => onChange(def.key, e.target.value)}>
        {(def.options || []).map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )

  return (
    <div className="param-row">
      <label>{def.label}</label>
      <input
        type={def.type}
        {...(def.type === 'number' ? { step: def.step } : {})}
        value={displayVal}
        onChange={handleChange}
      />
    </div>
  )
}

// ── StrategyPanel: selector + collapsible params ──────────────────────────────

const StrategyPanel = ({ running, configs, activeStrategy, onStrategyChange, onConfigChange, onStart, onStop }) => {
  const [open, setOpen] = useState(false)
  const config = configs[activeStrategy]
  if (!config) return null

  const isCombined = activeStrategy === 'combined'

  return (
    <div className="strategy-panel">

      {/* Top bar: selector + status + start/stop */}
      <div className="strategy-bar">
        <span className="strategy-label">Strategy</span>

        <select
          value={activeStrategy}
          disabled={running}
          onChange={e => onStrategyChange(e.target.value)}
        >
          <option value="bonding">Bonding</option>
          <option value="momentum">Momentum</option>
          <option value="combined">Combined</option>
        </select>

        <span className={`status-dot ${running ? 'running' : 'stopped'}`}>
          {running ? '● Running' : '○ Stopped'}
        </span>

        {running
          ? <button className="btn-danger"  onClick={onStop}>Stop</button>
          : <button className="btn-success" onClick={onStart}>Start</button>
        }

        <button className="btn-secondary" onClick={() => setOpen(o => !o)}>
          {open ? '▲ Hide Params' : '▼ Show Params'}
        </button>
      </div>

      {/* Collapsible params */}
      {open && (
        <div className="params-grid">

          <div className="params-section">
            <h4>{isCombined ? 'Allocation & Risk' : 'General'}</h4>
            {(isCombined ? COMBINED_GENERAL_PARAMS : GENERAL_PARAMS).map(def => (
              <ParamField key={def.key} def={def} value={config[def.key]}
                onChange={(k, v) => onConfigChange(activeStrategy, k, v)} />
            ))}
          </div>

          {isCombined ? (
            <>
              <div className="params-section">
                <h4>Bonding Leg</h4>
                {STRATEGY_PARAMS.combinedBonding.map(def => (
                  <ParamField key={def.key} def={def} value={config.bonding?.[def.key]}
                    onChange={(k, v) => onConfigChange(activeStrategy, k, v, 'bonding')} />
                ))}
              </div>
              <div className="params-section">
                <h4>Momentum Leg</h4>
                {STRATEGY_PARAMS.combinedMomentum.map(def => (
                  <ParamField key={def.key} def={def} value={config.momentum?.[def.key]}
                    onChange={(k, v) => onConfigChange(activeStrategy, k, v, 'momentum')} />
                ))}
              </div>
            </>
          ) : (
            <div className="params-section">
              <h4>{activeStrategy.charAt(0).toUpperCase() + activeStrategy.slice(1)}</h4>
              {STRATEGY_PARAMS[activeStrategy].map(def => (
                <ParamField key={def.key} def={def} value={config[def.key]}
                  onChange={(k, v) => onConfigChange(activeStrategy, k, v)} />
              ))}
            </div>
          )}

        </div>
      )}
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  // Strategy state
  const [activeStrategy, setActiveStrategy] = useState('bonding')
  const [configs, setConfigs]               = useState({ bonding: null, momentum: null, combined: null })
  const [running, setRunning]               = useState(false)

  // Data state
  const [balance, setBalance]     = useState(null)
  const [markets, setMarkets]     = useState([])
  const [orders, setOrders]       = useState([])
  const [positions, setPositions] = useState([])

  // UI state
  const [activeTab, setActiveTab]   = useState('markets')
  // Empty set = show all; otherwise AND together active filters
  const [marketFilters, setMarketFilters] = useState(new Set())
  const [tradeModal, setTradeModal] = useState(null)
  const [closeModal, setCloseModal] = useState(null)

  const toggleMarketFilter = (val) => {
    if (val === 'all') {
      setMarketFilters(new Set())
      return
    }
    setMarketFilters(prev => {
      const next = new Set(prev)
      if (next.has(val)) next.delete(val)
      else next.add(val)
      return next
    })
  }

  // ── Data fetching ───────────────────────────────────────────────────────────

  const fetchAll = async () => {
    try {
      const [bal, mkt, ord, pos] = await Promise.all([
        axios.get(`${API}/balance`),
        axios.get(`${API}/markets`),
        axios.get(`${API}/orders`),
        axios.get(`${API}/positions`),
      ])
      setBalance(bal.data)
      setMarkets(mkt.data.markets || [])
      setOrders(ord.data.orders || [])
      setPositions(pos.data.positions || [])
    } catch (e) {
      console.error('Fetch error:', e)
    }
  }

  useEffect(() => {
    Promise.all([
      axios.get(`${API}/strategy/config`),
      axios.get(`${API}/strategy/defaults/bonding`),
      axios.get(`${API}/strategy/defaults/momentum`),
      axios.get(`${API}/strategy/defaults/combined`),
    ]).then(([cfg, bond, mom, comb]) => {
      const active = cfg.data.strategy_type || 'bonding'
      setActiveStrategy(active)
      setRunning(cfg.data.enabled || false)
      setConfigs({
        bonding:  active === 'bonding'  ? cfg.data : bond.data,
        momentum: active === 'momentum' ? cfg.data : mom.data,
        combined: active === 'combined' ? cfg.data : comb.data,
      })
    }).catch(e => console.error('Init error:', e))

    fetchAll()
    const interval = setInterval(fetchAll, 30000)
    return () => clearInterval(interval)
  }, [])

  // ── Strategy controls ───────────────────────────────────────────────────────

  const handleStrategyChange = (type) => {
    setActiveStrategy(type)
    // Don't send to backend yet — user must click Start
  }

  const handleConfigChange = (strategyType, key, value, nest = null) => {
    const prev = configs[strategyType] || {}
    const updatedConfig = nest
      ? { ...prev, [nest]: { ...(prev[nest] || {}), [key]: value } }
      : { ...prev, [key]: value }
    setConfigs(prevConfigs => ({ ...prevConfigs, [strategyType]: updatedConfig }))
    if (running) {
      // Never send enabled or strategy_type — those are controlled by start/stop only
      const { enabled, strategy_type, ...safeConfig } = updatedConfig
      axios.put(`${API}/strategy/config`, safeConfig)
    }
  }

  const handleStart = async () => {
    try {
        // Only send the strategy params — /start endpoint sets enabled=True itself
        const { enabled, ...paramsOnly } = configs[activeStrategy]
        const configToSend = { ...paramsOnly, strategy_type: activeStrategy }
        await axios.put(`${API}/strategy/config`, configToSend)
        await axios.post(`${API}/strategy/start`)
        setRunning(true)
    } catch (e) {
        console.error('Start error', e)
    }
  }

  const handleStop = async () => {
    try {
      await axios.post(`${API}/strategy/stop`)
      setRunning(false)
    } catch (e) {
      console.error('Stop error:', e)
    }
  }

  // ── Trade / close actions ───────────────────────────────────────────────────

  const executeTrade = async (ticker, side, quantity, price) => {
    await axios.post(`${API}/trade`, { ticker, side, quantity: parseInt(quantity), price: parseInt(price) })
    fetchAll()
  }

  const closePosition = async (ticker, side, quantity, price) => {
    await axios.post(`${API}/close`, { ticker, side, quantity: parseInt(quantity), price: parseInt(price) })
    fetchAll()
  }

  const cancelOrder = async (orderId) => {
    await axios.post(`${API}/cancel`, { order_id: orderId })
    fetchAll()
  }

  // ── Filtered markets ────────────────────────────────────────────────────────

  const filteredMarkets = markets.filter(m => {
    if (marketFilters.size === 0) return true
    if (marketFilters.has('high')   && Math.max(m.yes_bid, m.no_bid) < 90) return false
    if (marketFilters.has('soon')   && m.total_seconds_left >= 15 * 60)    return false
    if (marketFilters.has('volume') && m.volume < 1000)                   return false
    return true
  })

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="app">

      {/* Header */}
      <div className="header">
        <h1>Kalshi Trader</h1>
        {balance && (
          <div className="balance">
            <span>Cash: <strong>${balance.balance?.toFixed(2)}</strong></span>
            <span>Portfolio: <strong>${balance.portfolio_value?.toFixed(2)}</strong></span>
            <span>Total: <strong>${((balance.balance || 0) + (balance.portfolio_value || 0)).toFixed(2)}</strong></span>
          </div>
        )}
      </div>

      {/* Strategy Panel */}
      <StrategyPanel
        running={running}
        configs={configs}
        activeStrategy={activeStrategy}
        onStrategyChange={handleStrategyChange}
        onConfigChange={handleConfigChange}
        onStart={handleStart}
        onStop={handleStop}
      />

      {/* Tabs */}
      <div className="tabs">
        {['markets', 'orders', 'positions'].map(tab => (
          <FilterBtn key={tab} active={activeTab === tab} onClick={() => setActiveTab(tab)}>
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
            <span className="tab-count">
              {tab === 'markets'   ? filteredMarkets.length
             : tab === 'orders'   ? orders.length
             : positions.length}
            </span>
          </FilterBtn>
        ))}
      </div>

      {/* Markets Tab */}
      {activeTab === 'markets' && (
        <div className="tab-content">
          <div className="filter-bar">
            {[
              ['all',    'All'],
              ['high',   'High Prob (>90¢)'],
              ['soon',   'Expiring <15min'],
              ['volume', 'High Volume'],
            ].map(([val, label]) => (
              <FilterBtn
                key={val}
                active={val === 'all' ? marketFilters.size === 0 : marketFilters.has(val)}
                onClick={() => toggleMarketFilter(val)}
              >
                {label}
              </FilterBtn>
            ))}
          </div>
          <div className="table-scroll">
            <table>
              <thead><tr>
                <th>Ticker</th><th>Title</th><th>Subtitle</th>
                <th>Yes Sub</th><th>No Sub</th>
                <th>Yes Bid</th><th>Yes Ask</th><th>No Bid</th><th>No Ask</th>
                <th>Volume</th><th>Time</th><th>Action</th>
              </tr></thead>
              <tbody>
                {filteredMarkets.length === 0
                  ? <tr><td colSpan={12}>No markets</td></tr>
                  : filteredMarkets.map(m => (
                    <tr key={m.ticker} onClick={() => setTradeModal(m)} className="clickable">
                      <td>{m.ticker}</td>
                      <td>{m.title}</td>
                      <td>{m.subtitle || '-'}</td>
                      <td>{m.yes_sub_title || '-'}</td>
                      <td>{m.no_sub_title || '-'}</td>
                      <td>{m.yes_bid}¢</td><td>{m.yes_ask}¢</td>
                      <td>{m.no_bid}¢</td><td>{m.no_ask}¢</td>
                      <td>{m.volume.toLocaleString()}</td>
                      <td>{m.days_left > 0 ? `${m.days_left}d ${m.hours_left}h` : `${m.hours_left}h ${m.minutes_left}m`}</td>
                      <td><button className="btn-small" onClick={e => { e.stopPropagation(); setTradeModal(m) }}>Trade</button></td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Orders Tab */}
      {activeTab === 'orders' && (
        <div className="tab-content">
          <table>
            <thead><tr>
              <th>Ticker</th><th>Side</th><th>Action</th>
              <th>Price</th><th>Remaining</th><th>Created</th><th>Action</th>
            </tr></thead>
            <tbody>
              {orders.length === 0
                ? <tr><td colSpan={7}>No orders</td></tr>
                : orders.map(o => (
                  <tr key={o.order_id}>
                    <td>{o.ticker}</td>
                    <td>{o.side}</td>
                    <td>{o.action}</td>
                    <td>{o.price}¢</td>
                    <td>{o.remaining_count}/{o.initial_count}</td>
                    <td>{new Date(o.created_time).toLocaleString()}</td>
                    <td><button className="btn-small btn-danger" onClick={() => cancelOrder(o.order_id)}>Cancel</button></td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Positions Tab */}
      {activeTab === 'positions' && (
        <div className="tab-content">
          <table>
            <thead><tr>
              <th>Ticker</th><th>Side</th><th>Bid</th><th>Contracts</th>
              <th>Avg Price</th><th>Cost</th><th>Payout If Right</th>
              <th>Market Value</th><th>Return</th><th>Time</th><th>Action</th>
            </tr></thead>
            <tbody>
              {positions.length === 0
                ? <tr><td colSpan={11}>No positions</td></tr>
                : positions.map(p => {
                  const payoutPct = ((p.payout_if_right / p.cost - 1) * 100).toFixed(1)
                  const retPct    = p.cost > 0 ? (p.unrealized_return / p.cost * 100) : 0
                  const timeStr   = p.days_left > 0
                    ? `${p.days_left}d ${p.hours_left}h`
                    : `${p.hours_left}h ${p.minutes_left}m`
                  return (
                    <tr key={p.ticker}>
                      <td>{p.ticker}</td>
                      <td>{p.side}</td>
                      <td>{p.current_bid}¢</td>
                      <td>{p.contracts}</td>
                      <td>${p.avg_price.toFixed(4).replace(/\.?0+$/, '')}</td>
                      <td>${p.cost.toFixed(4).replace(/\.?0+$/, '')}</td>
                      <td>${p.payout_if_right.toFixed(2)} ({payoutPct}%)</td>
                      <td>${p.market_value.toFixed(2)}</td>
                      <td className={p.unrealized_return >= 0 ? 'positive' : 'negative'}>
                        ${p.unrealized_return.toFixed(2)} ({retPct >= 0 ? '+' : ''}{retPct.toFixed(1)}%)
                      </td>
                      <td>{timeStr}</td>
                      <td><button className="btn-small btn-danger" onClick={() => setCloseModal(p)}>Close</button></td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
        </div>
      )}

      {/* Trade Modal */}
      {tradeModal && (
        <Modal title={tradeModal.title} onClose={() => setTradeModal(null)}>
          <TradeForm market={tradeModal} onSubmit={executeTrade} onClose={() => setTradeModal(null)} />
        </Modal>
      )}

      {/* Close Position Modal */}
      {closeModal && (
        <Modal title={`Close: ${closeModal.ticker}`} onClose={() => setCloseModal(null)}>
          <p>{closeModal.contracts} {closeModal.side.toUpperCase()} contracts
            @ ${closeModal.avg_price.toFixed(4).replace(/\.?0+$/, '')} avg |
            Current Bid: {closeModal.current_bid}¢
          </p>
          <CloseForm position={closeModal} onSubmit={closePosition} onClose={() => setCloseModal(null)} />
        </Modal>
      )}
    </div>
  )
}

// ── TradeForm ─────────────────────────────────────────────────────────────────

function TradeForm({ market, onSubmit, onClose }) {
  const [side, setSide]         = useState('yes')
  const [quantity, setQuantity] = useState(1)
  const [price, setPrice]       = useState(market.yes_bid)

  const handleSideChange = (s) => {
    setSide(s)
    setPrice(s === 'yes' ? market.yes_bid : market.no_bid)
  }

  return (
    <div className="trade-form">
      <div className="form-row">
        <label>Side</label>
        <div>
          <FilterBtn active={side === 'yes'} onClick={() => handleSideChange('yes')}>YES ({market.yes_bid}¢)</FilterBtn>
          <FilterBtn active={side === 'no'}  onClick={() => handleSideChange('no')}>NO ({market.no_bid}¢)</FilterBtn>
        </div>
      </div>
      <div className="form-row">
        <label>Quantity</label>
        <input type="number" min={1} value={quantity} onChange={e => setQuantity(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Price (¢)</label>
        <input type="number" min={1} max={99} value={price} onChange={e => setPrice(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Est. Cost</label>
        <span>${(quantity * price / 100).toFixed(2)}</span>
      </div>
      <div className="modal-actions">
        <button className="btn-success" onClick={() => { onSubmit(market.ticker, side, quantity, price); onClose() }}>
          Buy {side.toUpperCase()}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}

// ── CloseForm ─────────────────────────────────────────────────────────────────

function CloseForm({ position, onSubmit, onClose }) {
  const [quantity, setQuantity] = useState(position.contracts)
  const [price, setPrice]       = useState(position.current_bid)

  return (
    <div className="trade-form">
      <div className="form-row">
        <label>Quantity</label>
        <input type="number" min={1} max={position.contracts} value={quantity}
          onChange={e => setQuantity(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Price (¢)</label>
        <input type="number" min={1} max={99} value={price}
          onChange={e => setPrice(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Est. Proceeds</label>
        <span>${(quantity * price / 100).toFixed(2)}</span>
      </div>
      <div className="modal-actions">
        <button className="btn-danger"
          onClick={() => { onSubmit(position.ticker, position.side, quantity, price); onClose() }}>
          Close {position.side.toUpperCase()}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}
