# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic Safe Daily 3:2 field re-apply planner (mirrors Swift QuickReapplyPlanner)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

SAFE_DAILY_PACKS: tuple[str, ...] = ("mp4_3x2", "screen_3x2")
_UNVERIFIED_STATES = frozenset({"not_ready", "unverified", "applied_unverified", "stock_unverified"})


class QuickReapplyDecision(str, Enum):
    BLOCKED_PINS_UNVERIFIED = "blocked_pins_unverified"
    RUN_RECOVERY_PREFLIGHT_FIRST = "run_recovery_preflight_first"
    RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY = "run_preflight_then_safe_daily_apply"
    READY_FOR_SAFE_DAILY_APPLY = "ready_for_safe_daily_apply"
    ALREADY_APPLIED = "already_applied"


@dataclass(frozen=True)
class QuickReapplyPlan:
    decision: QuickReapplyDecision
    packs: tuple[str, ...] = ()


def _matches_selected_body(selected_body_id: str | None, candidate_body_id: str | None) -> bool:
    if not selected_body_id:
        return True
    if not candidate_body_id:
        return True
    return candidate_body_id == selected_body_id


def plan_quick_reapply(
    *,
    pins_verified: bool,
    selected_body_id: str | None = None,
    offline_mock_camera: bool = False,
    left_behind_warning: bool = False,
    has_interrupted_session: bool = False,
    preflight_result: Mapping[str, Any] | None = None,
    apply_result: Mapping[str, Any] | None = None,
    putback_result: Mapping[str, Any] | None = None,
    latest_session: Mapping[str, Any] | None = None,
    result_source: str | None = None,
) -> QuickReapplyPlan:
    """Compute the deterministic Quick Field Re-Apply decision.

    Safety invariants:
    - Unverified SHA-256 pins always block live operations.
    - Interrupted, unverified, or left-behind states always force recovery preflight first.
    - Offline mock results NEVER unlock live apply or claim live applied state.
    """
    if not pins_verified:
        return QuickReapplyPlan(QuickReapplyDecision.BLOCKED_PINS_UNVERIFIED)

    if left_behind_warning or has_interrupted_session:
        return QuickReapplyPlan(QuickReapplyDecision.RUN_RECOVERY_PREFLIGHT_FIRST)

    live_session: Mapping[str, Any] | None = None
    if (
        latest_session is not None
        and bool(latest_session.get("found"))
        and latest_session.get("mode") == "live_usb"
        and _matches_selected_body(selected_body_id, latest_session.get("body_id"))
    ):
        live_session = latest_session

    if live_session is not None:
        ls_ok = bool(live_session.get("ok"))
        ls_ready = bool(live_session.get("ready"))
        ls_verified = live_session.get("verified")
        ls_state = str(live_session.get("state") or "")
        if not ls_ok or not ls_ready or ls_verified is False or ls_state in _UNVERIFIED_STATES:
            return QuickReapplyPlan(QuickReapplyDecision.RUN_RECOVERY_PREFLIGHT_FIRST)
        if live_session.get("kind") == "putback" and ls_state != "stock":
            return QuickReapplyPlan(QuickReapplyDecision.RUN_RECOVERY_PREFLIGHT_FIRST)

    is_mock_origin = (
        offline_mock_camera
        or result_source == "mock"
        or (latest_session is not None and latest_session.get("mode") == "mock")
    )

    if not is_mock_origin:
        if preflight_result is not None and _matches_selected_body(selected_body_id, preflight_result.get("body_id")):
            pre_state = str(preflight_result.get("state") or "")
            if not bool(preflight_result.get("ok")) or not bool(preflight_result.get("ready")) or pre_state in _UNVERIFIED_STATES:
                return QuickReapplyPlan(QuickReapplyDecision.RUN_RECOVERY_PREFLIGHT_FIRST)

        if putback_result is not None and _matches_selected_body(selected_body_id, putback_result.get("body_id")):
            if not bool(putback_result.get("ok")) or putback_result.get("state") != "stock":
                return QuickReapplyPlan(QuickReapplyDecision.RUN_RECOVERY_PREFLIGHT_FIRST)

        if apply_result is not None and _matches_selected_body(selected_body_id, apply_result.get("body_id")):
            if not bool(apply_result.get("ok")):
                return QuickReapplyPlan(QuickReapplyDecision.RUN_RECOVERY_PREFLIGHT_FIRST)

    if is_mock_origin:
        return QuickReapplyPlan(QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY)

    has_live_source = result_source in ("live_usb", "liveInApp", "liveTerminal", "android_usb")

    if live_session is not None:
        ls_ok = bool(live_session.get("ok"))
        ls_ready = bool(live_session.get("ready"))
        ls_verified = live_session.get("verified")
        ls_state = str(live_session.get("state") or "")
        ls_kind = str(live_session.get("kind") or "")

        if ls_state == "applied" and ls_ok and ls_ready and ls_verified is not False:
            return QuickReapplyPlan(QuickReapplyDecision.ALREADY_APPLIED)

        if ls_kind in ("preflight", "dump") and ls_ok and ls_ready and ls_verified is not False and ls_state == "stock":
            if preflight_result is not None and _matches_selected_body(selected_body_id, preflight_result.get("body_id")):
                if not (
                    bool(preflight_result.get("ok"))
                    and bool(preflight_result.get("ready"))
                    and preflight_result.get("state") == "stock"
                ):
                    return QuickReapplyPlan(QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY)
            return QuickReapplyPlan(QuickReapplyDecision.READY_FOR_SAFE_DAILY_APPLY, packs=SAFE_DAILY_PACKS)

        return QuickReapplyPlan(QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY)

    if has_live_source:
        if apply_result is not None and _matches_selected_body(selected_body_id, apply_result.get("body_id")) and bool(apply_result.get("ok")):
            return QuickReapplyPlan(QuickReapplyDecision.ALREADY_APPLIED)

        if (
            preflight_result is not None
            and _matches_selected_body(selected_body_id, preflight_result.get("body_id"))
            and bool(preflight_result.get("ok"))
            and bool(preflight_result.get("ready"))
        ):
            pre_state = str(preflight_result.get("state") or "")
            if pre_state == "applied":
                return QuickReapplyPlan(QuickReapplyDecision.ALREADY_APPLIED)
            if pre_state == "stock" and putback_result is None:
                return QuickReapplyPlan(QuickReapplyDecision.READY_FOR_SAFE_DAILY_APPLY, packs=SAFE_DAILY_PACKS)

    return QuickReapplyPlan(QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY)
