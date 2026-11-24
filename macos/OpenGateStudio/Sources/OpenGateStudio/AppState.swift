import AppKit
import Foundation
import OpenGateStudioCore
import SwiftUI

public enum StudioTab: String, CaseIterable, Identifiable {
    case packsAndSafety = "Feature Packs & 5-Gate Apply"
    case clipInspector = "Clip, XML & Gyro Inspector"

    public var id: String { rawValue }
}

public enum SessionResultSource: String, Sendable, Equatable {
    case mock = "Offline Mock Simulation"
    case liveTerminal = "Live Terminal Session"
}

@MainActor
public final class AppState: ObservableObject {
    private struct SafetyResultsSnapshot {
        var preflightResult: PreflightResult?
        var applyResult: ApplyResult?
        var putbackResult: PutbackResult?
        var latestSyncedSession: LatestSessionResult?
        var preparedLiveCommandPath: String?
        var preparedLiveCommandPreview: String?
        var liveStatusBanner: String?
        var lastResultSource: SessionResultSource?
    }

    @Published public var selectedTab: StudioTab = .packsAndSafety

    // Bridge & bodies
    @Published public var bodies: [BodyInfo] = []
    @Published public var selectedBodyId: String = "zve1_202" {
        didSet {
            if oldValue != selectedBodyId {
                resetSafetySessionResults()
                syncDefaultPacksForSelectedBody()
            }
        }
    }
    @Published public var startupError: String?

    // Pin verification
    @Published public var pinResult: VerifyPinsResult?
    @Published public var isVerifyingPins: Bool = false

    // Camera mode
    @Published public var offlineMockCamera: Bool = true {
        didSet {
            if oldValue != offlineMockCamera {
                saveActiveSnapshot(forMock: oldValue)
                restoreSnapshot(forMock: offlineMockCamera)
                stepperError = nil
            }
        }
    }
    @Published public var mockState: MockCameraState = .stock {
        didSet {
            if oldValue != mockState {
                mockSnapshot = SafetyResultsSnapshot()
                if offlineMockCamera {
                    restoreSnapshot(forMock: true)
                    stepperError = nil
                }
            }
        }
    }

    // Modular packs
    @Published public var selectedPacks: Set<String> = ["mp4_3x2", "screen_3x2"]

    // 5-Gate Safety Stepper
    @Published public var batteryPulled10s: Bool = false
    @Published public var cameraInStillsMode: Bool = false
    @Published public var preflightResult: PreflightResult?
    @Published public var applyResult: ApplyResult?
    @Published public var putbackResult: PutbackResult?
    @Published public var stepperError: String?

    // Live Camera USB / Terminal bridge state
    @Published public var preparedLiveCommandPath: String?
    @Published public var preparedLiveCommandPreview: String?
    @Published public var liveStatusBanner: String?
    @Published public var latestSyncedSession: LatestSessionResult?
    @Published public var lastResultSource: SessionResultSource?
    @Published public var isSyncingSession: Bool = false

    @Published public var isRunningPreflight: Bool = false
    @Published public var isApplying: Bool = false
    @Published public var isPuttingBack: Bool = false
    @Published public var isConsoleExpanded: Bool = false

    // Console traces
    @Published public var consoleLogs: [CommandTrace] = []

    // Tab 2: Clip Inspector
    @Published public var selectedMP4URL: URL?
    @Published public var selectedXMLURL: URL?
    @Published public var clipResult: ClipCheckResult?
    @Published public var clipError: String?
    @Published public var isCheckingClip: Bool = false

    private var bridge: StudioBridge?
    private let sessionDir: URL
    private var mockSnapshot = SafetyResultsSnapshot()
    private var liveSnapshot = SafetyResultsSnapshot()

    public static let modularPackOrder: [String] = [
        "mp4_3x2",
        "screen_3x2",
        "hdmi32",
        "high_bitrate",
        "xavc_si"
    ]

    public init(bridge: StudioBridge? = nil, sessionDirectory: URL? = nil) {
        if let sessionDirectory {
            self.sessionDir = sessionDirectory
        } else {
            let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
                ?? URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
            self.sessionDir = appSupport
                .appendingPathComponent("OpenGateStudio", isDirectory: true)
                .appendingPathComponent("sessions", isDirectory: true)
        }

        if let bridge {
            self.bridge = bridge
        } else {
            do {
                self.bridge = try StudioBridge(sessionDirectory: self.sessionDir)
            } catch {
                self.bridge = nil
                self.startupError = error.localizedDescription
            }
        }
    }

    public var selectedBody: BodyInfo? {
        bodies.first(where: { $0.bodyId == selectedBodyId }) ?? bodies.first
    }

