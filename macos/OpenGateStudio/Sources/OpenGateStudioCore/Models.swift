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
        issues: [String]
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
    }
}

public enum LiveCommandAction: String, CaseIterable, Codable, Identifiable, Sendable {
    case preflight
    case dump
    case apply
    case putback

    public var id: String { rawValue }
}

public struct LatestSessionResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let found: Bool
    public let bodyId: String
    public let sessionId: String?
    public let kind: String?
    public let ready: Bool
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
        case ready
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
        ready: Bool,
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
        self.ready = ready
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
        self.ready = try c.decodeIfPresent(Bool.self, forKey: .ready) ?? false
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
