from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()
engine = create_engine('sqlite:///trading.db')
Session = sessionmaker(bind=engine)

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    ticker = Column(String)
    side = Column(String)
    size = Column(Integer)
    price = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    pnl = Column(Float, default=0.0)

Base.metadata.create_all(engine)

class Database:
    def __init__(self):
        self.session = Session()
    
    def save_trade(self, opp: dict, order):
        trade = Trade(
            ticker=opp["ticker"],
            side="yes",
            size=opp["size"],
            price=opp["prob"]
        )
        self.session.add(trade)
        self.session.commit()
    
    def get_trades(self):
        trades = self.session.query(Trade).order_by(Trade.timestamp.desc()).limit(50).all()
        return [{"id": t.id, "ticker": t.ticker, "size": t.size, 
                 "price": t.price, "pnl": t.pnl, "timestamp": t.timestamp.isoformat()} 
                for t in trades]
    
    def get_positions(self):
        return self.session.query(Trade).filter(Trade.pnl == 0).all()
    
    def get_pnl_summary(self):
        trades = self.session.query(Trade).all()
        total_pnl = sum(t.pnl for t in trades)
        return {"total_pnl": total_pnl, "trade_count": len(trades)}