    public var isChecklistComplete: Bool {
        batteryPulled10s && cameraInStillsMode
    }

    public var isApplyUnlocked: Bool {
        isChecklistComplete && (preflightResult?.ready == true)
    }

    public var isMixedPowerSwitchWarning: Bool {
        guard let preflight = preflightResult else { return false }
        return !preflight.ready && (preflight.state == "not_ready" || (offlineMockCamera && mockState == .mixedPowerswitch))
    }

    public var pinsVerifiedForAllOrSelected: Bool {
        if let pinResult {
            return pinResult.ok
        }
        return selectedBody?.pinsOk ?? false
    }

    public func bootstrapIfNeeded() async {
        guard bodies.isEmpty else { return }
        await loadBodies()
        await verifyPins()
    }

    public func retryLocateBridge() async {
        do {
            bridge = try StudioBridge(sessionDirectory: sessionDir)
            startupError = nil
            await loadBodies()
            await verifyPins()
        } catch {
            startupError = error.localizedDescription
        }
    }

    public func loadBodies() async {
        guard let bridge else { return }
        do {
            let (res, trace) = try await bridge.listBodies()
            appendLog(trace)
            bodies = res.bodies
            if !bodies.contains(where: { $0.bodyId == selectedBodyId }), let first = bodies.first {
                selectedBodyId = first.bodyId
            }
            syncDefaultPacksForSelectedBody()
            startupError = nil
        } catch {
            captureError(error, target: .startup)
        }
    }

    public func verifyPins() async {
        guard let bridge else { return }
        isVerifyingPins = true
        defer { isVerifyingPins = false }

        do {
            let (res, trace) = try await bridge.verifyPins()
            appendLog(trace)
            pinResult = res
        } catch {
            captureError(error, target: .stepper)
        }
    }

    public func runPreflight() async {
        guard let bridge else { return }
        stepperError = nil
        isRunningPreflight = true
        defer { isRunningPreflight = false }

        if !offlineMockCamera {
            do {
                let (prep, trace) = try await bridge.prepareLiveCommand(
                    action: .preflight,
                    bodyId: selectedBodyId,
                    packs: nil,
                    sessionDir: sessionDir
                )
                appendLog(trace)
                recordPreparedLiveCommand(prep, actionLabel: "Read-Only Preflight")
                openLiveCommandInTerminalIfAllowed(prep.commandFile)
            } catch {
                captureError(error, target: .stepper)
            }
            return
        }

        applyResult = nil
        putbackResult = nil

        do {
            let (res, trace) = try await bridge.preflight(
                bodyId: selectedBodyId,
                mockCamera: true,
                mockState: mockState,
                sessionDir: sessionDir
            )
            appendLog(trace)
            preflightResult = res
            lastResultSource = .mock
            saveActiveSnapshot(forMock: true)
        } catch {
            preflightResult = nil
            captureError(error, target: .stepper)
        }
    }

    public func applySelectedPacks() async {
        guard let bridge, isApplyUnlocked else { return }
        stepperError = nil
        isApplying = true
        defer { isApplying = false }

        let orderedPacks = Self.modularPackOrder.filter { selectedPacks.contains($0) }
        let packsToSend = orderedPacks.isEmpty ? ["core_open_gate"] : orderedPacks

        if !offlineMockCamera {
            do {
                let (prep, trace) = try await bridge.prepareLiveCommand(
                    action: .apply,
                    bodyId: selectedBodyId,
                    packs: packsToSend,
                    sessionDir: sessionDir
                )
                appendLog(trace)
                recordPreparedLiveCommand(prep, actionLabel: "Apply Selected Packs")
                openLiveCommandInTerminalIfAllowed(prep.commandFile)
            } catch {
                captureError(error, target: .stepper)
            }
            return
        }

        putbackResult = nil
        do {
            let (res, trace) = try await bridge.apply(
                bodyId: selectedBodyId,
                packs: packsToSend,
                mockCamera: true,
                sessionDir: sessionDir
            )
            appendLog(trace)
            applyResult = res
            lastResultSource = .mock
            saveActiveSnapshot(forMock: true)
        } catch {
            captureError(error, target: .stepper)
        }
    }

    public func putBackToStock() async {
        guard let bridge else { return }
        stepperError = nil
        isPuttingBack = true
        defer { isPuttingBack = false }

        if !offlineMockCamera {
            do {
                let (prep, trace) = try await bridge.prepareLiveCommand(
                    action: .putback,
                    bodyId: selectedBodyId,
                    packs: nil,
                    sessionDir: sessionDir
                )
                appendLog(trace)
                recordPreparedLiveCommand(prep, actionLabel: "Put Back to Stock")
                openLiveCommandInTerminalIfAllowed(prep.commandFile)
            } catch {
                captureError(error, target: .stepper)
            }
            return
        }

        do {
            let (res, trace) = try await bridge.putback(
                bodyId: selectedBodyId,
                packs: nil,
                mockCamera: true,
                sessionDir: sessionDir
            )
            appendLog(trace)
            putbackResult = res
            applyResult = nil
            preflightResult = nil
            lastResultSource = .mock
            saveActiveSnapshot(forMock: true)
        } catch {
            captureError(error, target: .stepper)
        }
    }

