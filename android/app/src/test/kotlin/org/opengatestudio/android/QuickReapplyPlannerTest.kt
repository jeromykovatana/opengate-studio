package org.opengatestudio.android

import org.junit.Assert.assertEquals
import org.junit.Test

class QuickReapplyPlannerTest {
    @Test
    fun unverifiedPinsAlwaysBlock() {
        val liveStock = SessionSnapshot(
            ok = true,
            bodyId = "zve1_202",
            kind = "preflight",
            mode = "live_usb",
            ready = true,
            verified = true,
            state = "stock"
        )
        assertEquals(
            QuickReapplyDecision.BlockedPinsUnverified,
            QuickReapplyPlanner.plan(
                pinsVerified = false,
                selectedBodyId = "zve1_202",
                latestSession = liveStock,
                resultSource = "android_usb"
            )
        )
    }

    @Test
    fun mockReadyNeverUnlocksLiveApply() {
        val mockStock = SessionSnapshot(
            ok = true,
            bodyId = "zve1_202",
            kind = "preflight",
            mode = "mock",
            ready = true,
            verified = true,
            state = "stock"
        )
        assertEquals(
            QuickReapplyDecision.RunPreflightThenSafeDailyApply,
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "zve1_202",
                offlineMockCamera = false,
                preflightResult = mockStock,
                latestSession = mockStock,
                resultSource = "mock"
            )
        )
    }

    @Test
    fun liveStockPreflightUnlocksSafeDailyApply() {
        val liveStock = SessionSnapshot(
            ok = true,
            bodyId = "fx3_702",
            kind = "preflight",
            mode = "live_usb",
            ready = true,
            verified = true,
            state = "stock"
        )
        assertEquals(
            QuickReapplyDecision.ReadyForSafeDailyApply(listOf("mp4_3x2", "screen_3x2")),
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "fx3_702",
                offlineMockCamera = false,
                preflightResult = liveStock,
                latestSession = liveStock,
                resultSource = "android_usb"
            )
        )
    }

    @Test
    fun leftBehindOrUnverifiedForcesRecoveryPreflight() {
        assertEquals(
            QuickReapplyDecision.RunRecoveryPreflightFirst,
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "a7s3_501",
                leftBehindWarning = true
            )
        )
    }
}
