import Foundation

/// Flexible step execution entry that decodes either a step ID string (e.g. "V19")
/// or a structured step result object from `studio_cli.py`.
public struct ExecutedStep: Codable, Hashable, Sendable, Identifiable {
    public let step: String
    public let status: String?
    public let detail: String?

    public var id: String {
        if let status, !status.isEmpty {
            return "\(step):\(status)"
        }
        return step
    }

    public init(step: String, status: String? = nil, detail: String? = nil) {
        self.step = step
        self.status = status
        self.detail = detail
    }

    private enum CodingKeys: String, CodingKey {
        case step
        case name
        case id
        case status
        case verdict
        case summary
        case detail
        case message
    }

    public init(from decoder: Decoder) throws {
        if let single = try? decoder.singleValueContainer(),
           let str = try? single.decode(String.self) {
            self.step = str
            self.status = nil
            self.detail = nil
            return
        }
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let stepName = try container.decodeIfPresent(String.self, forKey: .step)
            ?? container.decodeIfPresent(String.self, forKey: .name)
            ?? container.decodeIfPresent(String.self, forKey: .id)
            ?? "unknown"
        let statusVal = try container.decodeIfPresent(String.self, forKey: .status)
            ?? container.decodeIfPresent(String.self, forKey: .verdict)
        let detailVal = try container.decodeIfPresent(String.self, forKey: .detail)
            ?? container.decodeIfPresent(String.self, forKey: .summary)
            ?? container.decodeIfPresent(String.self, forKey: .message)
        self.step = stepName
        self.status = statusVal
        self.detail = detailVal
    }

    public func encode(to encoder: Encoder) throws {
        if status == nil && detail == nil {
            var single = encoder.singleValueContainer()
            try single.encode(step)
        } else {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(step, forKey: .step)
            try container.encodeIfPresent(status, forKey: .status)
            try container.encodeIfPresent(detail, forKey: .detail)
        }
    }
}

public struct PackInfo: Codable, Equatable, Sendable {
    public let title: String?
    public let summary: String?
    public let description: String?
    public let required: Bool?
    public let defaultEnabled: Bool?
    public let applySteps: [String]
    public let putbackSteps: [String]
    public let fallbackApplySteps: [String]?
    public let fallbackPutbackSteps: [String]?

    private enum CodingKeys: String, CodingKey {
        case title
        case name
        case label
        case summary
        case description
        case required
        case defaultEnabled = "default_enabled"
        case applySteps = "apply_steps"
        case putbackSteps = "putback_steps"
        case fallbackApplySteps = "fallback_apply_steps"
        case fallbackPutbackSteps = "fallback_putback_steps"
    }

    public init(
        title: String? = nil,
        summary: String? = nil,
        description: String? = nil,
        required: Bool? = nil,
        defaultEnabled: Bool? = nil,
        applySteps: [String] = [],
        putbackSteps: [String] = [],
        fallbackApplySteps: [String]? = nil,
        fallbackPutbackSteps: [String]? = nil
    ) {
        self.title = title
        self.summary = summary
        self.description = description
        self.required = required
        self.defaultEnabled = defaultEnabled
        self.applySteps = applySteps
        self.putbackSteps = putbackSteps
        self.fallbackApplySteps = fallbackApplySteps
        self.fallbackPutbackSteps = fallbackPutbackSteps
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.title = try c.decodeIfPresent(String.self, forKey: .title)
            ?? c.decodeIfPresent(String.self, forKey: .name)
            ?? c.decodeIfPresent(String.self, forKey: .label)
        self.summary = try c.decodeIfPresent(String.self, forKey: .summary)
        self.description = try c.decodeIfPresent(String.self, forKey: .description)
        self.required = try c.decodeIfPresent(Bool.self, forKey: .required)
        self.defaultEnabled = try c.decodeIfPresent(Bool.self, forKey: .defaultEnabled)
        self.applySteps = try c.decodeIfPresent([String].self, forKey: .applySteps) ?? []
        self.putbackSteps = try c.decodeIfPresent([String].self, forKey: .putbackSteps) ?? []
        self.fallbackApplySteps = try c.decodeIfPresent([String].self, forKey: .fallbackApplySteps)
        self.fallbackPutbackSteps = try c.decodeIfPresent([String].self, forKey: .fallbackPutbackSteps)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(title, forKey: .title)
        try c.encodeIfPresent(summary, forKey: .summary)
        try c.encodeIfPresent(description, forKey: .description)
        try c.encodeIfPresent(required, forKey: .required)
        try c.encodeIfPresent(defaultEnabled, forKey: .defaultEnabled)
        try c.encode(applySteps, forKey: .applySteps)
        try c.encode(putbackSteps, forKey: .putbackSteps)
        try c.encodeIfPresent(fallbackApplySteps, forKey: .fallbackApplySteps)
        try c.encodeIfPresent(fallbackPutbackSteps, forKey: .fallbackPutbackSteps)
    }
}