    public func syncLatestCameraSession(silentIfNotFound: Bool = false) async {
        guard let bridge else { return }
        if isSyncingSession { return }
        isSyncingSession = true
        defer { isSyncingSession = false }

        do {
            let (res, trace) = try await bridge.latestSession(bodyId: selectedBodyId, sessionDir: sessionDir)
            let isNewSession = res.found && res.sessionId != liveSnapshot.latestSyncedSession?.sessionId
            if !silentIfNotFound || isNewSession {
                appendLog(trace)
            }
            applySyncedLiveSession(res, silentIfNotFound: silentIfNotFound)
        } catch {
            if !silentIfNotFound {
                captureError(error, target: .stepper)
            }
        }
    }

    public func handleAppDidBecomeActive() async {
        guard !offlineMockCamera else { return }
        await syncLatestCameraSession(silentIfNotFound: true)
    }

    public func openPreparedLiveCommand() {
        guard let path = preparedLiveCommandPath, !path.isEmpty else { return }
        openLiveCommandInTerminalIfAllowed(path)
    }

    public func selectMP4File(_ url: URL) async {
        selectedMP4URL = url
        if let autoXML = StudioBridge.autoDetectSidecarXML(for: url) {
            selectedXMLURL = autoXML
        } else {
            selectedXMLURL = nil
        }
        await inspectCurrentClip()
    }

    public func selectXMLFile(_ url: URL?) async {
        selectedXMLURL = url
        if selectedMP4URL != nil {
            await inspectCurrentClip()
        }
    }

    public func inspectCurrentClip() async {
        guard let bridge, let mp4URL = selectedMP4URL else { return }
        clipError = nil
        isCheckingClip = true
        defer { isCheckingClip = false }

        do {
            let (res, trace) = try await bridge.checkClip(mp4URL: mp4URL, xmlURL: selectedXMLURL)
            appendLog(trace)
            clipResult = res
        } catch {
            clipResult = nil
            captureError(error, target: .clip)
        }
    }

    public func isPackEnabled(_ packId: String) -> Bool {
        selectedPacks.contains(packId)
    }

    public func setPack(_ packId: String, enabled: Bool) {
        if enabled {
            selectedPacks.insert(packId)
        } else {
            selectedPacks.remove(packId)
        }
    }

    public func resetSafetySessionResults() {
        mockSnapshot = SafetyResultsSnapshot()
        liveSnapshot = SafetyResultsSnapshot()
        preflightResult = nil
        applyResult = nil
        putbackResult = nil
        latestSyncedSession = nil
        preparedLiveCommandPath = nil
        preparedLiveCommandPreview = nil
        liveStatusBanner = nil
        lastResultSource = nil
        stepperError = nil
    }

    private func saveActiveSnapshot(forMock isMock: Bool) {
        let snap = SafetyResultsSnapshot(
            preflightResult: preflightResult,
            applyResult: applyResult,
            putbackResult: putbackResult,
            latestSyncedSession: latestSyncedSession,
            preparedLiveCommandPath: preparedLiveCommandPath,
            preparedLiveCommandPreview: preparedLiveCommandPreview,
            liveStatusBanner: liveStatusBanner,
            lastResultSource: lastResultSource
        )
        if isMock {
            mockSnapshot = snap
        } else {
            liveSnapshot = snap
        }
    }

    private func restoreSnapshot(forMock isMock: Bool) {
        let snap = isMock ? mockSnapshot : liveSnapshot
        preflightResult = snap.preflightResult
        applyResult = snap.applyResult
        putbackResult = snap.putbackResult
        latestSyncedSession = snap.latestSyncedSession
        preparedLiveCommandPath = snap.preparedLiveCommandPath
        preparedLiveCommandPreview = snap.preparedLiveCommandPreview
        liveStatusBanner = snap.liveStatusBanner
        lastResultSource = snap.lastResultSource
    }

