"""Enterprise sales lead model — captures Talk-to-Sales form submissions."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime
from . import Base


class EnterpriseLead(Base):
    """A lead captured from the Enterprise pricing tier or contact-sales modal.

    Used for: BPOs, call centers, large e-commerce sellers, Fortune 500 prospects.
    Volume is low (a few per week) but each lead is high-value.
    """
    __tablename__ = 'enterprise_leads'

    lead_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Required fields from the form
    name = Column(String(200), nullable=False)
    email = Column(String(320), nullable=False, index=True)
    company = Column(String(200), nullable=False)

    # Optional but useful for qualification
    job_title = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    country = Column(String(100), nullable=True)
    num_agents = Column(Integer, nullable=True)  # # of agents/seats they need
    use_case = Column(Text, nullable=True)       # free-text description
    source_plan = Column(String(50), nullable=True)  # which pricing tier triggered the form

    # Status tracking (for sales team)
    status = Column(String(30), default='new', index=True)  # new, contacted, qualified, won, lost
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'lead_id': self.lead_id,
            'name': self.name,
            'email': self.email,
            'company': self.company,
            'job_title': self.job_title,
            'phone': self.phone,
            'country': self.country,
            'num_agents': self.num_agents,
            'use_case': self.use_case,
            'source_plan': self.source_plan,
            'status': self.status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
