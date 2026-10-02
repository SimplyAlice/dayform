from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.planning.ports import PlanRepository
from app.domain.entities.planning.constraint import Constraint
from app.domain.entities.planning.context import PlanningContext
from app.domain.entities.planning.plan import Plan, PlanStatus
from app.domain.entities.planning.plan_item import PlanItem
from app.infrastructure.db.models.constraint import ConstraintModel
from app.infrastructure.db.models.plan import PlanModel
from app.infrastructure.db.models.plan_item import PlanItemModel
from app.infrastructure.db.models.planning_context import PlanningContextModel


class SqlAlchemyPlanRepository(PlanRepository):
    """SQLAlchemy adapter for the complete planning aggregate."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, plan: Plan) -> Plan:
        row = _plan_to_model(plan)
        self._session.add(row)
        await self._session.flush()
        return _to_plan(row)

    async def get(self, plan_id: UUID, user_id: UUID) -> Plan | None:
        row = await self._get_row(plan_id, user_id)
        return _to_plan(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> list[Plan]:
        result = await self._session.execute(
            select(PlanModel).where(PlanModel.user_id == user_id).options(*_aggregate_load_options()).execution_options(populate_existing=True)
            .order_by(PlanModel.updated_at.desc(), PlanModel.id.desc())
        )
        return [_to_plan(row) for row in result.scalars().unique().all()]

    async def update(self, plan: Plan) -> Plan:
        row = await self._get_row(plan.id, plan.user_id)
        if row is None:
            raise ValueError("Cannot update a plan that is not persisted.")
        row.intention, row.title, row.status = plan.intention, plan.title, plan.status.value
        if plan.context is None:
            row.context = None
        elif row.context is None:
            row.context = _context_to_model(plan.context)
        else:
            row.context.location = plan.context.location
            row.context.start_time = plan.context.start_time
            row.context.end_time = plan.context.end_time
            row.context.group_size = plan.context.group_size
            row.context.transport_mode = plan.context.transport_mode
            row.context.origin = plan.context.origin
        row.constraints = [_constraint_to_model(item) for item in plan.constraints]
        await self._session.flush()
        await self._session.refresh(row, attribute_names=["context", "constraints", "items", "updated_at"])
        return _to_plan(row)

    async def delete(self, plan_id: UUID, user_id: UUID) -> bool:
        result = await self._session.execute(delete(PlanModel).where(PlanModel.id == plan_id, PlanModel.user_id == user_id))
        await self._session.flush()
        return result.rowcount == 1

    async def create_item(self, user_id: UUID, plan_id: UUID, item: PlanItem) -> PlanItem | None:
        if await self._get_row(plan_id, user_id) is None:
            return None
        position = item.position
        if position == 0:
            maximum = await self._session.scalar(select(func.max(PlanItemModel.position)).where(PlanItemModel.plan_id == plan_id))
            position = maximum + 1 if maximum is not None else 0
        row = _item_to_model(item, position=position)
        self._session.add(row)
        await self._session.flush()
        return _to_item(row)

    async def get_item(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> PlanItem | None:
        row = await self._get_item_row(user_id, plan_id, item_id)
        return _to_item(row) if row is not None else None

    async def list_items(self, user_id: UUID, plan_id: UUID) -> list[PlanItem] | None:
        if await self._get_row(plan_id, user_id) is None:
            return None
        result = await self._session.execute(
            select(PlanItemModel).where(PlanItemModel.plan_id == plan_id).order_by(PlanItemModel.position, PlanItemModel.id)
        )
        return [_to_item(row) for row in result.scalars().all()]

    async def update_item(self, user_id: UUID, plan_id: UUID, item: PlanItem) -> PlanItem | None:
        row = await self._get_item_row(user_id, plan_id, item.id)
        if row is None:
            return None
        row.name, row.item_type, row.description = item.name, item.item_type, item.description
        row.start_time, row.end_time = item.start_time, item.end_time
        row.estimated_cost, row.location, row.position = item.estimated_cost, item.location, item.position
        row.status = item.status.value if hasattr(item.status, "value") else str(item.status)
        await self._session.flush()
        return _to_item(row)

    async def delete_item(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> bool:
        row = await self._get_item_row(user_id, plan_id, item_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def _get_row(self, plan_id: UUID, user_id: UUID) -> PlanModel | None:
        result = await self._session.execute(
            select(PlanModel).where(PlanModel.id == plan_id, PlanModel.user_id == user_id).options(*_aggregate_load_options()).execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def _get_item_row(self, user_id: UUID, plan_id: UUID, item_id: UUID) -> PlanItemModel | None:
        result = await self._session.execute(
            select(PlanItemModel).join(PlanModel).where(
                PlanItemModel.id == item_id, PlanItemModel.plan_id == plan_id, PlanModel.user_id == user_id
            )
        )
        return result.scalar_one_or_none()


def _aggregate_load_options() -> tuple[Any, Any, Any]:
    return (selectinload(PlanModel.context), selectinload(PlanModel.constraints), selectinload(PlanModel.items))


def _plan_to_model(plan: Plan) -> PlanModel:
    row = PlanModel(id=plan.id, user_id=plan.user_id, intention=plan.intention, title=plan.title, status=plan.status.value)
    row.context = _context_to_model(plan.context) if plan.context is not None else None
    row.constraints = [_constraint_to_model(item) for item in plan.constraints]
    row.items = [_item_to_model(item) for item in plan.items]
    return row


def _context_to_model(context: PlanningContext) -> PlanningContextModel:
    return PlanningContextModel(plan_id=context.plan_id, location=context.location, start_time=context.start_time,
                                end_time=context.end_time, group_size=context.group_size, transport_mode=context.transport_mode,
                                origin=context.origin)


def _constraint_to_model(item: Constraint) -> ConstraintModel:
    return ConstraintModel(id=item.id, plan_id=item.plan_id, type=item.type, value=item.value, numeric_value=item.numeric_value)


def _item_to_model(item: PlanItem, position: int | None = None) -> PlanItemModel:
    return PlanItemModel(
        id=item.id,
        plan_id=item.plan_id,
        name=item.name,
        item_type=item.item_type,
        description=item.description,
        start_time=item.start_time,
        end_time=item.end_time,
        estimated_cost=item.estimated_cost,
        location=item.location,
        position=item.position if position is None else position,
        status=item.status.value if hasattr(item.status, "value") else str(item.status),
    )


def _to_plan(row: PlanModel) -> Plan:
    context = None if row.context is None else PlanningContext(
        plan_id=row.id, location=row.context.location, start_time=row.context.start_time, end_time=row.context.end_time,
        group_size=row.context.group_size, transport_mode=row.context.transport_mode,
        origin=row.context.origin,
    )
    return Plan(id=row.id, user_id=row.user_id, intention=row.intention, title=row.title, status=PlanStatus(row.status),
                created_at=row.created_at, updated_at=row.updated_at, context=context,
                constraints=[Constraint(id=item.id, plan_id=row.id, type=item.type, value=item.value,
                                        numeric_value=item.numeric_value) for item in row.constraints],
                items=[_to_item(item) for item in sorted(row.items, key=lambda value: (value.position, str(value.id)))])


def _to_item(row: PlanItemModel) -> PlanItem:
    return PlanItem(
        id=row.id,
        plan_id=row.plan_id,
        name=row.name,
        item_type=row.item_type,
        description=row.description,
        start_time=row.start_time,
        end_time=row.end_time,
        estimated_cost=row.estimated_cost,
        location=row.location,
        position=row.position,
        status=row.status,
    )
