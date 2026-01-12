import { useState, useEffect } from 'react'
import axios from 'axios'
import './App.css'

const API = 'http://localhost:8000/api'

const FilterBtn = ({ active, onClick, children }) => (
  <button className={`filter-btn ${active ? 'active' : ''}`} onClick={onClick}>{children}</button>
)

const Modal = ({ title, onClose, children }) => (
  <>
    <div className="modal-overlay" onClick={onClose} />
    <div className="modal"><h3>{title}</h3>{children}</div>
  </>
)

function App() {
  const [balance, setBalance] = useState(0)
  const [markets, setMarkets] = useState([])
  const [orders, setOrders] = useState([])
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ highProb: false, tightSpread: false, highVolume: false })
  const [tradeModal, setTradeModal] = useState(null)
  const [closeModal, setCloseModal] = useState(null)
  const [tradeSide, setTradeSide] = useState('yes')
  const [strategyEnabled, setStrategyEnabled] = useState(false)
  const [strategyConfig, setStrategyConfig] = useState({
    capital_allocation: 50,
    position_size: 5,
    min_probability: 98,
    scan_frequency: 15,
    stop_loss: 50,
    max_time_to_expiry: 72,
    max_pending_age_minutes: 5,
    order_delay_seconds: 2,
    max_positions: 20
  })

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
      setBalance(balRes.data.balance)
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
      const res = await axios.get(`${API}/strategy`)
      setStrategyConfig(res.data)
      setStrategyEnabled(res.data.enabled)
    } catch (err) {
      console.error('Failed to load strategy config')
    }
  }

  const updateStrategyConfig = async (newConfig) => {
    try {
      await axios.put(`${API}/strategy/config`, newConfig)
    } catch (err) {
      console.error('Failed to update config')
    }
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
    const spread = m.yes_ask - m.yes_bid
    return (!filters.highProb || (m.yes_bid >= 98 || m.no_bid >= 98)) &&
          (!filters.tightSpread || spread <= 2) &&
          (!filters.highVolume || m.volume >= 10000)
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

  const posVal = positions.reduce((sum, p) => sum + p.market_value, 0)
  const portVal = balance + posVal

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

      <section className="strategy-panel">
        <div className="strategy-status">
          <div>
            <h2>High Probability Strategy</h2>
            <div className="status-indicator">
              <span className={`status-dot ${strategyEnabled ? 'running' : 'stopped'}`}></span>
              <span className="status-text">{strategyEnabled ? 'Running' : 'Stopped'}</span>
            </div>
          </div>
        </div>

        <div className="strategy-params">
          <div className="param-group">
            <label>
              Capital Allocation: {strategyConfig.capital_allocation}%
              <input 
                type="range" 
                min="10" 
                max="100" 
                step="5"
                value={strategyConfig.capital_allocation}
                onChange={(e) => setStrategyConfig({...strategyConfig, capital_allocation: parseInt(e.target.value)})}
              />
            </label>
          </div>
          
          <div className="param-group">
            <label>
              Position Size: {strategyConfig.position_size}%
              <input 
                type="range" 
                min="1" 
                max="20" 
                step="1"
                value={strategyConfig.position_size}
                onChange={(e) => setStrategyConfig({...strategyConfig, position_size: parseInt(e.target.value)})}
              />
            </label>
          </div>

          <div className="param-group">
            <label>
              Min Probability: {strategyConfig.min_probability}¢
              <input 
                type="number" 
                min="95" 
                max="99"
                value={strategyConfig.min_probability}
                onChange={(e) => setStrategyConfig({...strategyConfig, min_probability: parseInt(e.target.value)})}
              />
            </label>
          </div>

          <div className="param-group">
            <label>
              Scan Every:
              <select 
                value={strategyConfig.scan_frequency}
                onChange={(e) => setStrategyConfig({...strategyConfig, scan_frequency: parseInt(e.target.value)})}
              >
                <option value="5">5 min</option>
                <option value="10">10 min</option>
                <option value="15">15 min</option>
                <option value="30">30 min</option>
                <option value="60">60 min</option>
              </select>
            </label>
          </div>

          <div className="param-group">
            <label>
              Stop Loss: {strategyConfig.stop_loss}¢
              <input 
                type="number" 
                min="1" 
                max="99"
                value={strategyConfig.stop_loss}
                onChange={(e) => setStrategyConfig({...strategyConfig, stop_loss: parseInt(e.target.value)})}
              />
            </label>
          </div>

          <div className="param-group">
            <label>
              Max Time to Expiry (hrs): {strategyConfig.max_time_to_expiry}
              <input 
                type="number" 
                min="1" 
                max="168"
                value={strategyConfig.max_time_to_expiry}
                onChange={(e) => setStrategyConfig({...strategyConfig, max_time_to_expiry: parseInt(e.target.value)})}
              />
            </label>
          </div>

          <div className="param-group">
            <label>
              Max Positions: {strategyConfig.max_positions}
              <input 
                type="number" 
                min="5" 
                max="50"
                value={strategyConfig.max_positions}
                onChange={(e) => setStrategyConfig({...strategyConfig, max_positions: parseInt(e.target.value)})}
              />
            </label>
          </div>

          <div className="param-group">
            <label>
              Pending Order Max Age (min): {strategyConfig.max_pending_age_minutes}
              <input 
                type="number" 
                min="1" 
                max="30"
                value={strategyConfig.max_pending_age_minutes}
                onChange={(e) => setStrategyConfig({...strategyConfig, max_pending_age_minutes: parseInt(e.target.value)})}
              />
            </label>
          </div>
        </div>

        <div className="strategy-controls">
          <button 
            className={`btn-toggle ${strategyEnabled ? 'active' : ''}`}
            onClick={toggleStrategy}
          >
            {strategyEnabled ? 'Stop' : 'Start'}
          </button>
        </div>
      </section>

      <section>
        <div className="section-header">
          <h2>Markets ({filteredMarkets.length} expiring in 72h)</h2>
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
        <div className="table-container">
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
