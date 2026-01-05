import { useState, useEffect } from 'react'
import axios from 'axios'

const API = 'http://localhost:8000/api'

function App() {
  const [balance, setBalance] = useState(0)
  const [markets, setMarkets] = useState([])
  const [positions, setPositions] = useState([])
  const [filters, setFilters] = useState({
    min_prob: 0.5,
    max_prob: 1.0,
    max_days: 30
  })
  const [selectedMarket, setSelectedMarket] = useState(null)
  const [orderForm, setOrderForm] = useState({
    quantity: 10,
    price: null,
    side: 'yes'
  })

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000) // refresh every 10s
    return () => clearInterval(interval)
  }, [filters])

  const fetchData = async () => {
    try {
      const [balRes, marketsRes, posRes] = await Promise.all([
        axios.get(`${API}/balance`),
        axios.get(`${API}/markets`, { params: filters }),
        axios.get(`${API}/positions`)
      ])
      setBalance(balRes.data.balance)
      setMarkets(marketsRes.data.markets)
      setPositions(posRes.data.positions)
    } catch (err) {
      console.error(err)
    }
  }

  const placeOrder = async () => {
    if (!selectedMarket) return
    try {
      await axios.post(`${API}/orders/create`, {
        ticker: selectedMarket.ticker,
        side: orderForm.side,
        quantity: orderForm.quantity,
        price: orderForm.price
      })
      alert('Order placed!')
      setSelectedMarket(null)
      fetchData()
    } catch (err) {
      alert('Error: ' + err.response?.data?.message || err.message)
    }
  }

  const closePosition = async (pos) => {
    if (!confirm(`Close ${pos.quantity} contracts of ${pos.ticker}?`)) return
    try {
      await axios.post(`${API}/orders/close`, null, {
        params: { ticker: pos.ticker, side: pos.side, quantity: pos.quantity }
      })
      alert('Position closed!')
      fetchData()
    } catch (err) {
      alert('Error: ' + err.response?.data?.message || err.message)
    }
  }

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0)

  return (
    <div style={{ padding: '20px', fontFamily: 'system-ui', maxWidth: '1400px', margin: '0 auto' }}>
      <h1>Kalshi Market Screener</h1>
      
      {/* Balance */}
      <div style={{ display: 'flex', gap: '20px', marginBottom: '30px' }}>
        <Card title="Balance" value={`$${balance.toFixed(2)}`} />
        <Card title="Total P&L" value={`$${totalPnl.toFixed(2)}`} color={totalPnl >= 0 ? 'green' : 'red'} />
        <Card title="Positions" value={positions.length} />
        <Card title="Markets" value={markets.length} />
      </div>

      {/* Filters */}
      <div style={{ background: '#f5f5f5', padding: '15px', borderRadius: '8px', marginBottom: '20px' }}>
        <h3>Filters</h3>
        <div style={{ display: 'flex', gap: '15px', alignItems: 'center' }}>
          <label>
            Min Prob: <input type="number" step="0.05" value={filters.min_prob} 
                           onChange={(e) => setFilters({...filters, min_prob: parseFloat(e.target.value)})} 
                           style={{ width: '70px', padding: '5px' }} />
          </label>
          <label>
            Max Prob: <input type="number" step="0.05" value={filters.max_prob} 
                           onChange={(e) => setFilters({...filters, max_prob: parseFloat(e.target.value)})} 
                           style={{ width: '70px', padding: '5px' }} />
          </label>
          <label>
            Max Days: <input type="number" value={filters.max_days} 
                           onChange={(e) => setFilters({...filters, max_days: parseInt(e.target.value)})} 
                           style={{ width: '70px', padding: '5px' }} />
          </label>
          <button onClick={fetchData} style={{ padding: '5px 15px', cursor: 'pointer' }}>Refresh</button>
        </div>
      </div>

      {/* Markets Table */}
      <div style={{ marginBottom: '30px' }}>
        <h2>Markets ({markets.length})</h2>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
            <thead>
              <tr style={{ background: '#333', color: 'white', textAlign: 'left' }}>
                <th style={{ padding: '10px' }}>Ticker</th>
                <th>Title</th>
                <th>Yes Bid</th>
                <th>Yes Ask</th>
                <th>Spread</th>
                <th>Days Left</th>
                <th>Volume</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {markets.map(m => {
                const spread = m.yes_ask - m.yes_bid
                return (
                  <tr key={m.ticker} style={{ borderBottom: '1px solid #ddd' }}>
                    <td style={{ padding: '10px', fontFamily: 'monospace' }}>{m.ticker}</td>
                    <td style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {m.title}
                    </td>
                    <td>{m.yes_bid}¢</td>
                    <td>{m.yes_ask}¢</td>
                    <td>{spread}¢</td>
                    <td>{m.days_left}d</td>
                    <td>{m.volume}</td>
                    <td>
                      <button onClick={() => setSelectedMarket(m)} 
                              style={{ padding: '5px 10px', cursor: 'pointer', background: '#007bff', color: 'white', border: 'none', borderRadius: '4px' }}>
                        Trade
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Order Modal */}
      {selectedMarket && (
        <div style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', 
                      background: 'white', padding: '30px', borderRadius: '8px', boxShadow: '0 4px 20px rgba(0,0,0,0.3)', zIndex: 1000 }}>
          <h2>Trade: {selectedMarket.ticker}</h2>
          <p style={{ marginBottom: '20px', color: '#666' }}>{selectedMarket.title}</p>
          
          <div style={{ marginBottom: '15px' }}>
            <label>Side: </label>
            <select value={orderForm.side} onChange={(e) => setOrderForm({...orderForm, side: e.target.value})} 
                    style={{ padding: '5px', marginLeft: '10px' }}>
              <option value="yes">Yes ({selectedMarket.yes_ask}¢)</option>
              <option value="no">No ({selectedMarket.no_ask}¢)</option>
            </select>
          </div>
          
          <div style={{ marginBottom: '15px' }}>
            <label>Quantity: </label>
            <input type="number" value={orderForm.quantity} 
                   onChange={(e) => setOrderForm({...orderForm, quantity: parseInt(e.target.value)})} 
                   style={{ padding: '5px', marginLeft: '10px', width: '80px' }} />
          </div>
          
          <div style={{ marginBottom: '15px' }}>
            <label>Limit Price (¢): </label>
            <input type="number" value={orderForm.price || ''} placeholder="Market order"
                   onChange={(e) => setOrderForm({...orderForm, price: e.target.value ? parseInt(e.target.value) : null})} 
                   style={{ padding: '5px', marginLeft: '10px', width: '80px' }} />
            <span style={{ fontSize: '12px', color: '#666', marginLeft: '10px' }}>Leave empty for market order</span>
          </div>
          
          <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
            <button onClick={placeOrder} 
                    style={{ padding: '10px 20px', background: '#28a745', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
              Place Order
            </button>
            <button onClick={() => setSelectedMarket(null)} 
                    style={{ padding: '10px 20px', background: '#dc3545', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {selectedMarket && <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 999 }} onClick={() => setSelectedMarket(null)} />}

      {/* Positions Table */}
      <div>
        <h2>Open Positions ({positions.length})</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#333', color: 'white', textAlign: 'left' }}>
              <th style={{ padding: '10px' }}>Ticker</th>
              <th>Side</th>
              <th>Quantity</th>
              <th>Avg Price</th>
              <th>Current Price</th>
              <th>P&L</th>
              <th>P&L %</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #ddd' }}>
                <td style={{ padding: '10px', fontFamily: 'monospace' }}>{p.ticker}</td>
                <td>{p.side}</td>
                <td>{p.quantity}</td>
                <td>{(p.avg_price * 100).toFixed(0)}¢</td>
                <td>{(p.current_price * 100).toFixed(0)}¢</td>
                <td style={{ color: p.pnl >= 0 ? 'green' : 'red', fontWeight: 'bold' }}>
                  ${p.pnl.toFixed(2)}
                </td>
                <td style={{ color: p.pnl_pct >= 0 ? 'green' : 'red' }}>
                  {p.pnl_pct.toFixed(1)}%
                </td>
                <td>
                  <button onClick={() => closePosition(p)} 
                          style={{ padding: '5px 10px', cursor: 'pointer', background: '#dc3545', color: 'white', border: 'none', borderRadius: '4px' }}>
                    Close
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const Card = ({ title, value, color = 'black' }) => (
  <div style={{ padding: '20px', background: 'white', border: '1px solid #ddd', borderRadius: '8px', flex: 1 }}>
    <div style={{ fontSize: '14px', color: '#666', marginBottom: '8px' }}>{title}</div>
    <div style={{ fontSize: '28px', fontWeight: 'bold', color }}>{value}</div>
  </div>
)

export default App
