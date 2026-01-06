import { useState, useEffect } from 'react'
import axios from 'axios'

const API = 'http://localhost:8000/api'

function App() {
  const [balance, setBalance] = useState(0)
  const [markets, setMarkets] = useState([])
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(false)

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

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0)

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
        <Card title="P&L" value={`$${totalPnl.toFixed(2)}`} color={totalPnl >= 0 ? 'green' : 'red'} />
        <Card title="Positions" value={positions.length} />
        <Card title="Markets" value={markets.length} />
      </div>

      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '8px' }}>Markets ({markets.length})</h2>
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
                <th style={{ minWidth: '70px' }}>Category</th>
                <th>Yes Bid</th>
                <th>Yes Ask</th>
                <th>No Bid</th>
                <th>No Ask</th>
                <th>Volume</th>
                <th>Open Int.</th>
                <th>Time Left</th>
              </tr>
            </thead>
            <tbody>
              {markets.map(m => {
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
                    <td style={{ color: '#666' }}>{m.category}</td>
                    <td style={{ fontWeight: 'bold', color: '#28a745' }}>{m.yes_bid}¢</td>
                    <td style={{ fontWeight: 'bold', color: '#007bff' }}>{m.yes_ask}¢</td>
                    <td style={{ fontWeight: 'bold', color: '#28a745' }}>{m.no_bid}¢</td>
                    <td style={{ fontWeight: 'bold', color: '#007bff' }}>{m.no_ask}¢</td>
                    <td>{m.volume.toLocaleString()}</td>
                    <td>{m.open_interest.toLocaleString()}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{timeStr}</td>
                  </tr>
                )
              })}
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
                <th>Side</th>
                <th>Quantity</th>
                <th>Avg Price</th>
                <th>Current Price</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 ? (
                <tr>
                  <td colSpan="6" style={{ padding: '20px', textAlign: 'center', color: '#999' }}>
                    No open positions
                  </td>
                </tr>
              ) : (
                positions.map((p, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                    <td style={{ padding: '8px', fontFamily: 'monospace' }}>{p.ticker}</td>
                    <td style={{ textTransform: 'uppercase', fontWeight: 'bold' }}>{p.side}</td>
                    <td>{p.quantity}</td>
                    <td>{(p.avg_price * 100).toFixed(0)}¢</td>
                    <td>{(p.current_price * 100).toFixed(0)}¢</td>
                    <td style={{ color: p.pnl >= 0 ? 'green' : 'red', fontWeight: 'bold' }}>
                      ${p.pnl.toFixed(2)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

const Card = ({ title, value, color = 'black' }) => (
  <div style={{ padding: '12px', background: 'white', border: '1px solid #ddd', borderRadius: '4px' }}>
    <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>{title}</div>
    <div style={{ fontSize: '20px', fontWeight: 'bold', color }}>{value}</div>
  </div>
)

export default App
