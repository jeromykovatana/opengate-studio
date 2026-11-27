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
    fun offlineMockToggleNeverUnlocksApplyEvenWithPriorLiveSession() {
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
            QuickReapplyDecision.RunPreflightThenSafeDailyApply,
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "zve1_202",
                offlineMockCamera = true,
                preflightResult = liveStock,
                latestSession = liveStock,
                resultSource = "android_usb"
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
    fun liveAppliedSessionReportsAlreadyApplied() {
        val liveApplied = SessionSnapshot(
            ok = true,
            bodyId = "zve1_202",
            kind = "closing_dump",
            mode = "live_usb",
            ready = true,
            verified = true,
            state = "applied"
        )
        assertEquals(
            QuickReapplyDecision.AlreadyApplied,
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "zve1_202",
                offlineMockCamera = false,
                latestSession = liveApplied,
                resultSource = "android_usb"
            )
        )
    }

    @Test
    fun unverifiedPutbackForcesRecoveryPreflight() {
        val badPutback = SessionSnapshot(
            ok = false,
            bodyId = "a7s3_501",
            kind = "putback",
            mode = "live_usb",
            ready = false,
            verified = false,
            state = "stock_unverified"
        )
        assertEquals(
            QuickReapplyDecision.RunRecoveryPreflightFirst,
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "a7s3_501",
                latestSession = badPutback,
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
