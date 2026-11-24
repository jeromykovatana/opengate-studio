import AppKit
import Foundation
import OpenGateStudioCore
import SwiftUI

public enum StudioTab: String, CaseIterable, Identifiable {
    case packsAndSafety = "Feature Packs & 5-Gate Apply"
    case clipInspector = "Clip, XML & Gyro Inspector"

    public var id: String { rawValue }
}

@MainActor
public final class AppState: ObservableObject {
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
                resetSafetySessionResults()
            }
        }
    }
    @Published public var mockState: MockCameraState = .stock {
        didSet {
            if oldValue != mockState {
                resetSafetySessionResults()
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

    public static let modularPackOrder: [String] = [
        "mp4_3x2",
        "screen_3x2",
        "hdmi32",
        "high_bitrate",
        "xavc_si"
    ]

    public init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
        self.sessionDir = appSupport
            .appendingPathComponent("OpenGateStudio", isDirectory: true)
            .appendingPathComponent("sessions", isDirectory: true)

        do {
            self.bridge = try StudioBridge(sessionDirectory: sessionDir)
        } catch {
            self.bridge = nil
            self.startupError = error.localizedDescription
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
        return !preflight.ready && (preflight.state == "not_ready" || mockState == .mixedPowerswitch)
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
        applyResult = nil
        putbackResult = nil
        isRunningPreflight = true
        defer { isRunningPreflight = false }

        do {
            let (res, trace) = try await bridge.preflight(
                bodyId: selectedBodyId,
                mockCamera: offlineMockCamera,
                mockState: mockState,
                sessionDir: sessionDir
            )
            appendLog(trace)
            preflightResult = res
        } catch {
            preflightResult = nil
            captureError(error, target: .stepper)
        }
    }

    public func applySelectedPacks() async {
        guard let bridge, isApplyUnlocked else { return }
        stepperError = nil
        putbackResult = nil
        isApplying = true
        defer { isApplying = false }

        let orderedPacks = Self.modularPackOrder.filter { selectedPacks.contains($0) }
        let packsToSend = orderedPacks.isEmpty ? ["core_open_gate"] : orderedPacks
        do {
            let (res, trace) = try await bridge.apply(
                bodyId: selectedBodyId,
                packs: packsToSend,
                mockCamera: offlineMockCamera,
                sessionDir: sessionDir
            )
            appendLog(trace)
            applyResult = res
        } catch {
            captureError(error, target: .stepper)
        }
    }

    public func putBackToStock() async {
        guard let bridge else { return }
        stepperError = nil
        isPuttingBack = true
        defer { isPuttingBack = false }

        do {
            let (res, trace) = try await bridge.putback(
                bodyId: selectedBodyId,
                packs: nil,
                mockCamera: offlineMockCamera,
                sessionDir: sessionDir
            )
            appendLog(trace)
            putbackResult = res
            applyResult = nil
            preflightResult = nil
        } catch {
            captureError(error, target: .stepper)
        }
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
        preflightResult = nil
        applyResult = nil
        putbackResult = nil
        stepperError = nil
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
