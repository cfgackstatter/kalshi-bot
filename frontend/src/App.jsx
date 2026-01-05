import { useState, useEffect } from 'react'
import axios from 'axios'

const API = 'http://localhost:8000/api'

function App() {
  const [balance, setBalance] = useState(0)
  const [markets, setMarkets] = useState([])
  const [positions, setPositions] = useState([])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [])

  const fetchData = async () => {
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
    }
  }

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0)

  return (
    <div style={{ padding: '20px', fontFamily: 'system-ui', maxWidth: '1200px', margin: '0 auto' }}>
      <h1>Kalshi Viewer</h1>

      {/* Summary */}
      <div style={{ display: 'flex', gap: '20px', marginBottom: '30px' }}>
        <Card title="Balance" value={`$${balance.toFixed(2)}`} />
        <Card
          title="Total P&L"
          value={`$${totalPnl.toFixed(2)}`}
          color={totalPnl >= 0 ? 'green' : 'red'}
        />
        <Card title="Positions" value={positions.length} />
        <Card title="Markets (shown)" value={markets.length} />
      </div>

      {/* Markets (first 10) */}
      <div style={{ marginBottom: '30px' }}>
        <h2>Markets (first {markets.length})</h2>
        <div style={{ maxHeight: '400px', overflowY: 'auto', border: '1px solid #ddd', borderRadius: '4px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: '#333', color: 'white', textAlign: 'left' }}>
                <th style={{ padding: '8px' }}>Ticker</th>
                <th>Title</th>
                <th>Yes Bid</th>
                <th>Yes Ask</th>
                <th>Days Left</th>
              </tr>
            </thead>
            <tbody>
              {markets.map(m => (
                <tr key={m.ticker} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: '8px', fontFamily: 'monospace', fontSize: '11px' }}>
                    {m.ticker}
                  </td>
                  <td style={{ maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {m.title}
                  </td>
                  <td>{m.yes_bid}¢</td>
                  <td>{m.yes_ask}¢</td>
                  <td>{m.days_left}d</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Positions */}
      <div>
        <h2>Open Positions ({positions.length})</h2>
        <div style={{ maxHeight: '300px', overflowY: 'auto', border: '1px solid #ddd', borderRadius: '4px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: '#333', color: 'white', textAlign: 'left' }}>
                <th style={{ padding: '8px' }}>Ticker</th>
                <th>Side</th>
                <th>Quantity</th>
                <th>Avg Price</th>
                <th>Current Price</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: '8px', fontFamily: 'monospace', fontSize: '11px' }}>
                    {p.ticker}
                  </td>
                  <td style={{ textTransform: 'uppercase' }}>{p.side}</td>
                  <td>{p.quantity}</td>
                  <td>{(p.avg_price * 100).toFixed(0)}¢</td>
                  <td>{(p.current_price * 100).toFixed(0)}¢</td>
                  <td style={{ color: p.pnl >= 0 ? 'green' : 'red', fontWeight: 'bold' }}>
                    ${p.pnl.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

const Card = ({ title, value, color = 'black' }) => (
  <div style={{ padding: '16px', background: 'white', border: '1px solid #ddd', borderRadius: '8px', flex: 1 }}>
    <div style={{ fontSize: '14px', color: '#666', marginBottom: '6px' }}>{title}</div>
    <div style={{ fontSize: '24px', fontWeight: 'bold', color }}>{value}</div>
  </div>
)

export default App
