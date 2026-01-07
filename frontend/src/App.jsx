import { useState, useEffect } from 'react'
import axios from 'axios'

const API = 'http://localhost:8000/api'

function App() {
  const [balance, setBalance] = useState(0)
  const [markets, setMarkets] = useState([])
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({
    highProb: false,
    tightSpread: false,
    highVolume: false
  })
  const [tradeModal, setTradeModal] = useState(null)
  const [closeModal, setCloseModal] = useState(null)

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [balRes, marketsRes, posRes] = await Promise.all([
        axios.get(`${API}/balance`),
        axios.get(`${API}/markets`),
        axios.get(`${API}/positions`)
      ])
      setBalance(balRes.data.balance)
      setMarkets(marketsRes.data.markets)
      setPositions(posRes.data.positions)
    } catch (err) {
      console.error(err)
      alert('Error fetching data: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const filteredMarkets = markets.filter(m => {
    const spread = m.yes_ask - m.yes_bid
    if (filters.highProb && m.yes_bid < 98) return false
    if (filters.tightSpread && spread > 2) return false
    if (filters.highVolume && m.volume < 10000) return false
    return true
  })

  const totalPnl = positions.reduce((sum, p) => sum + p.realized_pnl_dollars, 0)

  return (
    <div style={{ padding: '15px', fontFamily: 'system-ui', maxWidth: '2000px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
        <h1 style={{ margin: 0, fontSize: '24px' }}>Kalshi Viewer</h1>
        <button 
          onClick={fetchData} 
          disabled={loading}
          style={{ 
            padding: '8px 16px', 
            background: loading ? '#ccc' : '#007bff', 
            color: 'white', 
            border: 'none', 
            borderRadius: '4px', 
            cursor: loading ? 'not-allowed' : 'pointer',
            fontWeight: 'bold'
          }}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '15px' }}>
        <Card title="Balance" value={`$${balance.toFixed(2)}`} />
        <Card title="Realized P&L" value={`$${totalPnl.toFixed(2)}`} color={totalPnl >= 0 ? 'green' : 'red'} />
        <Card title="Positions" value={positions.length} />
        <Card title="Markets" value={`${filteredMarkets.length} / ${markets.length}`} />
      </div>

      <div style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <h2 style={{ fontSize: '18px', margin: 0 }}>
            Markets ({filteredMarkets.length}{filteredMarkets.length !== markets.length && ` of ${markets.length}`})
          </h2>
          
          <div style={{ display: 'flex', gap: '8px' }}>
            <FilterButton 
              active={filters.highProb}
              onClick={() => setFilters({...filters, highProb: !filters.highProb})}
              label="High Prob ≥98¢"
            />
            <FilterButton 
              active={filters.tightSpread}
              onClick={() => setFilters({...filters, tightSpread: !filters.tightSpread})}
              label="Tight Spread ≤2¢"
            />
            <FilterButton 
              active={filters.highVolume}
              onClick={() => setFilters({...filters, highVolume: !filters.highVolume})}
              label="Volume ≥10k"
            />
          </div>
        </div>

        <div style={{ 
          maxHeight: '500px', 
          overflowY: 'auto', 
          border: '1px solid #ddd', 
          borderRadius: '4px',
          background: 'white'
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
            <thead style={{ position: 'sticky', top: 0, background: '#333', zIndex: 1 }}>
              <tr style={{ color: 'white', textAlign: 'left' }}>
                <th style={{ padding: '8px', minWidth: '120px' }}>Ticker</th>
                <th style={{ minWidth: '250px' }}>Title</th>
                <th style={{ minWidth: '120px' }}>Subtitle</th>
                <th style={{ minWidth: '120px' }}>Yes Sub</th>
                <th style={{ minWidth: '120px' }}>No Sub</th>
                <th>Yes Bid</th>
                <th>Yes Ask</th>
                <th>No Bid</th>
                <th>No Ask</th>
                <th>Volume</th>
                <th>Open Int.</th>
                <th>Time Left</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredMarkets.length === 0 ? (
                <tr>
                  <td colSpan="13" style={{ padding: '20px', textAlign: 'center', color: '#999' }}>
                    No markets match current filters
                  </td>
                </tr>
              ) : (
                filteredMarkets.map(m => {
                  const timeStr = m.days_left > 0 
                    ? `${m.days_left}d ${m.hours_left}h`
                    : `${m.hours_left}h ${m.minutes_left}m`
                  
                  return (
                    <tr key={m.ticker} style={{ borderBottom: '1px solid #eee' }}>
                      <td style={{ padding: '8px', fontFamily: 'monospace', fontSize: '10px' }}>{m.ticker}</td>
                      <td>{m.title}</td>
                      <td style={{ color: '#555' }}>{m.subtitle || '-'}</td>
                      <td style={{ color: '#555' }}>{m.yes_sub_title || '-'}</td>
                      <td style={{ color: '#555' }}>{m.no_sub_title || '-'}</td>
                      <td style={{ fontWeight: 'bold', color: '#28a745' }}>{m.yes_bid}¢</td>
                      <td style={{ fontWeight: 'bold', color: '#007bff' }}>{m.yes_ask}¢</td>
                      <td style={{ fontWeight: 'bold', color: '#28a745' }}>{m.no_bid}¢</td>
                      <td style={{ fontWeight: 'bold', color: '#007bff' }}>{m.no_ask}¢</td>
                      <td>{m.volume.toLocaleString()}</td>
                      <td>{m.open_interest.toLocaleString()}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>{timeStr}</td>
                      <td>
                        <button
                          onClick={() => setTradeModal(m)}
                          style={{
                            padding: '4px 8px',
                            background: '#007bff',
                            color: 'white',
                            border: 'none',
                            borderRadius: '3px',
                            cursor: 'pointer',
                            fontSize: '11px',
                            fontWeight: 'bold'
                          }}>
                          Trade
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 style={{ fontSize: '18px', marginBottom: '8px' }}>Open Positions ({positions.length})</h2>
        <div style={{ 
          maxHeight: '300px', 
          overflowY: 'auto', 
          border: '1px solid #ddd', 
          borderRadius: '4px',
          background: 'white'
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead style={{ position: 'sticky', top: 0, background: '#333', zIndex: 1 }}>
              <tr style={{ color: 'white', textAlign: 'left' }}>
                <th style={{ padding: '8px' }}>Ticker</th>
                <th>Contracts</th>
                <th>Exposure</th>
                <th>Realized P&L</th>
                <th>Total Traded</th>
                <th>Fees Paid</th>
                <th>Resting Orders</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 ? (
                <tr>
                  <td colSpan="8" style={{ padding: '20px', textAlign: 'center', color: '#999' }}>
                    No open positions
                  </td>
                </tr>
              ) : (
                positions.map((p, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                    <td style={{ padding: '8px', fontFamily: 'monospace' }}>{p.ticker}</td>
                    <td>{p.position}</td>
                    <td>${p.market_exposure_dollars.toFixed(2)}</td>
                    <td style={{ color: p.realized_pnl_dollars >= 0 ? 'green' : 'red', fontWeight: 'bold' }}>
                      ${p.realized_pnl_dollars.toFixed(2)}
                    </td>
                    <td>{p.total_traded}</td>
                    <td>${p.fees_paid_dollars.toFixed(2)}</td>
                    <td>{p.resting_orders_count}</td>
                    <td>
                      <button
                        onClick={() => setCloseModal(p)}
                        style={{
                          padding: '4px 8px',
                          background: '#dc3545',
                          color: 'white',
                          border: 'none',
                          borderRadius: '3px',
                          cursor: 'pointer',
                          fontSize: '11px',
                          fontWeight: 'bold'
                        }}>
                        Close
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {tradeModal && <TradeModal market={tradeModal} onClose={() => setTradeModal(null)} onSuccess={fetchData} />}
      {closeModal && <CloseModal position={closeModal} markets={markets} onClose={() => setCloseModal(null)} onSuccess={fetchData} />}
    </div>
  )
}

const Card = ({ title, value, color = 'black' }) => (
  <div style={{ padding: '12px', background: 'white', border: '1px solid #ddd', borderRadius: '4px' }}>
    <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>{title}</div>
    <div style={{ fontSize: '20px', fontWeight: 'bold', color }}>{value}</div>
  </div>
)

const FilterButton = ({ active, onClick, label }) => (
  <button
    onClick={onClick}
    style={{
      padding: '6px 12px',
      background: active ? '#28a745' : '#f8f9fa',
      color: active ? 'white' : '#333',
      border: active ? 'none' : '1px solid #ddd',
      borderRadius: '4px',
      cursor: 'pointer',
      fontSize: '12px',
      fontWeight: active ? 'bold' : 'normal'
    }}>
    {label} {active && '✓'}
  </button>
)

const TradeModal = ({ market, onClose, onSuccess }) => {
  const [side, setSide] = useState('yes')
  const [quantity, setQuantity] = useState(100)
  const [price, setPrice] = useState(side === 'yes' ? market.yes_ask : market.no_ask)
  const [loading, setLoading] = useState(false)

  const handleSideChange = (newSide) => {
    setSide(newSide)
    setPrice(newSide === 'yes' ? market.yes_ask : market.no_ask)
  }

  const totalCost = (quantity * price / 100).toFixed(2)
  const fee = Math.ceil(0.07 * quantity * (price/100) * (1 - price/100) * 100) / 100

  const handleTrade = async () => {
    if (quantity <= 0) {
      alert('Quantity must be positive')
      return
    }

    if (price < 1 || price > 99) {
      alert('Price must be between 1¢ and 99¢')
      return
    }

    if (!window.confirm(`Place limit order?\n\nBuy ${quantity} ${side.toUpperCase()} @ ${price}¢\nTotal: $${totalCost}\nEstimated fee: $${fee.toFixed(2)}`)) {
      return
    }

    setLoading(true)
    try {
      await axios.post(`${API}/trade`, {
        ticker: market.ticker,
        side,
        quantity,
        price
      })
      alert('Limit order placed successfully!')
      onSuccess()
      onClose()
    } catch (err) {
      alert(`Error: ${err.response?.data?.detail || err.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: 'white',
        padding: '20px',
        borderRadius: '8px',
        maxWidth: '500px',
        width: '90%'
      }}>
        <h2 style={{ marginTop: 0 }}>Place Limit Order</h2>
        
        <div style={{ marginBottom: '15px' }}>
          <strong>Market:</strong> {market.title}
          {market.subtitle && <div style={{ color: '#666', fontSize: '14px' }}>{market.subtitle}</div>}
        </div>

        <div style={{ marginBottom: '15px', padding: '10px', background: '#f8f9fa', borderRadius: '4px', fontSize: '13px' }}>
          <div>Current Yes: Bid {market.yes_bid}¢ / Ask {market.yes_ask}¢</div>
          <div>Current No: Bid {market.no_bid}¢ / Ask {market.no_ask}¢</div>
        </div>

        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Side:</label>
          <div style={{ display: 'flex', gap: '10px' }}>
            <label style={{ cursor: 'pointer' }}>
              <input type="radio" value="yes" checked={side === 'yes'} onChange={(e) => handleSideChange(e.target.value)} />
              {' '}YES
            </label>
            <label style={{ cursor: 'pointer' }}>
              <input type="radio" value="no" checked={side === 'no'} onChange={(e) => handleSideChange(e.target.value)} />
              {' '}NO
            </label>
          </div>
        </div>

        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            Limit Price (¢):
          </label>
          <input
            type="number"
            value={price}
            onChange={(e) => setPrice(parseInt(e.target.value) || 0)}
            min="1"
            max="99"
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontSize: '14px'
            }}
          />
          <div style={{ fontSize: '12px', color: '#666', marginTop: '3px' }}>
            Default is current ask (instant fill likely). Lower = better price but may not fill.
          </div>
        </div>

        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Quantity:</label>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(parseInt(e.target.value) || 0)}
            min="1"
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontSize: '14px'
            }}
          />
        </div>

        <div style={{ marginBottom: '20px', padding: '10px', background: '#f8f9fa', borderRadius: '4px' }}>
          <div><strong>Limit price:</strong> {price}¢</div>
          <div><strong>Total cost (if filled):</strong> ${totalCost}</div>
          <div style={{ fontSize: '12px', color: '#666' }}>Est. fee: ${fee.toFixed(2)} (~{((fee / parseFloat(totalCost)) * 100).toFixed(2)}%)</div>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={handleTrade}
            disabled={loading}
            style={{
              flex: 1,
              padding: '10px',
              background: loading ? '#ccc' : '#28a745',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontWeight: 'bold'
            }}>
            {loading ? 'Placing Order...' : 'Place Limit Order'}
          </button>
          <button
            onClick={onClose}
            disabled={loading}
            style={{
              flex: 1,
              padding: '10px',
              background: '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

const CloseModal = ({ position, markets, onClose, onSuccess }) => {
  const market = markets.find(m => m.ticker === position.ticker)
  const side = position.position > 0 ? 'yes' : 'no'
  const absPosition = Math.abs(position.position)
  
  const [quantity, setQuantity] = useState(absPosition)
  const [price, setPrice] = useState(market ? (side === 'yes' ? market.yes_bid : market.no_bid) : 50)
  const [loading, setLoading] = useState(false)

  const totalProceeds = (quantity * price / 100).toFixed(2)

  const handleClose = async () => {
    if (quantity <= 0 || quantity > absPosition) {
      alert(`Quantity must be between 1 and ${absPosition}`)
      return
    }

    if (price < 1 || price > 99) {
      alert('Price must be between 1¢ and 99¢')
      return
    }

    if (!window.confirm(`Close position?\n\nSell ${quantity} ${side.toUpperCase()} @ ${price}¢\nProceeds: $${totalProceeds}`)) {
      return
    }

    setLoading(true)
    try {
      await axios.post(`${API}/close`, {
        ticker: position.ticker,
        side,
        quantity,
        price
      })
      alert('Close order placed successfully!')
      onSuccess()
      onClose()
    } catch (err) {
      alert(`Error: ${err.response?.data?.detail || err.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: 'white',
        padding: '20px',
        borderRadius: '8px',
        maxWidth: '500px',
        width: '90%'
      }}>
        <h2 style={{ marginTop: 0 }}>Close Position</h2>
        
        <div style={{ marginBottom: '15px' }}>
          <strong>Ticker:</strong> {position.ticker}
          <div style={{ color: '#666', fontSize: '14px' }}>
            Position: {absPosition} {side.toUpperCase()} contracts
          </div>
        </div>

        {market && (
          <div style={{ marginBottom: '15px', padding: '10px', background: '#f8f9fa', borderRadius: '4px', fontSize: '13px' }}>
            <div>Current Yes: Bid {market.yes_bid}¢ / Ask {market.yes_ask}¢</div>
            <div>Current No: Bid {market.no_bid}¢ / Ask {market.no_ask}¢</div>
          </div>
        )}

        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            Sell Price (¢):
          </label>
          <input
            type="number"
            value={price}
            onChange={(e) => setPrice(parseInt(e.target.value) || 0)}
            min="1"
            max="99"
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontSize: '14px'
            }}
          />
          <div style={{ fontSize: '12px', color: '#666', marginTop: '3px' }}>
            Default is current bid (instant fill likely). Higher = better price but may not fill.
          </div>
        </div>

        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            Quantity (max {absPosition}):
          </label>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(parseInt(e.target.value) || 0)}
            min="1"
            max={absPosition}
            style={{
              width: '100%',
              padding: '8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontSize: '14px'
            }}
          />
        </div>

        <div style={{ marginBottom: '20px', padding: '10px', background: '#f8f9fa', borderRadius: '4px' }}>
          <div><strong>Sell price:</strong> {price}¢</div>
          <div><strong>Proceeds (if filled):</strong> ${totalProceeds}</div>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={handleClose}
            disabled={loading}
            style={{
              flex: 1,
              padding: '10px',
              background: loading ? '#ccc' : '#dc3545',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontWeight: 'bold'
            }}>
            {loading ? 'Placing Order...' : 'Close Position'}
          </button>
          <button
            onClick={onClose}
            disabled={loading}
            style={{
              flex: 1,
              padding: '10px',
              background: '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
