import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import axios from 'axios'

const API = 'http://localhost:8000/api'

function App() {
  const [balance, setBalance] = useState(0)
  const [pnl, setPnl] = useState({ total_pnl: 0, trade_count: 0 })
  const [trades, setTrades] = useState([])
  const [params, setParams] = useState({
    min_probability: 0.90,
    max_time_to_close: 7,
    position_size: 100,
    kelly_fraction: 0.25
  })

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  const fetchData = async () => {
    try {
      const [balRes, pnlRes, tradesRes, paramsRes] = await Promise.all([
        axios.get(`${API}/balance`),
        axios.get(`${API}/pnl`),
        axios.get(`${API}/trades`),
        axios.get(`${API}/strategy/params`)
      ])
      setBalance(balRes.data.balance)
      setPnl(pnlRes.data)
      setTrades(tradesRes.data)
      setParams(paramsRes.data)
    } catch (err) {
      console.error(err)
    }
  }

  const updateParams = async () => {
    await axios.post(`${API}/strategy/params`, params)
  }

  const pnlData = trades.slice(0, 20).reverse().map((t, i) => ({
    name: i,
    pnl: t.pnl
  }))

  return (
    <div style={{ padding: '20px', fontFamily: 'system-ui' }}>
      <h1>Kalshi Trading Bot</h1>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginBottom: '30px' }}>
        <Card title="Balance" value={`$${balance.toFixed(2)}`} />
        <Card title="Total P&L" value={`$${pnl.total_pnl.toFixed(2)}`} color={pnl.total_pnl >= 0 ? 'green' : 'red'} />
        <Card title="Trades" value={pnl.trade_count} />
      </div>

      <div style={{ marginBottom: '30px', background: '#f5f5f5', padding: '20px', borderRadius: '8px' }}>
        <h2>Strategy Parameters</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '15px' }}>
          <Input label="Min Probability" value={params.min_probability} 
                 onChange={(v) => setParams({...params, min_probability: v})} />
          <Input label="Max Days to Close" value={params.max_time_to_close} 
                 onChange={(v) => setParams({...params, max_time_to_close: v})} />
          <Input label="Position Size ($)" value={params.position_size} 
                 onChange={(v) => setParams({...params, position_size: v})} />
          <Input label="Kelly Fraction" value={params.kelly_fraction} 
                 onChange={(v) => setParams({...params, kelly_fraction: v})} />
        </div>
        <button onClick={updateParams} style={{ marginTop: '15px', padding: '10px 20px', 
                background: '#007bff', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
          Update Parameters
        </button>
      </div>

      <div style={{ marginBottom: '30px' }}>
        <h2>P&L Chart</h2>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={pnlData}>
            <XAxis dataKey="name" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="pnl" stroke="#007bff" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div>
        <h2>Recent Trades</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f5f5f5', textAlign: 'left' }}>
              <th style={{ padding: '10px' }}>Ticker</th>
              <th>Size</th>
              <th>Price</th>
              <th>P&L</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {trades.map(t => (
              <tr key={t.id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={{ padding: '10px' }}>{t.ticker}</td>
                <td>{t.size}</td>
                <td>{(t.price * 100).toFixed(0)}¢</td>
                <td style={{ color: t.pnl >= 0 ? 'green' : 'red' }}>${t.pnl.toFixed(2)}</td>
                <td>{new Date(t.timestamp).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const Card = ({ title, value, color = 'black' }) => (
  <div style={{ padding: '20px', background: 'white', border: '1px solid #ddd', borderRadius: '8px' }}>
    <div style={{ fontSize: '14px', color: '#666', marginBottom: '8px' }}>{title}</div>
    <div style={{ fontSize: '28px', fontWeight: 'bold', color }}>{value}</div>
  </div>
)

const Input = ({ label, value, onChange }) => (
  <div>
    <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>{label}</label>
    <input type="number" step="0.01" value={value} 
           onChange={(e) => onChange(parseFloat(e.target.value))}
           style={{ width: '100%', padding: '8px', border: '1px solid #ddd', borderRadius: '4px' }} />
  </div>
)

export default App