public struct BodyInfo: Codable, Identifiable, Equatable, Sendable {
    public let bodyId: String
    public let camera: String
    public let firmware: String
    public let versionTxt: String?
    public let pinsOk: Bool
    public let packs: [String: PackInfo]

    public var id: String { bodyId }

    public var displayName: String {
        let shortCam: String
        if camera.contains("ZV-E1") {
            shortCam = "ZV-E1"
        } else if camera.contains("a7S III") || camera.contains("7SM3") {
            shortCam = "a7S III"
        } else if camera.contains("FX3") {
            shortCam = "FX3"
        } else {
            shortCam = camera
        }
        return "\(shortCam) \(firmware)"
    }

    private enum CodingKeys: String, CodingKey {
        case bodyId = "body_id"
        case camera
        case firmware
        case versionTxt = "version_txt"
        case pinsOk = "pins_ok"
        case packs
    }

    public init(
        bodyId: String,
        camera: String,
        firmware: String,
        versionTxt: String? = nil,
        pinsOk: Bool,
        packs: [String: PackInfo]
    ) {
        self.bodyId = bodyId
        self.camera = camera
        self.firmware = firmware
        self.versionTxt = versionTxt
        self.pinsOk = pinsOk
        self.packs = packs
    }
}

public struct ListBodiesResult: Codable, Equatable, Sendable {
    public let bodies: [BodyInfo]
}

public struct BodyPinVerification: Codable, Equatable, Sendable {
    public let ok: Bool
    public let checkedFiles: Int?
    public let issues: [String]?

    private enum CodingKeys: String, CodingKey {
        case ok
        case checkedFiles = "checked_files"
        case issues
    }

    public init(ok: Bool, checkedFiles: Int? = nil, issues: [String]? = nil) {
        self.ok = ok
        self.checkedFiles = checkedFiles
        self.issues = issues
    }

    public init(from decoder: Decoder) throws {
        if let single = try? decoder.singleValueContainer(),
           let boolVal = try? single.decode(Bool.self) {
            self.ok = boolVal
            self.checkedFiles = nil
            self.issues = nil
            return
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.ok = try c.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        self.checkedFiles = try c.decodeIfPresent(Int.self, forKey: .checkedFiles)
        self.issues = try c.decodeIfPresent([String].self, forKey: .issues)
    }
}

public struct VerifyPinsResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let checkedFiles: Int
    public let bodies: [String: BodyPinVerification]

    private enum CodingKeys: String, CodingKey {
        case ok
        case checkedFiles = "checked_files"
        case bodies
    }

    public init(ok: Bool, checkedFiles: Int, bodies: [String: BodyPinVerification]) {
        self.ok = ok
        self.checkedFiles = checkedFiles
        self.bodies = bodies
    }
}

