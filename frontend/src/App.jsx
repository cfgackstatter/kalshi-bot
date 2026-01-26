import { useState, useEffect } from 'react'
import axios from 'axios'
import './App.css'

const API = 'http://localhost:8000/api'

const FilterBtn = ({ active, onClick, children }) => (
  <button className={`filter-btn ${active ? 'active' : ''}`} onClick={onClick}>{children}</button>
)

const Modal = ({ title, onClose, children }) => (
  <div className="modal-overlay" onClick={onClose}>
    <div className="modal" onClick={(e) => e.stopPropagation()}>
      <h3>{title}</h3>
      {children}
    </div>
  </div>
)

function App() {
  const [balance, setBalance] = useState(0)
  const [portfolioValue, setPortfolioValue] = useState(0)
  const [markets, setMarkets] = useState([])
  const [orders, setOrders] = useState([])
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ highProb: false, tightSpread: false, highVolume: false })
  const [tradeModal, setTradeModal] = useState(null)
  const [closeModal, setCloseModal] = useState(null)
  const [tradeSide, setTradeSide] = useState('yes')
  const [strategyEnabled, setStrategyEnabled] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [strategyConfig, setStrategyConfig] = useState(null)

  useEffect(() => {
    fetchData()
    fetchStrategyConfig()
  }, [])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [balRes, marketsRes, ordersRes, posRes] = await Promise.all([
        axios.get(`${API}/balance`),
        axios.get(`${API}/markets`),
        axios.get(`${API}/orders`),
        axios.get(`${API}/positions`)
      ])

      const balData = balRes.data
      const cash = balData.balance                    // Cash
      const positionsVal = balData.portfolio_value    // Positions value
      const totalPortfolio = cash + positionsVal      // TOTAL

      setBalance(cash)
      setPortfolioValue(totalPortfolio)  // Store TOTAL
      setMarkets(marketsRes.data.markets)
      setOrders(ordersRes.data.orders)
      setPositions(posRes.data.positions)
    } catch (err) {
      alert('Error: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const fetchStrategyConfig = async () => {
    try {
      const res = await axios.get(`${API}/strategy/config`)
      setStrategyConfig(res.data)
      setStrategyEnabled(res.data.enabled || false)
    } catch (err) {
      console.error('Failed to load strategy config:', err)
      alert('Failed to load strategy configuration')
    }
  }

  const updateStrategyConfig = async (newConfig) => {
    try {
      await axios.put(`${API}/strategy/config`, newConfig)
    } catch (err) {
      console.error('Failed to update config')
    }
  }

  const handleConfigChange = async (key, value) => {
    if (!strategyConfig) return
    const newConfig = { ...strategyConfig, [key]: value }
    setStrategyConfig(newConfig)
    await updateStrategyConfig(newConfig)
  }

  const toggleStrategy = async () => {
    try {
      if (strategyEnabled) {
        await axios.post(`${API}/strategy/stop`)
      } else {
        await axios.post(`${API}/strategy/start`)
      }
      setStrategyEnabled(!strategyEnabled)
    } catch (err) {
      alert('Error: ' + err.message)
    }
  }

  const filteredMarkets = markets.filter(m => {
    const yes_mid = (m.yes_bid + m.yes_ask) / 2
    const no_mid = (m.no_bid + m.no_ask) / 2
    const spread = m.yes_ask - m.yes_bid
    return (
      (!filters.highProb || (yes_mid >= 98 || no_mid >= 98)) &&
      (!filters.tightSpread || spread <= 2) &&
      (!filters.highVolume || m.volume >= 10000)
    )
  })

  const cancelOrder = async (orderId) => {
    if (!confirm('Cancel this order?')) return
    try {
      await axios.post(`${API}/cancel`, { order_id: orderId })
      fetchData()
    } catch (err) {
      alert('Error: ' + err.message)
    }
  }

  const submitTrade = async (e, ticker) => {
    e.preventDefault()
    const fd = new FormData(e.target)
    try {
      await axios.post(`${API}/trade`, {
        ticker,
        side: fd.get('side'),
        quantity: parseInt(fd.get('quantity')),
        price: parseInt(fd.get('price'))
      })
      setTradeModal(null)
      fetchData()
    } catch (err) {
      alert('Error: ' + err.message)
    }
  }

  const submitClose = async (e, ticker) => {
    e.preventDefault()
    const fd = new FormData(e.target)
    try {
      await axios.post(`${API}/close`, {
        ticker,
        side: fd.get('side'),
        quantity: parseInt(fd.get('quantity')),
        price: parseInt(fd.get('price'))
      })
      setCloseModal(null)
      fetchData()
    } catch (err) {
      alert('Error: ' + err.message)
    }
  }

  const posVal = portfolioValue - balance
  const portVal = portfolioValue

  return (
    <div className="container">
      <div className="header">
        <div>
          <h1>Kalshi Trading</h1>
          <div className="stats">
            <span>Cash: ${balance.toFixed(2)}</span>
            <span>Positions: ${posVal.toFixed(2)}</span>
            <span>Total: ${portVal.toFixed(2)}</span>
          </div>
        </div>
        <button onClick={fetchData} disabled={loading} className="btn-primary">
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <section className="strategy-panel-improved">
        <div className="strategy-header">
          <div className="strategy-title">
            <h2>High Probability Strategy</h2>
            <div className="status-indicator">
              <span className={`status-dot ${strategyEnabled ? 'running' : 'stopped'}`}></span>
              <span className="status-text">{strategyEnabled ? 'Running' : 'Stopped'}</span>
            </div>
          </div>
          <button
            className={`btn-toggle ${strategyEnabled ? 'active' : ''}`}
            onClick={toggleStrategy}
          >
            {strategyEnabled ? 'Stop' : 'Start'}
          </button>
        </div>

        {!strategyConfig ? (
          <div>Loading configuration...</div>
        ) : (
          <div className="strategy-config-grid">
            {/* FIRST COLUMN: Capital Settings */}
            <div className="config-card">
              <h3 className="card-title">Capital Settings</h3>

              <div className="param-item">
                <div className="param-label-row">
                  <label>Capital Allocation</label>
                  <span className="param-value">{strategyConfig.capital_allocation}%</span>
                </div>
                <input
                  type="range"
                  min="10"
                  max="100"
                  step="5"
                  value={strategyConfig.capital_allocation}
                  onChange={(e) => handleConfigChange('capital_allocation', parseInt(e.target.value))}
                />
                <div className="param-hint">Will use ${(portVal * strategyConfig.capital_allocation / 100).toFixed(2)} of ${portVal.toFixed(2)}</div>
              </div>

              <div className="param-item">
                <div className="param-label-row">
                  <label>Position Size</label>
                  <span className="param-value">{strategyConfig.position_size}%</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="20"
                  step="1"
                  value={strategyConfig.position_size}
                  onChange={(e) => handleConfigChange('position_size', parseInt(e.target.value))}
                />
                <div className="param-hint">~${(portVal * strategyConfig.position_size / 100).toFixed(2)} per position</div>
              </div>
            </div>

            {/* SECOND COLUMN: Entry Filters */}
            <div className="config-card">
              <h3 className="card-title">Entry Filters</h3>

              <div className="param-item">
                <div className="param-label-row">
                  <label>Min Probability</label>
                  <span className="param-value">{strategyConfig.min_probability}¢</span>
                </div>
                <input
                  type="number"
                  min="95"
                  max="99"
                  value={strategyConfig.min_probability}
                  onChange={(e) => handleConfigChange('min_probability', parseInt(e.target.value))}
                />
              </div>

              <div className="param-item">
                <div className="param-label-row">
                  <label>Max Spread</label>
                  <span className="param-value">{strategyConfig.max_spread}¢</span>
                </div>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={strategyConfig.max_spread}
                  onChange={(e) => handleConfigChange('max_spread', parseInt(e.target.value))}
                />
              </div>

              <div className="param-item">
                <div className="param-label-row">
                  <label>Min Volume</label>
                  <span className="param-value">{strategyConfig.min_volume.toLocaleString()}</span>
                </div>
                <input
                  type="number"
                  min="0"
                  max="100000"
                  step="1000"
                  value={strategyConfig.min_volume}
                  onChange={(e) => handleConfigChange('min_volume', parseInt(e.target.value))}
                />
              </div>

              <div className="param-item">
                <div className="param-label-row">
                  <label>Max Time to Expiry</label>
                  <span className="param-value">
                    {strategyConfig.max_time_to_expiry >= 1 
                      ? `${strategyConfig.max_time_to_expiry}h`
                      : `${strategyConfig.max_time_to_expiry * 60}m`
                    }
                  </span>
                </div>
                <input
                  type="number"
                  min="0.1"
                  max="168"
                  step="0.5"
                  value={strategyConfig.max_time_to_expiry}
                  onChange={(e) => handleConfigChange('max_time_to_expiry', parseFloat(e.target.value))}
                />
              </div>
            </div>

            {/* THIRD COLUMN: Frequency */}
            <div className="config-card">
              <h3 className="card-title">Frequency</h3>

              <div className="param-item">
                <label>Scan Every:</label>
                <div className="button-group">
                  {[1, 5, 10, 15, 30, 45, 60].map(min => (
                    <button
                      key={min}
                      className={`freq-btn ${strategyConfig.scan_frequency === min ? 'active' : ''}`}
                      onClick={() => handleConfigChange('scan_frequency', min)}
                    >
                      {min}min
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Advanced Settings - Collapsible */}
        <div className="advanced-section">
          <button 
            className="advanced-toggle"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? '▼' : '▶'} Advanced Settings
          </button>

          {showAdvanced && (
            <div className="advanced-content">
              <div className="advanced-grid">
                <div className="param-item-compact">
                  <label>Stop Loss (¢):</label>
                  <input
                    type="number"
                    min="1"
                    max="99"
                    value={strategyConfig.stop_loss}
                    onChange={(e) => handleConfigChange('stop_loss', parseInt(e.target.value))}
                  />
                </div>

                <div className="param-item-compact">
                  <label>Order Max Age (min):</label>
                  <input
                    type="number"
                    min="1"
                    max="30"
                    value={strategyConfig.max_pending_age_minutes}
                    onChange={(e) => handleConfigChange('max_pending_age_minutes', parseInt(e.target.value))}
                  />
                </div>

                <div className="param-item-compact">
                  <label>Order Delay (sec):</label>
                  <input
                    type="number"
                    min="0"
                    max="5"
                    step="0.1"
                    value={strategyConfig.order_delay_seconds}
                    onChange={(e) => handleConfigChange('order_delay_seconds', parseFloat(e.target.value))}
                  />
                </div>

                <div className="param-item-compact">
                  <label>Exclude Tickers:</label>
                  <input
                    type="text"
                    placeholder="e.g., MENTION-,SAY-,NETFLIX"
                    value={strategyConfig.ticker_exclude_substrings}
                    onChange={(e) => handleConfigChange('ticker_exclude_substrings', e.target.value)}
                    style={{minWidth: '150px'}}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      <section>
        <div className="section-header">
          <h2>Markets expiring within 24h ({filteredMarkets.length})</h2>
          <div className="filters">
            <FilterBtn active={filters.highProb} onClick={() => setFilters({...filters, highProb: !filters.highProb})}>
              High Prob ≥98¢
            </FilterBtn>
            <FilterBtn active={filters.tightSpread} onClick={() => setFilters({...filters, tightSpread: !filters.tightSpread})}>
              Tight Spread ≤2¢
            </FilterBtn>
            <FilterBtn active={filters.highVolume} onClick={() => setFilters({...filters, highVolume: !filters.highVolume})}>
              Volume ≥10k
            </FilterBtn>
          </div>
        </div>
        <div className="table-container-scrollable">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Title</th>
                <th>Subtitle</th>
                <th>Yes Sub</th>
                <th>No Sub</th>
                <th>Yes Bid</th>
                <th>Yes Ask</th>
                <th>No Bid</th>
                <th>No Ask</th>
                <th>Volume</th>
                <th>Time</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filteredMarkets.length === 0 && <tr><td colSpan="12">No markets</td></tr>}
              {filteredMarkets.map(m => (
                <tr key={m.ticker}>
                  <td>{m.ticker}</td>
                  <td>{m.title}</td>
                  <td>{m.subtitle || '-'}</td>
                  <td>{m.yes_sub_title || '-'}</td>
                  <td>{m.no_sub_title || '-'}</td>
                  <td>{m.yes_bid}¢</td>
                  <td>{m.yes_ask}¢</td>
                  <td>{m.no_bid}¢</td>
                  <td>{m.no_ask}¢</td>
                  <td>{m.volume.toLocaleString()}</td>
                  <td>{m.days_left > 0 ? `${m.days_left}d ${m.hours_left}h` : `${m.hours_left}h ${m.minutes_left}m`}</td>
                  <td><button className="btn-sm btn-success" onClick={() => { setTradeSide('yes'); setTradeModal(m); }}>Trade</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {orders.length > 0 && (
        <section>
          <h2>Pending Orders ({orders.length})</h2>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Side</th>
                  <th>Action</th>
                  <th>Price</th>
                  <th>Remaining</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {orders.map(o => (
                  <tr key={o.order_id}>
                    <td>{o.ticker}</td>
                    <td className="uppercase">{o.side}</td>
                    <td className="capitalize">{o.action}</td>
                    <td>{o.price}¢</td>
                    <td>{o.remaining_count}/{o.initial_count}</td>
                    <td>{new Date(o.created_time).toLocaleString()}</td>
                    <td><button className="btn-sm btn-danger" onClick={() => cancelOrder(o.order_id)}>Cancel</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section>
        <h2>Open Positions ({positions.length})</h2>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Side</th>
                <th>Bid</th>
                <th>Contracts</th>
                <th>Avg Price</th>
                <th>Cost</th>
                <th>Payout If Right</th>
                <th>Market Value</th>
                <th>Return</th>
                <th>Time</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && <tr><td colSpan="11">No positions</td></tr>}
              {positions.map(p => {
                const retPct = (p.unrealized_return / p.cost) * 100
                const payoutPct = ((p.payout_if_right / p.cost - 1) * 100).toFixed(0)
                const timeStr = p.days_left > 0 ? `${p.days_left}d ${p.hours_left}h` : `${p.hours_left}h ${p.minutes_left}m`
                return (
                  <tr key={p.ticker}>
                    <td>{p.ticker}</td>
                    <td className="uppercase">{p.side}</td>
                    <td>{p.current_bid}¢</td>
                    <td>{p.contracts}</td>
                    <td>{p.avg_price.toFixed(2)}¢</td>
                    <td>${p.cost.toFixed(2)}</td>
                    <td>${p.payout_if_right.toFixed(2)} ({payoutPct}%)</td>
                    <td>${p.market_value.toFixed(2)}</td>
                    <td className={retPct >= 0 ? 'positive' : 'negative'}>
                      ${p.unrealized_return.toFixed(2)} ({retPct >= 0 ? '+' : ''}{retPct.toFixed(1)}%)
                    </td>
                    <td>{timeStr}</td>
                    <td><button className="btn-sm btn-warning" onClick={() => setCloseModal(p)}>Close</button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      {tradeModal && (
        <Modal title={`Trade: ${tradeModal.ticker}`} onClose={() => setTradeModal(null)}>
          <p className="subtitle">{tradeModal.title}</p>
          <form onSubmit={(e) => submitTrade(e, tradeModal.ticker)}>
            <label>Side
              <select 
                name="side" 
                required 
                value={tradeSide} 
                onChange={(e) => setTradeSide(e.target.value)}
              >
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <label>Quantity<input type="number" name="quantity" min="1" required /></label>
            <label>Price (¢)
              <input 
                type="number" 
                name="price" 
                min="1" 
                max="99" 
                key={tradeSide} 
                defaultValue={tradeSide === 'yes' ? tradeModal.yes_ask : tradeModal.no_ask} 
                required 
              />
            </label>
            <div className="btn-group">
              <button type="submit" className="btn-primary">Submit</button>
              <button type="button" className="btn-secondary" onClick={() => setTradeModal(null)}>Cancel</button>
            </div>
          </form>
        </Modal>
      )}

      {closeModal && (
        <Modal title={`Close: ${closeModal.ticker}`} onClose={() => setCloseModal(null)}>
          <p className="subtitle">
            {closeModal.contracts} {closeModal.side.toUpperCase()} contracts @ {closeModal.avg_price.toFixed(2)}¢ | 
            Current Bid: {closeModal.current_bid}¢
          </p>
          <form onSubmit={(e) => submitClose(e, closeModal.ticker)}>
            <label>Side
              <input type="text" value={closeModal.side.toUpperCase()} disabled style={{background: '#f3f4f6', cursor: 'not-allowed'}} />
              <input type="hidden" name="side" value={closeModal.side} />
            </label>
            <label>Quantity
              <input type="number" name="quantity" min="1" max={closeModal.contracts} defaultValue={closeModal.contracts} required />
            </label>
            <label>Price (¢)
              <input type="number" name="price" min="1" max="99" defaultValue={closeModal.current_bid} required />
            </label>
            <div className="btn-group">
              <button type="submit" className="btn-primary">Submit</button>
              <button type="button" className="btn-secondary" onClick={() => setCloseModal(null)}>Cancel</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

export default App
