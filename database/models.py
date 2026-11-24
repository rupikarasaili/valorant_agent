from datetime import datetime, timezone
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = "sqlite:///valorant_scout.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MatchModel(Base):
    __tablename__ = "matches"

    match_id = Column(String, primary_key=True, index=True)
    map_name = Column(String, nullable=False)
    status = Column(String, default="Pending Review", nullable=False)
    pipeline_stage = Column(String, default="ingested", nullable=False)
    handoff_note = Column(Text, nullable=True)
    coach_review = Column(Text, nullable=True)
    final_brief = Column(Text, nullable=True)

    rounds = relationship(
        "RoundModel", back_populates="match", cascade="all, delete-orphan"
    )
    findings = relationship(
        "TacticalFindingModel", back_populates="match", cascade="all, delete-orphan"
    )
    memories = relationship(
        "CoachMemoryModel", back_populates="match", cascade="all, delete-orphan"
    )
    access_logs = relationship(
        "AccessLogModel", back_populates="match", cascade="all, delete-orphan"
    )


class RoundModel(Base):
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.match_id"), nullable=False, index=True)
    round_num = Column(Integer, nullable=False)
    team_spend = Column(Integer, nullable=False)
    enemy_spend = Column(Integer, nullable=False)
    won = Column(Boolean, nullable=False)
    site = Column(String, nullable=False)
    untraded_deaths = Column(Integer, nullable=False)
    blunder_flagged = Column(String, nullable=True)

    match = relationship("MatchModel", back_populates="rounds")


class TacticalFindingModel(Base):
    __tablename__ = "tactical_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.match_id"), nullable=False, index=True)
    author = Column(String, nullable=False)  # economy_analyst | spatial_analyst | head_coach
    kind = Column(String, nullable=False)    # economy | spatial | directive
    body = Column(Text, nullable=False)
    status = Column(String, default="active", nullable=False, index=True)  # active | corrected | superseded
    version = Column(Integer, default=1, nullable=False)
    corrects_id = Column(Integer, ForeignKey("tactical_findings.id"), nullable=True)
    visibility = Column(String, default="shared", nullable=False)  # shared | private
    owner = Column(String, nullable=True)  # team_alpha | team_bravo | None when shared
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    match = relationship("MatchModel", back_populates="findings")
    corrects = relationship(
        "TacticalFindingModel",
        remote_side=[id],
        uselist=False,
    )


class CoachMemoryModel(Base):
    __tablename__ = "coach_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.match_id"), nullable=True, index=True)
    seed_key = Column(String, unique=True, nullable=True)
    author = Column(String, nullable=False)
    kind = Column(String, default="protocol", nullable=False)  # protocol | directive | note
    body = Column(Text, nullable=False)
    status = Column(String, default="active", nullable=False, index=True)  # active | corrected | superseded
    version = Column(Integer, default=1, nullable=False)
    corrects_id = Column(Integer, ForeignKey("coach_memories.id"), nullable=True)
    visibility = Column(String, default="private", nullable=False)
    owner = Column(String, nullable=False, index=True)  # team_alpha | team_bravo
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    match = relationship("MatchModel", back_populates="memories")
    corrects = relationship(
        "CoachMemoryModel",
        remote_side=[id],
        uselist=False,
    )


class AccessLogModel(Base):
    __tablename__ = "access_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.match_id"), nullable=True, index=True)
    actor = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    target = Column(String, nullable=False)
    result = Column(String, nullable=False, index=True)  # allowed | denied
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    match = relationship("MatchModel", back_populates="access_logs")


def seed_default_memories(db) -> None:
    """Seed one private memory note each for Team Alpha and Team Bravo idempotently."""
    defaults = [
        {
            "seed_key": "seed_team_alpha_anti_eco",
            "match_id": None,
            "author": "coach_alpha",
            "kind": "protocol",
            "body": (
                "Team Alpha Anti-Eco Protocol: Group on one site with crossfires, "
                "avoid isolated long-range duels against SMGs/shotguns, and hold "
                "utility to punish low-buy rushes."
            ),
            "status": "active",
            "version": 1,
            "corrects_id": None,
            "visibility": "private",
            "owner": "team_alpha",
        },
        {
            "seed_key": "seed_team_bravo_haven_default",
            "match_id": None,
            "author": "coach_bravo",
            "kind": "protocol",
            "body": (
                "Team Bravo Haven Default: Contest A Lobby early for info, anchor C "
                "site with slow utility, and keep mid lurk flexible until 0:45 "
                "before committing to a fast split."
            ),
            "status": "active",
            "version": 1,
            "corrects_id": None,
            "visibility": "private",
            "owner": "team_bravo",
        },
    ]

    inserted = False
    for item in defaults:
        exists = (
            db.query(CoachMemoryModel)
            .filter(CoachMemoryModel.seed_key == item["seed_key"])
            .first()
        )
        if not exists:
            db.add(CoachMemoryModel(**item))
            inserted = True

    if inserted:
        db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_default_memories(db)
    finally:
        db.close()