public struct PreflightResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let ready: Bool
    public let state: String
    public let verdict: String
    public let sessionId: String
    public let bodyId: String?
    public let warning: String?

    private enum CodingKeys: String, CodingKey {
        case ok
        case ready
        case state
        case verdict
        case sessionId = "session_id"
        case bodyId = "body_id"
        case warning
    }

    public init(
        ok: Bool,
        ready: Bool,
        state: String,
        verdict: String,
        sessionId: String,
        bodyId: String? = nil,
        warning: String? = nil
    ) {
        self.ok = ok
        self.ready = ready
        self.state = state
        self.verdict = verdict
        self.sessionId = sessionId
        self.bodyId = bodyId
        self.warning = warning
    }
}

public struct ApplyResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let stepsRun: [ExecutedStep]
    public let closingDumpVerdict: String
    public let activePacks: [String]
    public let bodyId: String?

    private enum CodingKeys: String, CodingKey {
        case ok
        case stepsRun = "steps_run"
        case closingDumpVerdict = "closing_dump_verdict"
        case activePacks = "active_packs"
        case bodyId = "body_id"
    }

    public init(
        ok: Bool,
        stepsRun: [ExecutedStep],
        closingDumpVerdict: String,
        activePacks: [String],
        bodyId: String? = nil
    ) {
        self.ok = ok
        self.stepsRun = stepsRun
        self.closingDumpVerdict = closingDumpVerdict
        self.activePacks = activePacks
        self.bodyId = bodyId
    }
}

public struct PutbackResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let stepsRun: [ExecutedStep]
    public let state: String
    public let bodyId: String?

    private enum CodingKeys: String, CodingKey {
        case ok
        case stepsRun = "steps_run"
        case state
        case bodyId = "body_id"
    }

    public init(ok: Bool, stepsRun: [ExecutedStep], state: String, bodyId: String? = nil) {
        self.ok = ok
        self.stepsRun = stepsRun
        self.state = state
        self.bodyId = bodyId
    }
}

public struct ClipCheckResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let width: Int
    public let height: Int
    public let displayAspect: String
    public let codec: String
    public let fps: String
    public let vprf3x2: Bool
    public let xml3x2: Bool?
    public let rtmdGyroPresent: Bool
    public let rtmdSamples: Int
    public let issues: [String]
    public let durationSec: Double?
    public let frameCount: Int?
    public let avgBitrateMbps: Double?
    public let cadenceConstant: Bool?
    public let codecProfileLevel: String?
    public let avcL51MbWarning: Bool?
    public let warnings: [String]?

    private enum CodingKeys: String, CodingKey {
        case ok
        case width
        case height
        case displayAspect = "display_aspect"
        case codec
        case fps
        case vprf3x2 = "vprf_3x2"
        case xml3x2 = "xml_3x2"
        case rtmdGyroPresent = "rtmd_gyro_present"
        case rtmdSamples = "rtmd_samples"
        case issues
        case durationSec = "duration_sec"
        case frameCount = "frame_count"
        case avgBitrateMbps = "avg_bitrate_mbps"
        case cadenceConstant = "cadence_constant"
        case codecProfileLevel = "codec_profile_level"
        case avcL51MbWarning = "avc_l51_mb_warning"
        case warnings
    }

    public init(
        ok: Bool,
        width: Int,
        height: Int,
        displayAspect: String,
        codec: String,
        fps: String,
        vprf3x2: Bool,
        xml3x2: Bool?,
        rtmdGyroPresent: Bool,
        rtmdSamples: Int,
        issues: [String],
        durationSec: Double? = nil,
        frameCount: Int? = nil,
        avgBitrateMbps: Double? = nil,
        cadenceConstant: Bool? = nil,
        codecProfileLevel: String? = nil,
        avcL51MbWarning: Bool? = nil,
        warnings: [String]? = nil
    ) {
        self.ok = ok
        self.width = width
        self.height = height
        self.displayAspect = displayAspect
        self.codec = codec
        self.fps = fps
        self.vprf3x2 = vprf3x2
        self.xml3x2 = xml3x2
        self.rtmdGyroPresent = rtmdGyroPresent
        self.rtmdSamples = rtmdSamples
        self.issues = issues
        self.durationSec = durationSec
        self.frameCount = frameCount
        self.avgBitrateMbps = avgBitrateMbps
        self.cadenceConstant = cadenceConstant
        self.codecProfileLevel = codecProfileLevel
        self.avcL51MbWarning = avcL51MbWarning
        self.warnings = warnings
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.ok = try c.decode(Bool.self, forKey: .ok)
        self.width = try c.decode(Int.self, forKey: .width)
        self.height = try c.decode(Int.self, forKey: .height)
        self.displayAspect = try c.decode(String.self, forKey: .displayAspect)
        self.codec = try c.decode(String.self, forKey: .codec)
        self.fps = try c.decode(String.self, forKey: .fps)
        self.vprf3x2 = try c.decode(Bool.self, forKey: .vprf3x2)
        self.xml3x2 = try c.decodeIfPresent(Bool.self, forKey: .xml3x2)
        self.rtmdGyroPresent = try c.decode(Bool.self, forKey: .rtmdGyroPresent)
        self.rtmdSamples = try c.decode(Int.self, forKey: .rtmdSamples)
        self.issues = try c.decodeIfPresent([String].self, forKey: .issues) ?? []
        self.durationSec = try c.decodeIfPresent(Double.self, forKey: .durationSec)
        self.frameCount = try c.decodeIfPresent(Int.self, forKey: .frameCount)
        self.avgBitrateMbps = try c.decodeIfPresent(Double.self, forKey: .avgBitrateMbps)
        self.cadenceConstant = try c.decodeIfPresent(Bool.self, forKey: .cadenceConstant)
        self.codecProfileLevel = try c.decodeIfPresent(String.self, forKey: .codecProfileLevel)
        self.avcL51MbWarning = try c.decodeIfPresent(Bool.self, forKey: .avcL51MbWarning)
        self.warnings = try c.decodeIfPresent([String].self, forKey: .warnings)
    }
}

