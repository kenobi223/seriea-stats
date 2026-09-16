"""Modelli dati del dominio."""
from dataclasses import dataclass, field


@dataclass
class OddsPick:
    source: str
    market: str
    pick: str
    odds: float
    updated: int = 0

    def to_dict(self):
        return {"source": self.source, "market": self.market,
                "pick": self.pick, "odds": self.odds, "updated": self.updated}


@dataclass
class Fixture:
    id: int
    home: str
    away: str
    home_id: int
    away_id: int
    start_ts: int
    round: int
    venue: str = ""
    status: str = "NOT_STARTED"
    odds: list = field(default_factory=list)          # list[OddsPick] correnti
    history: list = field(default_factory=list)       # list[snapshot]; ogni snapshot = list[OddsPick]
    predictions: dict = field(default_factory=dict)
    morale: dict = field(default_factory=dict)
    h2h: list = field(default_factory=list)           # resultati testa a testa
    form_home: list = field(default_factory=list)     # list[dict]
    form_away: list = field(default_factory=list)
    value_flags: list = field(default_factory=list)
    coach: dict = field(default_factory=dict)   # {"home": {...}, "away": {...}}

    @property
    def key(self):
        return f"{self.home}-{self.away}"

    def to_dict(self):
        return {
            "id": self.id, "home": self.home, "away": self.away,
            "home_id": self.home_id, "away_id": self.away_id,
            "start_ts": self.start_ts, "round": self.round,
            "venue": self.venue, "status": self.status,
            "odds": [o.to_dict() for o in self.odds],
            "history": [[o.to_dict() for o in snap] for snap in self.history],
            "predictions": self.predictions,
            "morale": self.morale,
            "h2h": self.h2h,
            "form_home": self.form_home, "form_away": self.form_away,
            "value_flags": self.value_flags,
            "coach": self.coach,
        }


@dataclass
class OddsMove:
    """Rilevazione disallineamento o movimento quote."""
    fixture: str
    market: str
    pick: str
    values: dict          # source -> odds
    kind: str             # 'spread' | 'move' | 'arb' | 'lineup'
    message: str
    severity: str         # 'info' | 'warn' | 'alert'

    def to_dict(self):
        return {"fixture": self.fixture, "market": self.market, "pick": self.pick,
                "values": self.values, "kind": self.kind, "message": self.message,
                "severity": self.severity}