package org.opengatestudio.android

/** Deterministic planner for Safe Daily 3:2 field re-apply after a battery swap. */
sealed class QuickReapplyDecision {
    data object BlockedPinsUnverified : QuickReapplyDecision()
    data object RunRecoveryPreflightFirst : QuickReapplyDecision()
    data object RunPreflightThenSafeDailyApply : QuickReapplyDecision()
    data class ReadyForSafeDailyApply(val packs: List<String>) : QuickReapplyDecision()
    data object AlreadyApplied : QuickReapplyDecision()
}

data class SessionSnapshot(
    val ok: Boolean,
    val found: Boolean = true,
    val bodyId: String? = null,
    val kind: String? = null,
    val mode: String? = null,
    val ready: Boolean = false,
    val verified: Boolean? = null,
    val state: String = "unknown"
)

object QuickReapplyPlanner {
    val safeDailyPacks: List<String> = listOf("mp4_3x2", "screen_3x2")
    private val unverifiedStates = setOf(
        "not_ready",
        "unverified",
        "applied_unverified",
        "stock_unverified"
    )

    private fun matchesSelectedBody(selectedBodyId: String?, candidateBodyId: String?): Boolean {
        if (selectedBodyId.isNullOrEmpty() || candidateBodyId.isNullOrEmpty()) return true
        return selectedBodyId == candidateBodyId
    }

    fun plan(
        pinsVerified: Boolean,
        selectedBodyId: String? = null,
        offlineMockCamera: Boolean = false,
        leftBehindWarning: Boolean = false,
        hasInterruptedSession: Boolean = false,
        preflightResult: SessionSnapshot? = null,
        applyResult: SessionSnapshot? = null,
        putbackResult: SessionSnapshot? = null,
        latestSession: SessionSnapshot? = null,
        resultSource: String? = null
    ): QuickReapplyDecision {
        if (!pinsVerified) {
            return QuickReapplyDecision.BlockedPinsUnverified
        }
        if (leftBehindWarning || hasInterruptedSession) {
            return QuickReapplyDecision.RunRecoveryPreflightFirst
        }

        val liveSession = latestSession?.takeIf {
            it.found && it.mode == "live_usb" && matchesSelectedBody(selectedBodyId, it.bodyId)
        }

        if (liveSession != null) {
            if (!liveSession.ok || !liveSession.ready || liveSession.verified == false || liveSession.state in unverifiedStates) {
                return QuickReapplyDecision.RunRecoveryPreflightFirst
            }
            if (liveSession.kind == "putback" && liveSession.state != "stock") {
                return QuickReapplyDecision.RunRecoveryPreflightFirst
            }
        }

        val isMockOrigin = offlineMockCamera || resultSource == "mock" || latestSession?.mode == "mock"

        if (!isMockOrigin) {
            if (preflightResult != null && matchesSelectedBody(selectedBodyId, preflightResult.bodyId)) {
                if (!preflightResult.ok || !preflightResult.ready || preflightResult.state in unverifiedStates) {
                    return QuickReapplyDecision.RunRecoveryPreflightFirst
                }
            }
            if (putbackResult != null && matchesSelectedBody(selectedBodyId, putbackResult.bodyId)) {
                if (!putbackResult.ok || putbackResult.state != "stock") {
                    return QuickReapplyDecision.RunRecoveryPreflightFirst
                }
            }
            if (applyResult != null && matchesSelectedBody(selectedBodyId, applyResult.bodyId)) {
                if (!applyResult.ok) {
                    return QuickReapplyDecision.RunRecoveryPreflightFirst
                }
            }
        }

        if (isMockOrigin) {
            return QuickReapplyDecision.RunPreflightThenSafeDailyApply
        }

        val hasLiveSource = resultSource in setOf("live_usb", "android_usb", "liveInApp", "liveTerminal")

        if (liveSession != null) {
            if (liveSession.state == "applied" && liveSession.ok && liveSession.ready && liveSession.verified != false) {
                return QuickReapplyDecision.AlreadyApplied
            }
            val isPreflightKind = liveSession.kind == "preflight" || liveSession.kind == "dump"
            if (isPreflightKind && liveSession.ok && liveSession.ready && liveSession.verified != false && liveSession.state == "stock") {
                if (preflightResult != null && matchesSelectedBody(selectedBodyId, preflightResult.bodyId)) {
                    if (!preflightResult.ok || !preflightResult.ready || preflightResult.state != "stock") {
                        return QuickReapplyDecision.RunPreflightThenSafeDailyApply
                    }
                }
                return QuickReapplyDecision.ReadyForSafeDailyApply(safeDailyPacks)
            }
            return QuickReapplyDecision.RunPreflightThenSafeDailyApply
        }

        if (hasLiveSource) {
            if (applyResult != null && matchesSelectedBody(selectedBodyId, applyResult.bodyId) && applyResult.ok) {
                return QuickReapplyDecision.AlreadyApplied
            }
            if (preflightResult != null && matchesSelectedBody(selectedBodyId, preflightResult.bodyId) && preflightResult.ok && preflightResult.ready) {
                if (preflightResult.state == "applied") return QuickReapplyDecision.AlreadyApplied
                if (preflightResult.state == "stock" && putbackResult == null) {
                    return QuickReapplyDecision.ReadyForSafeDailyApply(safeDailyPacks)
                }
            }
        }

        return QuickReapplyDecision.RunPreflightThenSafeDailyApply
    }
}