public struct BuildReportResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let bodyId: String
    public let reportDir: String
    public let markdownPath: String
    public let jsonPath: String
    public let manifestPath: String
    public let clipsScanned: Int
    public let clipsPassed: Int
    public let clipsFailed: Int
    public let markdownPreview: String

    private enum CodingKeys: String, CodingKey {
        case ok
        case bodyId = "body_id"
        case reportDir = "report_dir"
        case markdownPath = "markdown_path"
        case jsonPath = "json_path"
        case manifestPath = "manifest_path"
        case clipsScanned = "clips_scanned"
        case clipsPassed = "clips_passed"
        case clipsFailed = "clips_failed"
        case markdownPreview = "markdown_preview"
    }

    public init(
        ok: Bool,
        bodyId: String,
        reportDir: String,
        markdownPath: String,
        jsonPath: String,
        manifestPath: String,
        clipsScanned: Int,
        clipsPassed: Int,
        clipsFailed: Int,
        markdownPreview: String
    ) {
        self.ok = ok
        self.bodyId = bodyId
        self.reportDir = reportDir
        self.markdownPath = markdownPath
        self.jsonPath = jsonPath
        self.manifestPath = manifestPath
        self.clipsScanned = clipsScanned
        self.clipsPassed = clipsPassed
        self.clipsFailed = clipsFailed
        self.markdownPreview = markdownPreview
    }
}

public enum LiveCommandAction: String, CaseIterable, Codable, Identifiable, Sendable {
    case preflight
    case dump
    case apply
    case putback
    case expressApply = "express-apply"
    case expressPutback = "express-putback"

    public var id: String { rawValue }
}

