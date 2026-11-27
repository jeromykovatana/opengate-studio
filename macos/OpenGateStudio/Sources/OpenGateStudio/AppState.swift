import AppKit
import Foundation
import OpenGateStudioCore
import SwiftUI

public enum StudioDestination: String, CaseIterable, Identifiable {
    case camera = "Camera"
    case clips = "Clips"

    public var id: String { rawValue }
}

public enum DiagnosticsTab: String, CaseIterable, Identifiable {
    case console = "Console Log"
    case pins = "Kit Integrity"
    case fieldReport = "Field Report"

    public var id: String { rawValue }
}

public enum CameraWorkflowStage: Equatable, Sendable {
    case pinsBlocked
    case recoveryRequired
    case applied
    case restoredStock
    case readyToApply
    case needsPreflight
}

public enum SessionResultSource: String, Sendable, Equatable {
    case mock = "Offline Mock Simulation"
    case liveInApp = "Live USB (In-App)"
    case liveTerminal = "Live Terminal Session"
}

public enum PackPreset: String, CaseIterable, Identifiable, Sendable {
    case safeDaily = "Safe Daily 3:2"
    case cinemaFull = "Cinema + H.264/All-Intra + HDMI"
    case reliabilityAudit = "Reliability Audit"

    public var id: String { rawValue }
}

public enum LiveSessionPhase: Equatable, Sendable {
    case confirming
    case running
    case finished
    case cancelled
    case failed
}

public enum LiveStepStatus: Equatable, Sendable {
    case pending
    case waitingDrive(first: Bool)
    case active
    case done(outcome: String)
    case failed(message: String?)
}

public struct LiveStepItem: Identifiable, Equatable, Sendable {
    public let id: String
    public let index: Int
    public let summary: String
    public var status: LiveStepStatus

    public init(id: String, index: Int, summary: String, status: LiveStepStatus = .pending) {
        self.id = id
        self.index = index
        self.summary = summary
        self.status = status
    }
}

public enum LiveActionBanner: Equatable, Sendable {
    case awaitingAdminAuth
    case connectInitialDrive(title: String, detail: String, stepId: String?)
    case replugUsbDrive(title: String, detail: String, stepId: String?)
    case switchToMovieMode(title: String, detail: String, hint: String?)
}

public struct LiveSessionPresentation: Identifiable, Equatable {
    public let id: UUID
    public let action: LiveCommandAction
    public let bodyId: String
    public let cameraDisplayName: String
    public let requiredFirmware: String
    public let selectedPacks: [String]
    public let estimatedStepsPreview: [String]
    public let estimatedStepCount: Int

    public var phase: LiveSessionPhase = .confirming
    public var confirmedFirmwareAndUsb: Bool = false
    public var confirmedVolatileRam: Bool = false

    public var steps: [LiveStepItem] = []
    public var includesClosingDump: Bool = false
    public var closingKind: String? = nil
    public var closingDumpStatus: LiveStepStatus? = nil
    public var activeBanner: LiveActionBanner? = nil
    public var isCancelling: Bool = false
    public var logText: String = ""
    public var isLogExpanded: Bool = false

    public var completionVerdict: String? = nil
    public var completionState: String? = nil
    public var completionReady: Bool? = nil
    public var completionSessionId: String? = nil
    public var completionActivePacks: [String] = []

    public var failureMessage: String? = nil
    public var leftBehindWarning: Bool = false
    public var cancelMessage: String? = nil
    public var wasAdminAuthCancelled: Bool = false

    public init(
        id: UUID = UUID(),
        action: LiveCommandAction,
        bodyId: String,
        cameraDisplayName: String,
        requiredFirmware: String,
        selectedPacks: [String],
        estimatedStepsPreview: [String],
        estimatedStepCount: Int
    ) {
        self.id = id
        self.action = action
        self.bodyId = bodyId
        self.cameraDisplayName = cameraDisplayName
        self.requiredFirmware = requiredFirmware
        self.selectedPacks = selectedPacks
        self.estimatedStepsPreview = estimatedStepsPreview
        self.estimatedStepCount = estimatedStepCount
    }

    public var requiresVolatileRamConfirmation: Bool {
        action == .apply || action == .putback
    }

    public var canAuthorizeAndStart: Bool {
        confirmedFirmwareAndUsb && (!requiresVolatileRamConfirmation || confirmedVolatileRam)
    }

    public var actionTitle: String {
        switch action {
        case .preflight:
            return "Read-Only Preflight"
        case .dump:
            return "Read-Only RAM Dump"
        case .apply:
            return "Apply Selected Packs"
        case .putback:
            return "Put Back to Stock"
        }
    }

    public var totalProgressUnits: Int {
        let base = max(steps.count, 1)
        return base + (includesClosingDump ? 1 : 0)
    }

    public var completedProgressUnits: Int {
        var count = steps.filter {
            if case .done = $0.status { return true }
            return false
        }.count
        if includesClosingDump, let cd = closingDumpStatus, case .done = cd {
            count += 1
        }
        return count
    }