    private func recordPreparedLiveCommand(_ prep: PrepareLiveCommandResult, actionLabel: String) {
        let fileName = URL(fileURLWithPath: prep.commandFile).lastPathComponent
        let terminalDisabled = ProcessInfo.processInfo.environment["OPENGATE_NO_TERMINAL_OPEN"] == "1"
        let status: String
        if terminalDisabled {
            status = "Prepared \(actionLabel) command (\(fileName)) — Terminal auto-open suppressed (OPENGATE_NO_TERMINAL_OPEN=1)."
        } else {
            status = "Launched \(actionLabel) in Terminal.app (\(fileName)). Complete the prompts in Terminal, then return here or click Sync Latest Camera Session."
        }
        preparedLiveCommandPath = prep.commandFile
        preparedLiveCommandPreview = prep.preview
        liveStatusBanner = status
        liveSnapshot.preparedLiveCommandPath = prep.commandFile
        liveSnapshot.preparedLiveCommandPreview = prep.preview
        liveSnapshot.liveStatusBanner = status
    }

    private func openLiveCommandInTerminalIfAllowed(_ commandFile: String) {
        guard ProcessInfo.processInfo.environment["OPENGATE_NO_TERMINAL_OPEN"] != "1" else {
            return
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: commandFile))
    }

    private func applySyncedLiveSession(_ res: LatestSessionResult, silentIfNotFound: Bool) {
        liveSnapshot.latestSyncedSession = res

        guard res.found else {
            if !silentIfNotFound {
                let bodyLabel = selectedBody?.displayName ?? selectedBodyId
                liveSnapshot.liveStatusBanner = "No camera session recorded yet for \(bodyLabel). Run Read-Only Preflight in Terminal.app first."
                if !offlineMockCamera {
                    latestSyncedSession = res
                    liveStatusBanner = liveSnapshot.liveStatusBanner
                }
            }
            return
        }

        let sessionLabel = res.sessionId ?? "latest"
        let normalizedKind = (res.kind ?? "").lowercased()

        switch normalizedKind {
        case "putback":
            liveSnapshot.putbackResult = PutbackResult(
                ok: res.ok,
                stepsRun: res.stepsRun,
                state: res.state,
                bodyId: res.bodyId
            )
            liveSnapshot.applyResult = nil
            liveSnapshot.preflightResult = nil
            liveSnapshot.lastResultSource = .liveTerminal
            liveSnapshot.liveStatusBanner = "Synced Live Put Back session (\(sessionLabel)): state = \(res.state)"

        case "apply", "closing_dump":
            liveSnapshot.applyResult = ApplyResult(
                ok: res.ok && res.ready,
                stepsRun: res.stepsRun,
                closingDumpVerdict: res.verdict,
                activePacks: res.activePacks,
                bodyId: res.bodyId
            )
            liveSnapshot.putbackResult = nil
            liveSnapshot.lastResultSource = .liveTerminal
            liveSnapshot.liveStatusBanner = "Synced Live Apply session (\(sessionLabel)): \(res.verdict)"

        default:
            liveSnapshot.preflightResult = PreflightResult(
                ok: res.ok,
                ready: res.ready,
                state: res.state,
                verdict: res.verdict,
                sessionId: res.sessionId ?? "live-session",
                bodyId: res.bodyId,
                warning: res.ready ? nil : res.verdict
            )
            if res.state == "stock" || res.state == "not_ready" {
                liveSnapshot.applyResult = nil
            }
            liveSnapshot.putbackResult = nil
            liveSnapshot.lastResultSource = .liveTerminal
            let kindLabel = normalizedKind == "dump" ? "Dump" : "Preflight"
            liveSnapshot.liveStatusBanner = "Synced Live \(kindLabel) session (\(sessionLabel)): \(res.verdict)"
        }

        stepperError = nil
        if offlineMockCamera {
            if !silentIfNotFound {
                offlineMockCamera = false
            }
        } else {
            restoreSnapshot(forMock: false)
        }
    }

    private func syncDefaultPacksForSelectedBody() {
        guard let body = selectedBody else { return }
        var next = Set<String>()
        for packId in Self.modularPackOrder {
            if let pack = body.packs[packId] {
                if pack.defaultEnabled ?? (packId == "mp4_3x2" || packId == "screen_3x2") {
                    next.insert(packId)
                }
            }
        }
        if !next.isEmpty {
            selectedPacks = next
        }
    }

    private func appendLog(_ trace: CommandTrace) {
        consoleLogs.insert(trace, at: 0)
        if consoleLogs.count > 50 {
            consoleLogs.removeLast(consoleLogs.count - 50)
        }
    }

    private enum ErrorTarget {
        case startup
        case stepper
        case clip
    }

    private func captureError(_ error: Error, target: ErrorTarget) {
        if let bridgeError = error as? StudioBridgeError,
           case let .cliFailed(_, _, trace) = bridgeError {
            appendLog(trace)
        }
        let message = error.localizedDescription
        switch target {
        case .startup:
            startupError = message
        case .stepper:
            stepperError = message
        case .clip:
            clipError = message
        }
    }
}