public struct DetectedUsbCameraResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let detected: Bool
    public let bodyId: String?
    public let usbProductName: String?
    public let usbMode: String?
    public let isFx3aBlocked: Bool
    public let warning: String?

    private enum CodingKeys: String, CodingKey {
        case ok
        case detected
        case bodyId = "body_id"
        case usbProductName = "usb_product_name"
        case usbMode = "usb_mode"
        case isFx3aBlocked = "is_fx3a_blocked"
        case warning
    }

    public init(
        ok: Bool,
        detected: Bool,
        bodyId: String? = nil,
        usbProductName: String? = nil,
        usbMode: String? = nil,
        isFx3aBlocked: Bool = false,
        warning: String? = nil
    ) {
        self.ok = ok
        self.detected = detected
        self.bodyId = bodyId
        self.usbProductName = usbProductName
        self.usbMode = usbMode
        self.isFx3aBlocked = isFx3aBlocked
        self.warning = warning
    }
}

public struct LatestSessionResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let found: Bool
    public let bodyId: String
    public let sessionId: String?
    public let kind: String?
    public let mode: String?
    public let ready: Bool
    public let verified: Bool?
    public let state: String
    public let verdict: String
    public let activePacks: [String]
    public let stepsRun: [ExecutedStep]

    private enum CodingKeys: String, CodingKey {
        case ok
        case found
        case bodyId = "body_id"
        case sessionId = "session_id"
        case kind
        case mode
        case ready
        case verified
        case state
        case verdict
        case activePacks = "active_packs"
        case stepsRun = "steps_run"
    }

    public init(
        ok: Bool,
        found: Bool,
        bodyId: String,
        sessionId: String? = nil,
        kind: String? = nil,
        mode: String? = nil,
        ready: Bool,
        verified: Bool? = nil,
        state: String,
        verdict: String,
        activePacks: [String] = [],
        stepsRun: [ExecutedStep] = []
    ) {
        self.ok = ok
        self.found = found
        self.bodyId = bodyId
        self.sessionId = sessionId
        self.kind = kind
        self.mode = mode
        self.ready = ready
        self.verified = verified
        self.state = state
        self.verdict = verdict
        self.activePacks = activePacks
        self.stepsRun = stepsRun
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.ok = try c.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        self.found = try c.decodeIfPresent(Bool.self, forKey: .found) ?? false
        self.bodyId = try c.decodeIfPresent(String.self, forKey: .bodyId) ?? ""
        self.sessionId = try c.decodeIfPresent(String.self, forKey: .sessionId)
        self.kind = try c.decodeIfPresent(String.self, forKey: .kind)
        self.mode = try c.decodeIfPresent(String.self, forKey: .mode)
        self.ready = try c.decodeIfPresent(Bool.self, forKey: .ready) ?? false
        self.verified = try c.decodeIfPresent(Bool.self, forKey: .verified)
        self.state = try c.decodeIfPresent(String.self, forKey: .state) ?? "unknown"
        self.verdict = try c.decodeIfPresent(String.self, forKey: .verdict) ?? ""
        self.activePacks = try c.decodeIfPresent([String].self, forKey: .activePacks) ?? []
        self.stepsRun = try c.decodeIfPresent([ExecutedStep].self, forKey: .stepsRun) ?? []
    }
}

public struct PrepareLiveCommandResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let action: String
    public let bodyId: String
    public let commandFile: String
    public let preview: String

    private enum CodingKeys: String, CodingKey {
        case ok
        case action
        case bodyId = "body_id"
        case commandFile = "command_file"
        case preview
    }

    public init(
        ok: Bool,
        action: String,
        bodyId: String,
        commandFile: String,
        preview: String
    ) {
        self.ok = ok
        self.action = action
        self.bodyId = bodyId
        self.commandFile = commandFile
        self.preview = preview
    }
}

public struct LivePlanStep: Codable, Equatable, Hashable, Identifiable, Sendable {
    public let id: String
    public let summary: String

    public init(id: String, summary: String) {
        self.id = id
        self.summary = summary
    }
}

