import Foundation
import OpenGateStudioCore
import Testing

@Suite("QuickReapplyPlanner Decision & Safety Gate Tests")
struct QuickReapplyTests {
    private func makeBridge(sessionDir: URL? = nil) throws -> StudioBridge {
        let testFileURL = URL(fileURLWithPath: #filePath)
        let candidateRoot = testFileURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        if StudioBridge.isValidRepoRoot(candidateRoot) {
            return try StudioBridge(repoRoot: candidateRoot, sessionDirectory: sessionDir)
        }
        return try StudioBridge(sessionDirectory: sessionDir)
    }

    private func makeTempDir(prefix: String) throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(prefix)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    @Test("Unverified SHA-256 pins always block quick re-apply")
    func testBlockedWhenPinsUnverified() {
        let liveStockSession = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_live_1",
            kind: "preflight",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "stock",
            verdict: "VERDICT READY (stock preflight)"
        )

        let decision = QuickReapplyPlanner.plan(
            pinsVerified: false,
            selectedBodyId: "zve1_202",
            offlineMockCamera: false,
            latestSession: liveStockSession,
            resultSource: .liveInApp
        )
        #expect(decision == .blockedPinsUnverified)
    }

    @Test("Left-behind warning or interrupted/unverified session requires recovery preflight first")
    func testRecoveryPreflightRequired() {
        let liveStockSession = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_live_1",
            kind: "preflight",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "stock",
            verdict: "VERDICT READY (stock preflight)"
        )

        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                leftBehindWarning: true,
                latestSession: liveStockSession,
                resultSource: .liveInApp
            ) == .runRecoveryPreflightFirst
        )

        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                hasInterruptedSession: true,
                latestSession: liveStockSession,
                resultSource: .liveInApp
            ) == .runRecoveryPreflightFirst
        )

        let unverifiedClosing = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "fx3_702",
            sessionId: "session_unverified",
            kind: "closing_dump",
            mode: "live_usb",
            ready: false,
            verified: false,
            state: "unverified",
            verdict: "VERDICT UNVERIFIED"
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "fx3_702",
                latestSession: unverifiedClosing,
                resultSource: .liveInApp
            ) == .runRecoveryPreflightFirst
        )

        let mixedPreflight = PreflightResult(
            ok: true,
            ready: false,
            state: "not_ready",
            verdict: "VERDICT NOT READY (warm power-switch mixed state: pull battery >= 10s)",
            sessionId: "session_mixed",
            bodyId: "a7s3_501"
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "a7s3_501",
                preflightResult: mixedPreflight,
                resultSource: .liveInApp
            ) == .runRecoveryPreflightFirst
        )
    }

    @Test("Battery swap or missing live preflight requires live preflight before Safe Daily apply")
    func testRunPreflightThenSafeDailyApply() {
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: false
            ) == .runPreflightThenSafeDailyApply
        )

        // After putback, CLI still requires a fresh preflight/dump session before next apply.
        let putbackSession = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_putback",
            kind: "putback",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "stock",
            verdict: "VERDICT READY (stock preflight)"
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                latestSession: putbackSession,
                resultSource: .liveInApp
            ) == .runPreflightThenSafeDailyApply
        )

        // Another body's live preflight must never unlock the selected body.
        let otherBodySession = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "a7s3_501",
            sessionId: "session_other_body",
            kind: "preflight",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "stock",
            verdict: "VERDICT READY (stock preflight)"
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                latestSession: otherBodySession,
                resultSource: .liveInApp
            ) == .runPreflightThenSafeDailyApply
        )
    }

    @Test("Mock READY never unlocks live Safe Daily apply")
    func testMockReadyNeverUnlocksLiveApply() async throws {
        let sessionDir = try makeTempDir(prefix: "ogs-quick-reapply-mock")
        defer { try? FileManager.default.removeItem(at: sessionDir) }
        let bridge = try makeBridge(sessionDir: sessionDir)

        let (mockPreflight, _) = try await bridge.preflight(
            bodyId: "zve1_202",
            mockCamera: true,
            mockState: .stock,
            sessionDir: sessionDir
        )
        #expect(mockPreflight.ready == true)
        #expect(mockPreflight.state == "stock")

        let (mockLatest, _) = try await bridge.latestSession(
            bodyId: "zve1_202",
            sessionDir: sessionDir,
            mode: "mock"
        )
        #expect(mockLatest.found == true)
        #expect(mockLatest.mode == "mock")
        #expect(mockLatest.ready == true)

        // 1. In offlineMockCamera mode with mock READY: must require live preflight.
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: true,
                preflightResult: mockPreflight,
                latestSession: mockLatest,
                resultSource: .mock
            ) == .runPreflightThenSafeDailyApply
        )

        // 2. Even if offlineMockCamera is switched false, mock preflight/session must NEVER unlock live apply.
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: false,
                preflightResult: mockPreflight,
                latestSession: mockLatest,
                resultSource: .mock
            ) == .runPreflightThenSafeDailyApply
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: false,
                preflightResult: mockPreflight,
                latestSession: nil,
                resultSource: nil
            ) == .runPreflightThenSafeDailyApply
        )
    }

    @Test("Verified live_usb stock preflight unlocks Safe Daily 3:2 apply")
    func testReadyForSafeDailyApply() {
        let liveStock = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_live_stock",
            kind: "preflight",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "stock",
            verdict: "VERDICT READY (stock preflight)"
        )
        let preflight = PreflightResult(
            ok: true,
            ready: true,
            state: "stock",
            verdict: "VERDICT READY (stock preflight)",
            sessionId: "session_live_stock",
            bodyId: "zve1_202"
        )

        let decision = QuickReapplyPlanner.plan(
            pinsVerified: true,
            selectedBodyId: "zve1_202",
            offlineMockCamera: false,
            preflightResult: preflight,
            latestSession: liveStock,
            resultSource: .liveInApp
        )
        #expect(decision == .readyForSafeDailyApply(packs: ["mp4_3x2", "screen_3x2"]))
    }

    @Test("Verified live applied state reports alreadyApplied")
    func testAlreadyApplied() {
        let liveApplied = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "a7s3_501",
            sessionId: "session_live_applied",
            kind: "closing_dump",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "applied",
            verdict: "VERDICT READY (open gate applied)",
            activePacks: ["core_open_gate", "mp4_3x2", "screen_3x2"]
        )
        let applyResult = ApplyResult(
            ok: true,
            stepsRun: [ExecutedStep(step: "L5", status: "DONE")],
            closingDumpVerdict: "VERDICT READY (open gate applied)",
            activePacks: ["core_open_gate", "mp4_3x2", "screen_3x2"],
            bodyId: "a7s3_501"
        )

        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "a7s3_501",
                offlineMockCamera: false,
                applyResult: applyResult,
                latestSession: liveApplied,
                resultSource: .liveInApp
            ) == .alreadyApplied
        )
    }

    @Test("Verified live express_apply session reports alreadyApplied while unverified/contradictory/mock do not")
    func testExpressApplyQuickReapplyState() {
        let liveExpressApplied = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_express_1",
            kind: "express_apply",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "applied",
            verdict: "VERDICT READY (open gate applied)",
            activePacks: ["core_open_gate", "mp4_3x2", "screen_3x2"]
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: false,
                latestSession: liveExpressApplied,
                resultSource: .liveInApp
            ) == .alreadyApplied
        )

        let unverifiedExpress = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_express_bad",
            kind: "express_apply",
            mode: "live_usb",
            ready: false,
            verified: false,
            state: "applied_unverified",
            verdict: "VERDICT UNVERIFIED"
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: false,
                latestSession: unverifiedExpress,
                resultSource: .liveInApp
            ) == .runRecoveryPreflightFirst
        )

        let contradictoryExpress = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_express_contradictory",
            kind: "express_apply",
            mode: "live_usb",
            ready: true,
            verified: true,
            state: "stock",
            verdict: "VERDICT CONTRADICTORY"
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: false,
                latestSession: contradictoryExpress,
                resultSource: .liveInApp
            ) == .runRecoveryPreflightFirst
        )

        let mockExpress = LatestSessionResult(
            ok: true,
            found: true,
            bodyId: "zve1_202",
            sessionId: "session_express_mock",
            kind: "express_apply",
            mode: "mock",
            ready: true,
            verified: true,
            state: "applied",
            verdict: "VERDICT READY (open gate applied)"
        )
        #expect(
            QuickReapplyPlanner.plan(
                pinsVerified: true,
                selectedBodyId: "zve1_202",
                offlineMockCamera: false,
                latestSession: mockExpress,
                resultSource: .mock
            ) == .runPreflightThenSafeDailyApply
        )
    }
}
