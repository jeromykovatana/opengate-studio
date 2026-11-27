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

data class UsbAutoDetect(
    val bodyId: String?,
    val productName: String?,
    val isFx3aBlocked: Boolean,
    val warning: String?
)

object QuickReapplyPlanner {
    val safeDailyPacks: List<String> = listOf("mp4_3x2", "screen_3x2")
    val cinemaFullPacks: List<String> = listOf("mp4_3x2", "screen_3x2", "hdmi32", "high_bitrate", "xavc_si")
    private const val FX3A_WARNING = "ILME-FX3A is not supported by FX3 7.02 kits"
    private val unverifiedStates = setOf(
        "not_ready",
        "unverified",
        "applied_unverified",
        "stock_unverified"
    )

    fun detectCameraFromUsbDevices(devices: List<Map<String, Any>>): UsbAutoDetect {
        var firstProductName: String? = null
        var detectedBodyId: String? = null
        var detectedProductName: String? = null

        for (dev in devices) {
            val rawName = (dev["productName"] as? String)?.trim().orEmpty()
            if (rawName.isEmpty()) continue
            if (firstProductName == null) firstProductName = rawName

            val upper = rawName.uppercase()
            // Check ILME-FX3A / FX3A before ILME-FX3 so FX3A is never misclassified as FX3.
            if (upper.contains("ILME-FX3A") || upper.contains("FX3A")) {
                return UsbAutoDetect(
                    bodyId = null,
                    productName = rawName,
                    isFx3aBlocked = true,
                    warning = FX3A_WARNING
                )
            }
            if (detectedBodyId == null) {
                val matchedBody = when {
                    upper.contains("ZV-E1") -> "zve1_202"
                    upper.contains("ILCE-7SM3") -> "a7s3_501"
                    upper.contains("ILME-FX3") -> "fx3_702"
                    else -> null
                }
                if (matchedBody != null) {
                    detectedBodyId = matchedBody
                    detectedProductName = rawName
                }
            }
        }

        return UsbAutoDetect(
            bodyId = detectedBodyId,
            productName = detectedProductName ?: firstProductName,
            isFx3aBlocked = false,
            warning = null
        )
    }

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
            if ((liveSession.kind == "closing_dump" || liveSession.kind == "express_apply") && liveSession.state != "applied") {
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
            if (
                liveSession.state == "applied" &&
                liveSession.ok &&
                liveSession.ready &&
                liveSession.verified != false &&
                liveSession.kind in setOf("closing_dump", "express_apply", "preflight", "dump")
            ) {
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