public struct LiveRunEvent: Codable, Equatable, Sendable {
    public let ts: String?
    public let type: String
    public let action: String?
    public let bodyId: String?
    public let camera: String?
    public let firmware: String?
    public let steps: [LivePlanStep]?
    public let closingDump: Bool?
    public let closingKind: String?
    public let first: Bool?
    public let stepIndex: Int?
    public let totalSteps: Int?
    public let stepId: String?
    public let title: String?
    public let detail: String?
    public let summary: String?
    public let outcome: String?
    public let ok: Bool?
    public let hint: String?
    public let verdict: String?
    public let ready: Bool?
    public let verified: Bool?
    public let sessionId: String?
    public let state: String?
    public let stepsRun: [ExecutedStep]?
    public let activePacks: [String]?
    public let message: String?
    public let leftBehind: Bool?

    private enum CodingKeys: String, CodingKey {
        case ts
        case type
        case action
        case bodyId = "body_id"
        case camera
        case firmware
        case steps
        case closingDump = "closing_dump"
        case closingKind = "closing_kind"
        case first
        case stepIndex = "step_index"
        case totalSteps = "total_steps"
        case stepId = "step_id"
        case title
        case detail
        case summary
        case outcome
        case ok
        case hint
        case verdict
        case ready
        case verified
        case sessionId = "session_id"
        case state
        case stepsRun = "steps_run"
        case activePacks = "active_packs"
        case message
        case leftBehind = "left_behind"
    }

    public init(
        ts: String? = nil,
        type: String,
        action: String? = nil,
        bodyId: String? = nil,
        camera: String? = nil,
        firmware: String? = nil,
        steps: [LivePlanStep]? = nil,
        closingDump: Bool? = nil,
        closingKind: String? = nil,
        first: Bool? = nil,
        stepIndex: Int? = nil,
        totalSteps: Int? = nil,
        stepId: String? = nil,
        title: String? = nil,
        detail: String? = nil,
        summary: String? = nil,
        outcome: String? = nil,
        ok: Bool? = nil,
        hint: String? = nil,
        verdict: String? = nil,
        ready: Bool? = nil,
        verified: Bool? = nil,
        sessionId: String? = nil,
        state: String? = nil,
        stepsRun: [ExecutedStep]? = nil,
        activePacks: [String]? = nil,
        message: String? = nil,
        leftBehind: Bool? = nil
    ) {
        self.ts = ts
        self.type = type
        self.action = action
        self.bodyId = bodyId
        self.camera = camera
        self.firmware = firmware
        self.steps = steps
        self.closingDump = closingDump
        self.closingKind = closingKind
        self.first = first
        self.stepIndex = stepIndex
        self.totalSteps = totalSteps
        self.stepId = stepId
        self.title = title
        self.detail = detail
        self.summary = summary
        self.outcome = outcome
        self.ok = ok
        self.hint = hint
        self.verdict = verdict
        self.ready = ready
        self.verified = verified
        self.sessionId = sessionId
        self.state = state
        self.stepsRun = stepsRun
        self.activePacks = activePacks
        self.message = message
        self.leftBehind = leftBehind
    }
}

public final class LiveRunHandle: @unchecked Sendable {
    public let runDirectory: URL
    public let cancelFile: URL
    public let eventsFile: URL
    public let logFile: URL

    private let lock = NSLock()
    private var _isCancelRequested = false

    public var isCancelRequested: Bool {
        lock.lock()
        defer { lock.unlock() }
        return _isCancelRequested
    }

    public init(
        runDirectory: URL,
        cancelFile: URL,
        eventsFile: URL,
        logFile: URL
    ) {
        self.runDirectory = runDirectory
        self.cancelFile = cancelFile
        self.eventsFile = eventsFile
        self.logFile = logFile
    }

    /// Requests a safe cancellation by writing the cancel-file so Python stops cleanly
    /// between steps without killing a process mid-DMA-write.
    public func cancel() {
        lock.lock()
        _isCancelRequested = true
        lock.unlock()

        try? FileManager.default.createDirectory(at: runDirectory, withIntermediateDirectories: true)
        try? Data("cancel\n".utf8).write(to: cancelFile, options: .atomic)
    }
}

public struct LiveRunResult: Equatable, Sendable {
    public let exitCode: Int32
    public let wasUserCancelled: Bool
    public let events: [LiveRunEvent]
    public let logOutput: String
    public let eventsFile: URL
    public let logFile: URL
    public let stderrOutput: String

