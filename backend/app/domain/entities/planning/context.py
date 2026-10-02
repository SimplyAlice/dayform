from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class PlanningContext:
    plan_id: UUID
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    group_size: int = 1
    transport_mode: str | None = None
    origin: str | None = None

    def __post_init__(self) -> None:
        if self.group_size < 1:
            raise ValueError("Group size must be at least 1.")

        if self.end_time and self.start_time and self.end_time < self.start_time:
            raise ValueError("End time cannot be before start time.")