    public var progressFraction: Double {
        if phase == .finished {
            return 1.0
        }
        guard !steps.isEmpty || includesClosingDump else { return 0.0 }
        let total = Double(steps.count + (includesClosingDump ? 1 : 0))
        guard total > 0 else { return 0.0 }
        var units = Double(completedProgressUnits)
        let hasActive = steps.contains(where: {
            if case .active = $0.status { return true }
            return false
        }) || {
            if case .active = closingDumpStatus { return true }
            return false
        }()
        if hasActive {
            units += 0.35
        }
        return min(max(units / total, 0.0), 1.0)
    }
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
        var hasInterruptedSession: Bool = false
        var leftBehindWarning: Bool = false
    }

    @Published public var selectedDestination: StudioDestination = .camera
    @Published public var showSetupGuideSheet: Bool = false
    @Published public var isSetupBannerDismissed: Bool = false
    @Published public var showDiagnosticsSheet: Bool = false
    @Published public var selectedDiagnosticsTab: DiagnosticsTab = .console
    @Published public var isClipInspectorPresented: Bool = true
    @Published public var showProxyExportSheet: Bool = false
    @Published public var showGyroflowPresetsSheet: Bool = false
    @Published public var showModePopover: Bool = false

    // Bridge & bodies
    @Published public var bodies: [BodyInfo] = []
    @Published public var selectedBodyId: String = "zve1_202" {
        didSet {
            if oldValue != selectedBodyId {
                resetSafetySessionResults()
                resetBodySpecificSetupConfirmations()
                syncDefaultPacksForSelectedBody()
            }
        }
    }
    @Published public var startupError: String?

    // Pin verification
    @Published public var pinResult: VerifyPinsResult?
    @Published public var isVerifyingPins: Bool = false

    // Camera mode (defaults to Live USB)
    @Published public var offlineMockCamera: Bool = false {
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

    // Tab 1: Camera Setup Wizard checklist
    @Published public var checkedFirmwareVersion: Bool = false
    @Published public var checkedSdCardSlot1: Bool = false
    @Published public var checkedUsbMassStorage: Bool = false
    @Published public var checkedMovie24pSettings: Bool = false
    @Published public var checkedAppsClosed: Bool = false

    // Modular packs
    @Published public var selectedPacks: Set<String> = ["mp4_3x2", "screen_3x2"]

    // 5-Gate Safety Stepper
    @Published public var batteryPulled10s: Bool = false
    @Published public var cameraInStillsMode: Bool = false
    @Published public var preflightResult: PreflightResult?
    @Published public var applyResult: ApplyResult?
    @Published public var putbackResult: PutbackResult?
    @Published public var stepperError: String?

    // Live Camera USB (In-App + Terminal fallback) state
    @Published public var activeLiveSession: LiveSessionPresentation?
    @Published public var preparedLiveCommandPath: String?
    @Published public var preparedLiveCommandPreview: String?
    @Published public var liveStatusBanner: String?
    @Published public var latestSyncedSession: LatestSessionResult?
    @Published public var lastResultSource: SessionResultSource?
    @Published public var isSyncingSession: Bool = false
    @Published public var hasInterruptedLiveSession: Bool = false
    @Published public var liveLeftBehindWarning: Bool = false

    @Published public var isRunningPreflight: Bool = false
    @Published public var isApplying: Bool = false
    @Published public var isPuttingBack: Bool = false
    @Published public var isConsoleExpanded: Bool = false

    // Console traces
    @Published public var consoleLogs: [CommandTrace] = []

    // Tab 3: Clip Inspector
    @Published public var selectedMP4URL: URL?
    @Published public var selectedXMLURL: URL?
    @Published public var clipExpectMode: String = "open-gate"
    @Published public var clipResult: ClipCheckResult?
    @Published public var clipError: String?
    @Published public var isCheckingClip: Bool = false

    // Tab 3: Compact Gyro Diagnostic
    @Published public var gyroDiagResult: GyroDiagnosticResult?
    @Published public var gyroDiagError: String?
    @Published public var isRunningGyroDiag: Bool = false

    // Tab 4: Creator Workflow (Batch Ingest, Framing Preview, Proxies, Gyroflow Presets)
    @Published public var ingestRootURL: URL?
    @Published public var ingestExpectMode: String = "auto"
    @Published public var ingestRecursive: Bool = true
    @Published public var ingestResult: BatchIngestResult?
    @Published public var ingestError: String?
    @Published public var isIngestingBatch: Bool = false
    @Published public var selectedIngestedClipId: String?
    @Published public var selectedProxyClipPaths: Set<String> = []

    @Published public var previewAspect: DeliveryAspect = .aspect16x9
    @Published public var previewShowActionSafe: Bool = true
    @Published public var previewShowTitleSafe: Bool = true

    @Published public var proxyOutDirURL: URL?
    @Published public var proxyAspect: ProxyAspectOption = .ratio3x2
    @Published public var proxyResolution: ProxyResolutionOption = .res1080p
    @Published public var proxyCodec: ProxyCodecOption = .h264
    @Published public var proxyPreserveSidecar: Bool = true
    @Published public var proxyDryRun: Bool = false
    @Published public var proxyResult: ProxyGenerationResult?
    @Published public var proxyError: String?
    @Published public var isGeneratingProxies: Bool = false

    @Published public var gyroPresetList: GyroflowPresetListResult?
    @Published public var gyroPresetInstallResult: InstallGyroflowPresetsResult?
    @Published public var gyroPresetError: String?
    @Published public var isLoadingGyroPresets: Bool = false
    @Published public var isInstallingGyroPresets: Bool = false

    // Tab 3: Field Test & Reliability Report Builder
    @Published public var reportClipsFolderURL: URL?
    @Published public var reportMediaCard: String = ""
    @Published public var reportLens: String = ""
    @Published public var reportAmbientC: String = ""
    @Published public var reportSoakMinutes: String = ""
    @Published public var reportThermalResult: String = ""
    @Published public var reportReactivationSeconds: String = ""
    @Published public var reportAfDesqueezeNotes: String = ""
    @Published public var reportNotes: String = ""
    @Published public var reportResult: BuildReportResult?
    @Published public var reportError: String?
    @Published public var isBuildingReport: Bool = false
    @Published public var copiedReportConfirmation: Bool = false

    private var bridge: StudioBridge?
    private let sessionDir: URL
    private var mockSnapshot = SafetyResultsSnapshot()
    private var liveSnapshot = SafetyResultsSnapshot()
    private var activeLiveRunHandle: LiveRunHandle?
    private var activeLiveRunTask: Task<LiveRunResult, Error>?

    public static let modularPackOrder: [String] = [
        "mp4_3x2",
        "screen_3x2",
        "hdmi32",
        "high_bitrate",
        "xavc_si",
        "fx3_playback"
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

    public var requiredFirmwareForSelectedBody: String {
        if let fw = selectedBody?.firmware, !fw.isEmpty {
            return fw
        }
        switch selectedBodyId {
        case "a7s3_501": return "5.01"
        case "fx3_702": return "7.02"
        default: return "2.02"
        }
    }

    public var orderedSelectedPacksToSend: [String] {
        let ordered = Self.modularPackOrder.filter { packId in
            selectedPacks.contains(packId) && (selectedBody == nil || selectedBody?.packs[packId] != nil)
        }
        return ordered.isEmpty ? ["core_open_gate"] : ordered
    }

    public var isSetupWizardChecklistComplete: Bool {
        checkedFirmwareVersion
            && checkedSdCardSlot1
            && checkedUsbMassStorage
            && checkedMovie24pSettings
            && checkedAppsClosed
    }

    public var isChecklistComplete: Bool {
        batteryPulled10s && cameraInStillsMode
    }

    public var isApplyUnlocked: Bool {
        let pinsOkForLive = offlineMockCamera || pinResult == nil || pinsVerifiedForAllOrSelected
        return isChecklistComplete
            && pinsOkForLive
            && (preflightResult?.ready == true)
            && (offlineMockCamera || preflightResult?.state == "stock")
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

    public var isLiveSessionActive: Bool {
        activeLiveSession != nil
    }

    public var cameraStage: CameraWorkflowStage {
        if !offlineMockCamera && !pinsVerifiedForAllOrSelected {
            return .pinsBlocked
        }
        if isMixedPowerSwitchWarning {
            return .recoveryRequired
        }
        if !offlineMockCamera && quickReapplyDecision == .runRecoveryPreflightFirst {
            return .recoveryRequired
        }
        if let app = applyResult, app.ok {
            return .applied
        }
        if !offlineMockCamera && quickReapplyDecision == .alreadyApplied {
            return .applied
        }
        if let put = putbackResult, put.ok && put.state == "stock" {
            return .restoredStock
        }
        if isApplyUnlocked {
            return .readyToApply
        }
        return .needsPreflight
    }

    public var activePackPreset: PackPreset? {
        let safeDaily = availablePackSet(from: ["mp4_3x2", "screen_3x2"])
        if selectedPacks == safeDaily {
            return .safeDaily
        }
        let cinemaFull = availablePackSet(from: ["mp4_3x2", "screen_3x2", "hdmi32", "high_bitrate", "xavc_si"])
        if selectedPacks == cinemaFull {
            return .cinemaFull
        }
        return nil
    }

    public var activeInspectedBatchClip: IngestedClipItem? {
        guard let clips = ingestResult?.clips, !clips.isEmpty else { return nil }
        if let selectedId = selectedIngestedClipId,
           let matched = clips.first(where: { $0.id == selectedId }) {
            return matched
        }
        return clips.first
    }

    public func humanReadablePackTitle(for packId: String) -> String {
        ModularPackDescriptor.descriptor(for: packId, bodyId: selectedBodyId).title
    }

    private func availablePackSet(from desired: [String]) -> Set<String> {
        var next = Set<String>()
        for packId in desired {
            if packId == "fx3_playback" { continue }
            if selectedBody == nil || selectedBody?.packs[packId] != nil {
                next.insert(packId)
            }
        }
        return next
    }

    public var quickReapplyDecision: QuickReapplyDecision {
        let mappedSource: QuickReapplyResultSource? = lastResultSource.map {
            switch $0 {
            case .mock: return .mock
            case .liveInApp: return .liveInApp
            case .liveTerminal: return .liveTerminal
            }
        }
        return QuickReapplyPlanner.plan(
            pinsVerified: pinsVerifiedForAllOrSelected,
            selectedBodyId: selectedBodyId,
            offlineMockCamera: offlineMockCamera,
            leftBehindWarning: liveLeftBehindWarning || (activeLiveSession?.leftBehindWarning ?? false),
            hasInterruptedSession: hasInterruptedLiveSession || (activeLiveSession?.phase == .failed),
            preflightResult: preflightResult,
            applyResult: applyResult,
            putbackResult: putbackResult,
            latestSession: latestSyncedSession,
            resultSource: mappedSource
        )
    }

    public func triggerQuickSafeDailyReapply() {
        guard activeLiveSession == nil else { return }
        stepperError = nil

        if offlineMockCamera {
            offlineMockCamera = false
        }

        applyPackPreset(.safeDaily)

        switch quickReapplyDecision {
        case .blockedPinsUnverified:
            stepperError = "Cannot run Quick Field Re-Apply: SHA-256 kit pin verification failed or is unverified."

        case .runRecoveryPreflightFirst, .runPreflightThenSafeDailyApply:
            presentLiveSession(action: .preflight)

        case .readyForSafeDailyApply(let packs):
            let available = Set(packs.filter { selectedBody == nil || selectedBody?.packs[$0] != nil })
            if !available.isEmpty {
                selectedPacks = available
            }
            presentLiveSession(action: .apply)

        case .alreadyApplied:
            liveStatusBanner = "Safe Daily 3:2 Open Gate is already verified active. If you swapped the battery, run Read-Only Preflight first."
        }
    }

    public func startBatterySwapQuickReapply() {
        guard activeLiveSession == nil else { return }
        stepperError = nil

        if offlineMockCamera {
            offlineMockCamera = false
        }

        applyPackPreset(.safeDaily)
        liveSnapshot.applyResult = nil
        liveSnapshot.preflightResult = nil
        applyResult = nil
        preflightResult = nil
        presentLiveSession(action: .preflight)
    }

    public func handleBatterySwapReCheck() async {
        guard activeLiveSession == nil else { return }
        stepperError = nil

        if offlineMockCamera {
            mockSnapshot.applyResult = nil
            mockSnapshot.preflightResult = nil
            mockSnapshot.putbackResult = nil
            applyResult = nil
            preflightResult = nil
            putbackResult = nil
            if isChecklistComplete {
                await runPreflight()
            }
            return
        }

        liveSnapshot.applyResult = nil
        liveSnapshot.preflightResult = nil
        liveSnapshot.putbackResult = nil
        applyResult = nil
        preflightResult = nil
        putbackResult = nil
        await runPreflight()
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

        if !offlineMockCamera {
            guard pinResult == nil || pinsVerifiedForAllOrSelected else {
                stepperError = "Cannot start Live USB preflight: SHA-256 kit pin verification failed. Open Diagnostics -> Kit Integrity to inspect."
                return
            }
            presentLiveSession(action: .preflight)
            return
        }

        isRunningPreflight = true
        defer { isRunningPreflight = false }

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

        if !offlineMockCamera {
            presentLiveSession(action: .apply)
            return
        }

        isApplying = true
        defer { isApplying = false }

        let packsToSend = orderedSelectedPacksToSend
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

        if !offlineMockCamera {
            presentLiveSession(action: .putback)
            return
        }

        isPuttingBack = true
        defer { isPuttingBack = false }

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

    // MARK: - Native In-App Live USB Session Lifecycle

    public func presentLiveSession(action: LiveCommandAction) {
        guard activeLiveSession == nil else { return }
        stepperError = nil

        let displayName = selectedBody?.displayName ?? defaultDisplayName(for: selectedBodyId)
        let fw = requiredFirmwareForSelectedBody
        let packs = action == .apply ? orderedSelectedPacksToSend : []
        let previewSteps = estimateStepsPreview(for: action, packs: packs)

        activeLiveSession = LiveSessionPresentation(
            action: action,
            bodyId: selectedBodyId,
            cameraDisplayName: displayName,
            requiredFirmware: fw,
            selectedPacks: packs,
            estimatedStepsPreview: previewSteps,
            estimatedStepCount: previewSteps.count
        )
    }

    public func authorizeAndStartLiveSession() async {
        guard let bridge,
              var session = activeLiveSession,
              session.phase == .confirming,
              session.canAuthorizeAndStart else {
            return
        }

        stepperError = nil
        session.phase = .running
        session.activeBanner = .awaitingAdminAuth
        session.steps = []
        session.includesClosingDump = (session.action == .apply || session.action == .putback)
        session.closingKind = session.action == .putback ? "stock_check" : (session.action == .apply ? "movie_dump" : nil)
        session.closingDumpStatus = session.includesClosingDump ? .pending : nil
        session.isCancelling = false
        session.logText = ""
        session.completionVerdict = nil
        session.completionState = nil
        session.completionReady = nil
        session.completionSessionId = nil
        session.completionActivePacks = []
        session.failureMessage = nil
        session.leftBehindWarning = false
        session.cancelMessage = nil
        session.wasAdminAuthCancelled = false
        activeLiveSession = session

        switch session.action {
        case .preflight, .dump:
            isRunningPreflight = true
        case .apply:
            isApplying = true
        case .putback:
            isPuttingBack = true
        }
        defer {
            isRunningPreflight = false
            isApplying = false
            isPuttingBack = false
            activeLiveRunHandle = nil
            activeLiveRunTask = nil
        }

        let packsArg: [String]? = session.action == .apply ? session.selectedPacks : nil
        let (handle, task) = bridge.startLiveInAppRun(
            action: session.action,
            bodyId: session.bodyId,
            firmwareConfirmed: session.requiredFirmware,
            confirmVolatileRam: session.requiresVolatileRamConfirmation ? session.confirmedVolatileRam : false,
            packs: packsArg,
            sessionDir: sessionDir,
            dryRunSimulate: false,
            noMovieSession: false,
            onEvent: { [weak self] event in
                Task { @MainActor [weak self] in
                    self?.handleLiveRunEvent(event)
                }
            },
            onLogChunk: { [weak self] chunk in
                Task { @MainActor [weak self] in
                    self?.appendLiveRunLogChunk(chunk)
                }
            }
        )

        activeLiveRunHandle = handle
        activeLiveRunTask = task

        do {
            let result = try await task.value

            let packsSuffix = packsArg.map { " --packs \($0.joined(separator: ","))" } ?? ""
            let trace = CommandTrace(
                command: "live-inapp \(session.action.rawValue) --body \(session.bodyId) --firmware-confirmed \(session.requiredFirmware)\(packsSuffix)",
                exitCode: result.exitCode,
                stdout: result.logOutput,
                stderr: result.stderrOutput
            )
            appendLog(trace)

            await finalizeLiveSessionResult(result, action: session.action, wasCancelRequestedByButton: handle.isCancelRequested)
        } catch {
            if var current = activeLiveSession {
                current.phase = .failed
                current.activeBanner = nil
                current.isCancelling = false
                current.failureMessage = error.localizedDescription
                activeLiveSession = current
            }
            captureError(error, target: .stepper)
        }
    }

    public func cancelActiveLiveSession() {
        guard var current = activeLiveSession, current.phase == .running, !current.isCancelling else { return }
        current.isCancelling = true
        activeLiveSession = current
        activeLiveRunHandle?.cancel()
    }

    public func retryActiveLiveSession() {
        guard var current = activeLiveSession, current.phase != .running else { return }
        current.phase = .confirming
        current.steps = []
        current.closingDumpStatus = nil
        current.activeBanner = nil
        current.isCancelling = false
        current.logText = ""
        current.completionVerdict = nil
        current.completionState = nil
        current.completionReady = nil
        current.completionSessionId = nil
        current.completionActivePacks = []
        current.failureMessage = nil
        current.leftBehindWarning = false
        current.cancelMessage = nil
        current.wasAdminAuthCancelled = false
        activeLiveSession = current
    }

    public func dismissLiveSessionSheet() {
        guard activeLiveSession?.phase != .running else { return }
        activeLiveSession = nil
    }

    public func launchTerminalFallbackFromSheet() async {
        guard let bridge,
              let session = activeLiveSession,
              session.phase != .running else {
            return
        }

        let action = session.action
        let packsToSend: [String]? = action == .apply ? session.selectedPacks : nil
        activeLiveSession = nil

        stepperError = nil
        do {
            let (prep, trace) = try await bridge.prepareLiveCommand(
                action: action,
                bodyId: session.bodyId,
                packs: packsToSend,
                sessionDir: sessionDir
            )
            appendLog(trace)
            recordPreparedLiveCommand(prep, actionLabel: session.actionTitle)
            openLiveCommandInTerminalIfAllowed(prep.commandFile)
        } catch {
            captureError(error, target: .stepper)
        }
    }

    private func handleLiveRunEvent(_ event: LiveRunEvent) {
        guard var session = activeLiveSession else { return }

        switch event.type {
        case "plan":
            if case .awaitingAdminAuth = session.activeBanner {
                session.activeBanner = nil
            }
            if let planSteps = event.steps, !planSteps.isEmpty {
                session.steps = planSteps.enumerated().map { idx, step in
                    LiveStepItem(id: step.id, index: idx + 1, summary: step.summary, status: .pending)
                }
            } else if session.steps.isEmpty {
                let fallbackLabel = (session.action == .preflight || session.action == .dump)
                    ? "Read-only volatile RAM verification"
                    : session.actionTitle
                session.steps = [
                    LiveStepItem(id: session.action == .preflight ? "PREFLIGHT" : "STEP", index: 1, summary: fallbackLabel, status: .pending)
                ]
            }
            if let closing = event.closingDump {
                session.includesClosingDump = closing
                session.closingDumpStatus = closing ? .pending : nil
            }
            if let cKind = event.closingKind {
                session.closingKind = cKind
            }

        case "wait_drive":
            let isFirst = event.first ?? true
            if isFirst {
                session.activeBanner = .connectInitialDrive(
                    title: event.title ?? "Connect USB-C in Stills Mode (Mass Storage)",
                    detail: event.detail ?? "Make sure the camera is ON in Stills mode (USB Connection = Mass Storage), then plug in the USB-C cable.",
                    stepId: event.stepId
                )
            } else {
                session.activeBanner = .replugUsbDrive(
                    title: event.title ?? "Unplug USB-C and Plug Right Back In — Keep Camera ON!",
                    detail: event.detail ?? "Unplug the USB-C cable, pause 1–2 seconds, and plug it right back in without turning the camera off.",
                    stepId: event.stepId
                )
            }
            if session.includesClosingDump && event.stepId == "check" && session.action == .putback {
                session.closingKind = "stock_check"
                session.closingDumpStatus = .waitingDrive(first: false)
            } else {
                updateStepStatus(&session, stepId: event.stepId, stepIndex: event.stepIndex, summary: event.title) { current in
                    if case .done = current { return current }
                    return .waitingDrive(first: isFirst)
                }
            }

        case "step_start":
            session.activeBanner = nil
            updateStepStatus(&session, stepId: event.stepId, stepIndex: event.stepIndex, summary: event.summary) { _ in
                .active
            }

        case "step_done":
            let isOk = event.ok ?? true
            let outcomeText = event.outcome ?? (isOk ? "DONE" : "FAILED")
            updateStepStatus(&session, stepId: event.stepId, stepIndex: event.stepIndex, summary: event.summary) { _ in
                isOk ? .done(outcome: outcomeText) : .failed(message: outcomeText)
            }

        case "wait_movie_replug":
            session.activeBanner = .switchToMovieMode(
                title: event.title ?? "Unplug USB-C → Switch Camera to MOVIE Mode (24p/25p/30p) → Replug USB-C",
                detail: event.detail ?? "Keep the camera ON, unplug USB-C, switch to Movie mode (24p / 25p / 30p), wait 2 seconds, then replug USB-C for the closing verification dump.",
                hint: event.hint
            )
            session.includesClosingDump = true
            session.closingKind = "movie_dump"
            session.closingDumpStatus = .waitingDrive(first: false)

        case "closing_dump_start":
            session.activeBanner = nil
            session.includesClosingDump = true
            if let cKind = event.closingKind {
                session.closingKind = cKind
            }
            session.closingDumpStatus = .active

        case "closing_dump_done":
            session.activeBanner = nil
            session.includesClosingDump = true
            if let cKind = event.closingKind {
                session.closingKind = cKind
            }
            let verdict = event.verdict ?? "VERIFIED"
            if event.ready == true && event.verified != false {
                session.closingDumpStatus = .done(outcome: verdict)
            } else {
                session.closingDumpStatus = .failed(message: verdict)
            }

        case "complete":
            session.activeBanner = nil
            session.completionVerdict = event.verdict
            session.completionState = event.state
            session.completionReady = event.ready
            session.completionSessionId = event.sessionId
            session.completionActivePacks = event.activePacks ?? []
            for idx in session.steps.indices {
                if case .active = session.steps[idx].status {
                    session.steps[idx].status = .done(outcome: "DONE")
                }
            }
            if case .active = session.closingDumpStatus {
                if event.ok == true && event.ready == true && event.verified != false {
                    session.closingDumpStatus = .done(outcome: event.verdict ?? "DONE")
                } else {
                    session.closingDumpStatus = .failed(message: event.verdict ?? "UNVERIFIED")
                }
            }

        case "cancelled":
            session.activeBanner = nil
            session.cancelMessage = event.message ?? "Cancelled safely before the next step."

        case "error":
            session.activeBanner = nil
            session.failureMessage = event.message ?? "Live USB step failed."
            session.leftBehindWarning = event.leftBehind ?? false
            if event.stepId != nil || event.stepIndex != nil {
                updateStepStatus(&session, stepId: event.stepId, stepIndex: event.stepIndex, summary: nil) { _ in
                    .failed(message: event.message)
                }
            }

        default:
            break
        }

        activeLiveSession = session
    }

    private func updateStepStatus(
        _ session: inout LiveSessionPresentation,
        stepId: String?,
        stepIndex: Int?,
        summary: String?,
        transform: (LiveStepStatus) -> LiveStepStatus
    ) {
        if let stepId, let idx = session.steps.firstIndex(where: { $0.id == stepId }) {
            session.steps[idx].status = transform(session.steps[idx].status)
            return
        }
        if let stepIndex, stepIndex >= 1, stepIndex <= session.steps.count {
            session.steps[stepIndex - 1].status = transform(session.steps[stepIndex - 1].status)
            return
        }
        if let stepId, !stepId.isEmpty {
            let nextIndex = stepIndex ?? (session.steps.count + 1)
            let item = LiveStepItem(
                id: stepId,
                index: nextIndex,
                summary: summary ?? stepId,
                status: transform(.pending)
            )
            session.steps.append(item)
        }
    }

    private func appendLiveRunLogChunk(_ chunk: String) {
        guard !chunk.isEmpty, var session = activeLiveSession else { return }
        session.logText.append(chunk)
        if session.logText.count > 120_000 {
            session.logText = String(session.logText.suffix(100_000))
        }
        activeLiveSession = session
    }

    private func finalizeLiveSessionResult(
        _ result: LiveRunResult,
        action: LiveCommandAction,
        wasCancelRequestedByButton: Bool
    ) async {
        guard var session = activeLiveSession else { return }

        if session.logText.isEmpty && !result.logOutput.isEmpty {
            session.logText = result.logOutput
        }
        session.activeBanner = nil
        session.isCancelling = false

        let osascriptCancelled = StudioBridge.isOsascriptUserCancelled(
            exitCode: result.exitCode,
            stderr: result.stderrOutput
        )

        let outcome = LiveSessionOutcomeEvaluator.evaluate(
            result: result,
            action: action,
            actionTitle: session.actionTitle,
            existingFailureMessage: session.failureMessage,
            existingCancelMessage: session.cancelMessage,
            existingLeftBehind: session.leftBehindWarning,
            wasCancelRequestedByButton: wasCancelRequestedByButton,
            isOsascriptCancelled: osascriptCancelled
        )

        switch outcome {
        case let .cancelled(adminAuth, message):
            session.phase = .cancelled
            session.wasAdminAuthCancelled = adminAuth
            session.cancelMessage = message
            if !adminAuth && (session.completedProgressUnits > 0 || session.leftBehindWarning) {
                liveSnapshot.hasInterruptedSession = true
                liveSnapshot.leftBehindWarning = liveSnapshot.leftBehindWarning || session.leftBehindWarning
                if action == .apply {
                    liveSnapshot.preflightResult = nil
                }
            }
            activeLiveSession = session
            await syncLatestCameraSession(silentIfNotFound: true, source: .liveInApp)

        case let .finished(complete):
            session.phase = .finished
            session.completionVerdict = complete.verdict ?? session.completionVerdict
            session.completionState = complete.state ?? session.completionState
            session.completionReady = complete.ready ?? session.completionReady
            session.completionSessionId = complete.sessionId ?? session.completionSessionId
            if let packs = complete.activePacks {
                session.completionActivePacks = packs
            }
            for idx in session.steps.indices {
                if case .active = session.steps[idx].status {
                    session.steps[idx].status = .done(outcome: "DONE")
                }
            }
            if complete.ready == true && complete.verified != false {
                liveSnapshot.hasInterruptedSession = false
                liveSnapshot.leftBehindWarning = false
            } else {
                liveSnapshot.hasInterruptedSession = true
            }
            activeLiveSession = session
            await syncLatestCameraSession(silentIfNotFound: true, source: .liveInApp)

        case let .failed(message, leftBehind):
            session.phase = .failed
            session.failureMessage = message
            session.leftBehindWarning = leftBehind
            if case .active = session.closingDumpStatus {
                session.closingDumpStatus = .failed(message: message)
            }
            if action == .apply || action == .putback || leftBehind {
                liveSnapshot.hasInterruptedSession = true
                liveSnapshot.leftBehindWarning = liveSnapshot.leftBehindWarning || leftBehind
                if action == .apply {
                    liveSnapshot.preflightResult = nil
                }
            }
            activeLiveSession = session
            await syncLatestCameraSession(silentIfNotFound: true, source: .liveInApp)
        }
    }

    public func syncLatestCameraSession(
        silentIfNotFound: Bool = false,
        source: SessionResultSource = .liveInApp
    ) async {
        guard let bridge else { return }
        if isSyncingSession { return }
        isSyncingSession = true
        defer { isSyncingSession = false }

        do {
            let (res, trace) = try await bridge.latestSession(bodyId: selectedBodyId, sessionDir: sessionDir, mode: "live_usb")
            let isNewSession = res.found && res.sessionId != liveSnapshot.latestSyncedSession?.sessionId
            if !silentIfNotFound || isNewSession {
                appendLog(trace)
            }
            applySyncedLiveSession(res, silentIfNotFound: silentIfNotFound, source: source)
        } catch {
            if !silentIfNotFound {
                captureError(error, target: .stepper)
            }
        }
    }

    public func handleAppDidBecomeActive() async {
        guard !offlineMockCamera, activeLiveSession == nil else { return }
        let preferredSource: SessionResultSource = preparedLiveCommandPath != nil ? .liveTerminal : .liveInApp
        await syncLatestCameraSession(silentIfNotFound: true, source: preferredSource)
    }

    public func openPreparedLiveCommand() {
        guard let path = preparedLiveCommandPath, !path.isEmpty else { return }
        openLiveCommandInTerminalIfAllowed(path)
    }

    public func selectMP4File(_ url: URL) async {
        ingestRootURL = nil
        ingestResult = nil
        ingestError = nil
        selectedIngestedClipId = nil

        selectedMP4URL = url
        selectedProxyClipPaths = [url.path]
        gyroDiagResult = nil
        gyroDiagError = nil
        if let autoXML = StudioBridge.autoDetectSidecarXML(for: url) {
            selectedXMLURL = autoXML
        } else {
            selectedXMLURL = nil
        }
        await inspectCurrentClip()
        await runGyroDiagnosticForCurrentClip()
    }

    public func selectBatchClip(_ clip: IngestedClipItem) {
        selectedIngestedClipId = clip.id
        selectedMP4URL = URL(fileURLWithPath: clip.file)
        if let sidecar = clip.sidecarXml, !sidecar.isEmpty {
            selectedXMLURL = URL(fileURLWithPath: sidecar)
        } else {
            selectedXMLURL = StudioBridge.autoDetectSidecarXML(for: URL(fileURLWithPath: clip.file))
        }
        clipResult = nil
        clipError = nil
        gyroDiagResult = nil
        gyroDiagError = nil
    }

    public func openClipsFromURLs(_ urls: [URL]) async {
        guard let first = urls.first else { return }
        var isDir: ObjCBool = false
        if FileManager.default.fileExists(atPath: first.path, isDirectory: &isDir), isDir.boolValue {
            ingestRootURL = first
            selectedMP4URL = nil
            selectedXMLURL = nil
            clipResult = nil
            clipError = nil
            gyroDiagResult = nil
            gyroDiagError = nil
            selectedIngestedClipId = nil
            await runBatchIngest()
            return
        }

        let ext = first.pathExtension.lowercased()
        if ext == "xml" {
            await selectXMLFile(first)
        } else {
            await selectMP4File(first)
        }
    }

    public func clearClipsWorkspace() {
        selectedMP4URL = nil
        selectedXMLURL = nil
        clipResult = nil
        clipError = nil
        gyroDiagResult = nil
        gyroDiagError = nil
        ingestRootURL = nil
        ingestResult = nil
        ingestError = nil
        selectedIngestedClipId = nil
        selectedProxyClipPaths = []
    }

    public func selectXMLFile(_ url: URL?) async {
        selectedXMLURL = url
        gyroDiagResult = nil
        gyroDiagError = nil
        if selectedMP4URL != nil {
            await inspectCurrentClip()
            await runGyroDiagnosticForCurrentClip()
        }
    }

    public func inspectCurrentClip() async {
        guard let bridge, let mp4URL = selectedMP4URL else { return }
        clipError = nil
        isCheckingClip = true
        defer { isCheckingClip = false }

        do {
            let (res, trace) = try await bridge.checkClip(
                mp4URL: mp4URL,
                xmlURL: selectedXMLURL,
                expect: clipExpectMode
            )
            appendLog(trace)
            clipResult = res
        } catch {
            if let (decoded, trace) = StudioBridge.decodeStructuredFailureReport(ClipCheckResult.self, from: error) {
                appendLog(trace)
                clipResult = decoded
                clipError = nil
            } else {
                clipResult = nil
                captureError(error, target: .clip)
            }
        }
    }

    public func runGyroDiagnosticForCurrentClip() async {
        guard let bridge, let mp4URL = selectedMP4URL else { return }
        gyroDiagError = nil
        isRunningGyroDiag = true
        defer { isRunningGyroDiag = false }

        do {
            let (res, trace) = try await bridge.gyroDiagnose(
                mp4URL: mp4URL,
                xmlURL: selectedXMLURL,
                bodyId: selectedBodyId,
                expect: clipExpectMode
            )
            appendLog(trace)
            gyroDiagResult = res
        } catch {
            gyroDiagResult = nil
            if let bridgeError = error as? StudioBridgeError,
               case let .cliFailed(_, _, trace) = bridgeError {
                appendLog(trace)
            }
            gyroDiagError = error.localizedDescription
        }
    }

    public func runBatchIngest() async {
        guard let bridge, let rootDir = ingestRootURL else { return }
        ingestError = nil
        isIngestingBatch = true
        defer { isIngestingBatch = false }

        do {
            let (res, trace) = try await bridge.ingestBatch(
                rootDir: rootDir,
                expect: ingestExpectMode,
                bodyId: selectedBodyId,
                recursive: ingestRecursive
            )
            appendLog(trace)
            applyBatchIngestResult(res)
        } catch {
            if let (decoded, trace) = StudioBridge.decodeStructuredFailureReport(BatchIngestResult.self, from: error) {
                appendLog(trace)
                applyBatchIngestResult(decoded)
                ingestError = nil
            } else {
                ingestResult = nil
                if let bridgeError = error as? StudioBridgeError,
                   case let .cliFailed(_, _, trace) = bridgeError {
                    appendLog(trace)
                }
                ingestError = error.localizedDescription
            }
        }
    }

    private func applyBatchIngestResult(_ res: BatchIngestResult) {
        ingestResult = res
        selectedProxyClipPaths = Set(res.clips.filter(\.ok).map(\.file))
        if let existingId = selectedIngestedClipId,
           let matched = res.clips.first(where: { $0.id == existingId }) {
            selectBatchClip(matched)
        } else if let first = res.clips.first {
            selectBatchClip(first)
        } else {
            selectedIngestedClipId = nil
        }
    }

    public func generateProxiesForSelectedClips() async {
        guard let bridge, let outDir = proxyOutDirURL else { return }
        let inputURLs = selectedProxyClipPaths.sorted().map { URL(fileURLWithPath: $0) }
        guard !inputURLs.isEmpty else { return }

        proxyError = nil
        isGeneratingProxies = true
        defer { isGeneratingProxies = false }

        do {
            let (res, trace) = try await bridge.generateProxies(
                inputs: inputURLs,
                outDir: outDir,
                aspect: proxyAspect,
                resolution: proxyResolution,
                codec: proxyCodec,
                preserveGyroSidecar: proxyPreserveSidecar,
                dryRun: proxyDryRun
            )
            appendLog(trace)
            proxyResult = res
        } catch {
            proxyResult = nil
            if let bridgeError = error as? StudioBridgeError,
               case let .cliFailed(_, _, trace) = bridgeError {
                appendLog(trace)
            }
            proxyError = error.localizedDescription
        }
    }

    public func loadGyroflowPresets() async {
        guard let bridge else { return }
        gyroPresetError = nil
        isLoadingGyroPresets = true
        defer { isLoadingGyroPresets = false }

        do {
            let (res, trace) = try await bridge.listGyroflowPresets()
            appendLog(trace)
            gyroPresetList = res
        } catch {
            gyroPresetError = error.localizedDescription
        }
    }

    public func installGyroflowPresets(targetDir: URL? = nil) async {
        guard let bridge else { return }
        gyroPresetError = nil
        isInstallingGyroPresets = true
        defer { isInstallingGyroPresets = false }

        do {
            let (res, trace) = try await bridge.installGyroflowPresets(targetDir: targetDir)
            appendLog(trace)
            gyroPresetInstallResult = res
        } catch {
            if let bridgeError = error as? StudioBridgeError,
               case let .cliFailed(_, _, trace) = bridgeError {
                appendLog(trace)
            }
            gyroPresetError = error.localizedDescription
        }
    }

    public func buildFieldTestReport() async {
        guard let bridge else { return }
        reportError = nil
        copiedReportConfirmation = false
        isBuildingReport = true
        defer { isBuildingReport = false }

        do {
            let (res, trace) = try await bridge.buildReport(
                bodyId: selectedBodyId,
                clipsDir: reportClipsFolderURL,
                sessionDir: sessionDir,
                mediaCard: reportMediaCard,
                lens: reportLens,
                ambientC: reportAmbientC,
                soakMinutes: reportSoakMinutes,
                thermalResult: reportThermalResult,
                reactivationSeconds: reportReactivationSeconds,
                afDesqueezeNotes: reportAfDesqueezeNotes,
                notes: reportNotes
            )
            appendLog(trace)
            reportResult = res
        } catch {
            reportResult = nil
            if let bridgeError = error as? StudioBridgeError,
               case let .cliFailed(_, _, trace) = bridgeError {
                appendLog(trace)
            }
            reportError = error.localizedDescription
        }
    }

    public func copyReportMarkdownToClipboard() {
        guard let md = reportResult?.markdownPreview, !md.isEmpty else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(md, forType: .string)
        copiedReportConfirmation = true
    }

    public func revealReportFolderInFinder() {
        guard let dirPath = reportResult?.reportDir, !dirPath.isEmpty else { return }
        NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: dirPath)
    }

    public func applyPackPreset(_ preset: PackPreset) {
        let desired: [String]
        switch preset {
        case .safeDaily:
            desired = ["mp4_3x2", "screen_3x2"]
        case .cinemaFull, .reliabilityAudit:
            desired = ["mp4_3x2", "screen_3x2", "hdmi32", "high_bitrate", "xavc_si"]
        }
        var next = Set<String>()
        for packId in desired {
            if packId == "fx3_playback" { continue }
            if selectedBody == nil || selectedBody?.packs[packId] != nil {
                next.insert(packId)
            }
        }
        selectedPacks = next
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
        hasInterruptedLiveSession = false
        liveLeftBehindWarning = false
        stepperError = nil
    }

    private func defaultDisplayName(for bodyId: String) -> String {
        switch bodyId {
        case "a7s3_501": return "a7S III 5.01"
        case "fx3_702": return "FX3 7.02"
        default: return "ZV-E1 2.02"
        }
    }

    private func estimateStepsPreview(for action: LiveCommandAction, packs: [String]) -> [String] {
        switch action {
        case .preflight, .dump:
            return ["DUMP (Read-Only)"]
        case .apply:
            guard let body = selectedBody else {
                return ["L13", "L5", "L16", "V19", "S16", "C19"]
            }
            var ordered: [String] = []
            var seen = Set<String>()
            let allPackIds = ["core_open_gate"] + packs.filter { $0 != "core_open_gate" }
            for pid in allPackIds {
                guard let pack = body.packs[pid] else { continue }
                for step in pack.applySteps where !seen.contains(step) {
                    seen.insert(step)
                    ordered.append(step)
                }
            }
            return ordered.isEmpty ? ["L13", "L5", "L16"] : ordered
        case .putback:
            guard let body = selectedBody else {
                return ["C20", "S17", "V20", "L17", "L6", "L14"]
            }
            var ordered: [String] = []
            var seen = Set<String>()
            let reversePackIds = Self.modularPackOrder.reversed() + ["core_open_gate"]
            for pid in reversePackIds {
                guard let pack = body.packs[pid] else { continue }
                for step in pack.putbackSteps where !seen.contains(step) {
                    seen.insert(step)
                    ordered.append(step)
                }
            }
            return ordered.isEmpty ? ["L17", "L6", "L14"] : ordered
        }
    }

    private func resetBodySpecificSetupConfirmations() {
        checkedFirmwareVersion = false
        checkedMovie24pSettings = false
        batteryPulled10s = false
        cameraInStillsMode = false
        isSetupBannerDismissed = false
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
            lastResultSource: lastResultSource,
            hasInterruptedSession: hasInterruptedLiveSession,
            leftBehindWarning: liveLeftBehindWarning
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
        hasInterruptedLiveSession = snap.hasInterruptedSession
        liveLeftBehindWarning = snap.leftBehindWarning
    }

    private func recordPreparedLiveCommand(_ prep: PrepareLiveCommandResult, actionLabel: String) {
        let fileName = URL(fileURLWithPath: prep.commandFile).lastPathComponent
        let terminalDisabled = ProcessInfo.processInfo.environment["OPENGATE_NO_TERMINAL_OPEN"] == "1"
        let status: String
        if terminalDisabled {
            status = "Prepared Terminal fallback command for \(actionLabel) (\(fileName)) — auto-open suppressed."
        } else {
            status = "Opened Terminal fallback for \(actionLabel) (\(fileName)). Complete prompts there, then return here or click Sync Latest Camera Session."
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

    private func applySyncedLiveSession(
        _ res: LatestSessionResult,
        silentIfNotFound: Bool,
        source: SessionResultSource
    ) {
        liveSnapshot.latestSyncedSession = res

        guard res.found else {
            if !silentIfNotFound {
                let bodyLabel = selectedBody?.displayName ?? selectedBodyId
                liveSnapshot.liveStatusBanner = "No camera session recorded yet for \(bodyLabel). Click Run Read-Only Preflight to begin."
                if !offlineMockCamera {
                    latestSyncedSession = res
                    liveStatusBanner = liveSnapshot.liveStatusBanner
                }
            }
            return
        }

        if let mode = res.mode, mode != "live_usb" {
            return
        }

        let sessionLabel = res.sessionId ?? "latest"
        let normalizedKind = (res.kind ?? "").lowercased()

        switch normalizedKind {
        case "putback":
            let stockOk = res.ok && res.ready && res.verified != false && res.state == "stock"
            liveSnapshot.putbackResult = PutbackResult(
                ok: stockOk,
                stepsRun: res.stepsRun,
                state: res.state,
                bodyId: res.bodyId
            )
            if stockOk {
                liveSnapshot.applyResult = nil
                liveSnapshot.preflightResult = nil
            }
            liveSnapshot.lastResultSource = source
            liveSnapshot.liveStatusBanner = "Synced Live Put Back session (\(sessionLabel)): state = \(res.state)"

        case "apply", "closing_dump":
            let applyOk = res.ok && res.ready && res.verified != false && res.state == "applied"
            liveSnapshot.applyResult = applyOk ? ApplyResult(
                ok: true,
                stepsRun: res.stepsRun,
                closingDumpVerdict: res.verdict,
                activePacks: res.activePacks,
                bodyId: res.bodyId
            ) : nil
            liveSnapshot.putbackResult = nil
            liveSnapshot.lastResultSource = source
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
            liveSnapshot.lastResultSource = source
            let kindLabel = normalizedKind == "dump" ? "Dump" : "Preflight"
            liveSnapshot.liveStatusBanner = "Synced Live \(kindLabel) session (\(sessionLabel)): \(res.verdict)"
        }

        stepperError = nil
        if res.ok && res.ready && res.verified != false {
            if let syncedId = res.sessionId, syncedId != liveSnapshot.latestSyncedSession?.sessionId || activeLiveSession == nil {
                // Only clear interrupted warning on a verified recovery preflight/dump/putback/apply
                // when not currently in an active failed session.
                if activeLiveSession?.phase != .failed {
                    liveSnapshot.hasInterruptedSession = false
                    liveSnapshot.leftBehindWarning = false
                }
            }
        } else {
            liveSnapshot.hasInterruptedSession = true
        }
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
