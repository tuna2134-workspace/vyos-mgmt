"""Prefix-list management endpoints.

Prefix lists are the policy objects behind route-map prefix-list match
conditions and BGP prefix-list filters.  Reads are available to every
authenticated role; mutations require operator or admin.  Domain failures are
translated into the stable error codes from the API contract.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from vyos_mgmt.api.deps import (
    CurrentUser,
    OperatorUser,
    PrefixListServiceDep,
    RouterDep,
    SessionDep,
)
from vyos_mgmt.core.errors import AppError, conflict, not_found
from vyos_mgmt.db.models import Router, User
from vyos_mgmt.schemas.prefix_list import (
    PrefixListCreate,
    PrefixListFamily,
    PrefixListList,
    PrefixListRead,
    PrefixListRuleCreate,
    PrefixListRuleUpdate,
    PrefixListUpdate,
)
from vyos_mgmt.services.audit import record_audit
from vyos_mgmt.services.prefix_list_service import (
    PrefixListExistsError,
    PrefixListInUseError,
    PrefixListNotFoundError,
    PrefixListRuleDuplicateError,
    PrefixListRuleExistsError,
    PrefixListRuleNotFoundError,
    PrefixListValidationError,
)

router = APIRouter(prefix="/routers/{router_id}/prefix-lists", tags=["prefix-lists"])

RuleNumber = Annotated[int, Path(ge=1, le=65_535)]
FamilyPath = Annotated[PrefixListFamily, Path(description="Prefix-list family")]
FamilyFilter = Annotated[PrefixListFamily | None, Query(description="Filter by family")]


def _translate(exc: Exception) -> AppError:
    if isinstance(exc, PrefixListInUseError):
        return conflict("prefix_list_in_use", str(exc), details={"used_by": exc.used_by})
    if isinstance(exc, PrefixListRuleDuplicateError):
        return conflict("prefix_list_rule_duplicate", str(exc))
    if isinstance(exc, PrefixListRuleExistsError):
        return conflict("prefix_list_rule_exists", str(exc))
    if isinstance(exc, PrefixListExistsError):
        return conflict("prefix_list_exists", str(exc))
    if isinstance(exc, PrefixListRuleNotFoundError):
        return not_found("prefix_list_rule_not_found", str(exc))
    if isinstance(exc, PrefixListNotFoundError):
        return not_found("prefix_list_not_found", str(exc))
    if isinstance(exc, PrefixListValidationError):
        return AppError(
            422,
            "validation_error",
            "The request payload is invalid",
            details=[
                {
                    "loc": ["body", exc.field],
                    "msg": str(exc),
                    "type": "value_error",
                    "input": exc.value,
                }
            ],
        )
    raise exc


async def _audit(
    session: SessionDep,
    request: Request,
    actor: User,
    device: Router,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await record_audit(
        session,
        action=action,
        resource_type=resource_type,
        actor=actor,
        request=request,
        router=device,
        resource_id=resource_id,
        details=details,
    )


def _list_details(family: PrefixListFamily, name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "family": family, **extra}


def _rule_details(
    family: PrefixListFamily,
    name: str,
    number: int,
    payload: PrefixListRuleCreate | PrefixListRuleUpdate,
) -> dict[str, Any]:
    return {
        "name": name,
        "family": family,
        "number": number,
        **payload.model_dump(mode="json", exclude={"number"}),
    }


# ---------------------------------------------------------------------------
# Prefix lists
# ---------------------------------------------------------------------------


@router.get("", response_model=PrefixListList)
async def list_prefix_lists(
    service: PrefixListServiceDep,
    _current_user: CurrentUser,
    family: FamilyFilter = None,
) -> PrefixListList:
    return await service.list(family)


@router.post("", response_model=PrefixListRead, status_code=status.HTTP_201_CREATED)
async def create_prefix_list(
    payload: PrefixListCreate,
    request: Request,
    service: PrefixListServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> PrefixListRead:
    try:
        prefix_list = await service.create(payload)
    except PrefixListExistsError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="prefix_list.create",
        resource_type="prefix_list",
        resource_id=f"{payload.family}:{payload.name}",
        details=_list_details(payload.family, payload.name, description=payload.description),
    )
    return prefix_list


@router.get("/{family}/{name}", response_model=PrefixListRead)
async def get_prefix_list(
    family: FamilyPath,
    name: str,
    service: PrefixListServiceDep,
    _current_user: CurrentUser,
) -> PrefixListRead:
    try:
        return await service.get(family, name)
    except PrefixListNotFoundError as exc:
        raise _translate(exc) from exc


@router.put("/{family}/{name}", response_model=PrefixListRead)
async def update_prefix_list(
    family: FamilyPath,
    name: str,
    payload: PrefixListUpdate,
    request: Request,
    service: PrefixListServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> PrefixListRead:
    try:
        prefix_list = await service.update(family, name, payload)
    except PrefixListNotFoundError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="prefix_list.update",
        resource_type="prefix_list",
        resource_id=f"{family}:{name}",
        details=_list_details(family, name, description=payload.description),
    )
    return prefix_list


@router.delete("/{family}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prefix_list(
    family: FamilyPath,
    name: str,
    request: Request,
    service: PrefixListServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> Response:
    try:
        await service.delete(family, name)
    except (PrefixListNotFoundError, PrefixListInUseError) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="prefix_list.delete",
        resource_type="prefix_list",
        resource_id=f"{family}:{name}",
        details=_list_details(family, name),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@router.post("/{family}/{name}/rules", response_model=PrefixListRead)
async def create_prefix_list_rule(
    family: FamilyPath,
    name: str,
    payload: PrefixListRuleCreate,
    request: Request,
    service: PrefixListServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> PrefixListRead:
    try:
        prefix_list = await service.create_rule(family, name, payload)
    except (
        PrefixListNotFoundError,
        PrefixListRuleExistsError,
        PrefixListRuleDuplicateError,
        PrefixListValidationError,
    ) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="prefix_list.rule.create",
        resource_type="prefix_list_rule",
        resource_id=f"{family}:{name}:{payload.number}",
        details=_rule_details(family, name, payload.number, payload),
    )
    return prefix_list


@router.put("/{family}/{name}/rules/{number}", response_model=PrefixListRead)
async def update_prefix_list_rule(
    family: FamilyPath,
    name: str,
    number: RuleNumber,
    payload: PrefixListRuleUpdate,
    request: Request,
    service: PrefixListServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> PrefixListRead:
    try:
        prefix_list = await service.update_rule(family, name, number, payload)
    except (
        PrefixListNotFoundError,
        PrefixListRuleNotFoundError,
        PrefixListRuleDuplicateError,
        PrefixListValidationError,
    ) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="prefix_list.rule.update",
        resource_type="prefix_list_rule",
        resource_id=f"{family}:{name}:{number}",
        details=_rule_details(family, name, number, payload),
    )
    return prefix_list


@router.delete("/{family}/{name}/rules/{number}", response_model=PrefixListRead)
async def delete_prefix_list_rule(
    family: FamilyPath,
    name: str,
    number: RuleNumber,
    request: Request,
    service: PrefixListServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> PrefixListRead:
    try:
        prefix_list = await service.delete_rule(family, name, number)
    except (PrefixListNotFoundError, PrefixListRuleNotFoundError) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="prefix_list.rule.delete",
        resource_type="prefix_list_rule",
        resource_id=f"{family}:{name}:{number}",
        details=_list_details(family, name, number=number),
    )
    return prefix_list
