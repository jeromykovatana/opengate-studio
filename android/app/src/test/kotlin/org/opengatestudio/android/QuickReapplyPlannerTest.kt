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

    @Test
    fun expressApplyAppliedReportsAlreadyApplied() {
        val expressApplied = SessionSnapshot(
            ok = true,
            bodyId = "fx3_702",
            kind = "express_apply",
            mode = "live_usb",
            ready = true,
            verified = true,
            state = "applied"
        )
        assertEquals(
            QuickReapplyDecision.AlreadyApplied,
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "fx3_702",
                offlineMockCamera = false,
                latestSession = expressApplied,
                resultSource = "android_usb"
            )
        )
    }

    @Test
    fun expressApplyUnverifiedForcesRecoveryPreflight() {
        val expressUnverified = SessionSnapshot(
            ok = true,
            bodyId = "zve1_202",
            kind = "express_apply",
            mode = "live_usb",
            ready = true,
            verified = true,
            state = "stock"
        )
        assertEquals(
            QuickReapplyDecision.RunRecoveryPreflightFirst,
            QuickReapplyPlanner.plan(
                pinsVerified = true,
                selectedBodyId = "zve1_202",
                offlineMockCamera = false,
                latestSession = expressUnverified,
                resultSource = "android_usb"
            )
        )
    }

    @Test
    fun cinemaFullPacksContainAllFivePacks() {
        assertEquals(
            listOf("mp4_3x2", "screen_3x2", "hdmi32", "high_bitrate", "xavc_si"),
            QuickReapplyPlanner.cinemaFullPacks
        )
    }

    @Test
    fun detectCameraFromUsbDevicesMatchesBodiesAndBlocksFx3a() {
        val zve1 = QuickReapplyPlanner.detectCameraFromUsbDevices(
            listOf(mapOf("idProduct" to 0x0E00, "productName" to "ZV-E1"))
        )
        assertEquals("zve1_202", zve1.bodyId)
        assertEquals(false, zve1.isFx3aBlocked)
        assertEquals(null, zve1.warning)

        val a7s3 = QuickReapplyPlanner.detectCameraFromUsbDevices(
            listOf(mapOf("idProduct" to 0x0D00, "productName" to "ILCE-7SM3"))
        )
        assertEquals("a7s3_501", a7s3.bodyId)
        assertEquals(false, a7s3.isFx3aBlocked)

        val fx3 = QuickReapplyPlanner.detectCameraFromUsbDevices(
            listOf(mapOf("idProduct" to 0x0C00, "productName" to "ILME-FX3"))
        )
        assertEquals("fx3_702", fx3.bodyId)
        assertEquals(false, fx3.isFx3aBlocked)

        val fx3a = QuickReapplyPlanner.detectCameraFromUsbDevices(
            listOf(mapOf("idProduct" to 0x0C01, "productName" to "ILME-FX3A"))
        )
        assertEquals(null, fx3a.bodyId)
        assertEquals("ILME-FX3A", fx3a.productName)
        assertEquals(true, fx3a.isFx3aBlocked)
        assertEquals("ILME-FX3A is not supported by FX3 7.02 kits", fx3a.warning)
    }
}