    public init(
        exitCode: Int32,
        wasUserCancelled: Bool,
        events: [LiveRunEvent],
        logOutput: String,
        eventsFile: URL,
        logFile: URL,
        stderrOutput: String = ""
    ) {
        self.exitCode = exitCode
        self.wasUserCancelled = wasUserCancelled
        self.events = events
        self.logOutput = logOutput
        self.eventsFile = eventsFile
        self.logFile = logFile
        self.stderrOutput = stderrOutput
    }

    public var completeEvent: LiveRunEvent? {
        events.last(where: { $0.type == "complete" })
    }

    public var errorEvent: LiveRunEvent? {
        events.last(where: { $0.type == "error" })
    }

    public var cancelledEvent: LiveRunEvent? {
        events.last(where: { $0.type == "cancelled" })
    }
}

public enum LiveSessionOutcome: Equatable, Sendable {
    case finished(complete: LiveRunEvent)
    case cancelled(adminAuth: Bool, message: String)
    case failed(message: String, leftBehind: Bool)
}

public enum LiveSessionOutcomeEvaluator {
    public static func evaluate(
        result: LiveRunResult,
        action: LiveCommandAction,
        actionTitle: String,
        existingFailureMessage: String?,
        existingCancelMessage: String?,
        existingLeftBehind: Bool,
        wasCancelRequestedByButton: Bool,
        isOsascriptCancelled: Bool
    ) -> LiveSessionOutcome {
        if result.wasUserCancelled || isOsascriptCancelled {
            if isOsascriptCancelled || (!wasCancelRequestedByButton && result.events.isEmpty && result.cancelledEvent == nil) {
                return .cancelled(
                    adminAuth: true,
                    message: "Administrator authorization cancelled — nothing was sent to the camera."
                )
            }
            let msg = result.cancelledEvent?.message
                ?? existingCancelMessage
                ?? "Cancelled safely before the next step."
            return .cancelled(adminAuth: false, message: msg)
        }

        if result.exitCode == 0, let complete = result.completeEvent, complete.ok == true {
            switch action {
            case .apply, .expressApply:
                if complete.ready == true && complete.verified != false && complete.state == "applied" {
                    return .finished(complete: complete)
                }
                let msg = complete.verdict ?? "Apply did not pass fail-closed closing verification."
                return .failed(message: msg, leftBehind: existingLeftBehind)

            case .putback:
                if complete.ready == true && complete.verified != false && complete.state == "stock" {
                    return .finished(complete: complete)
                }
                let msg = complete.verdict ?? "Putback did not pass closing stock verification."
                return .failed(message: msg, leftBehind: existingLeftBehind)

            case .expressPutback:
                if complete.ready == true && complete.verified == true && complete.state == "stock" {
                    return .finished(complete: complete)
                }
                let msg = complete.verdict ?? "Express putback did not pass closing stock verification."
                return .failed(message: msg, leftBehind: existingLeftBehind)

            case .preflight, .dump:
                if complete.ready != nil && complete.verified != false {
                    return .finished(complete: complete)
                }
                let msg = complete.verdict ?? "\(actionTitle) returned incomplete verification."
                return .failed(message: msg, leftBehind: existingLeftBehind)
            }
        }

        if let errEv = result.errorEvent, let msg = errEv.message, !msg.isEmpty {
            return .failed(message: msg, leftBehind: errEv.leftBehind ?? existingLeftBehind)
        }
        if let existing = existingFailureMessage, !existing.isEmpty {
            return .failed(message: existing, leftBehind: existingLeftBehind)
        }
        let trimmedStderr = result.stderrOutput.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedStderr.isEmpty {
            return .failed(message: trimmedStderr, leftBehind: existingLeftBehind)
        }
        return .failed(
            message: "\(actionTitle) exited with status \(result.exitCode). Expand Live Output Log for details.",
            leftBehind: existingLeftBehind
        )
    }
}
