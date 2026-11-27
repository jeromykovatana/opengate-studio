import Foundation

public enum DeliveryAspect: String, CaseIterable, Identifiable, Codable, Sendable {
    case aspect16x9 = "16:9"
    case aspect1x1 = "1:1"
    case aspect9x16 = "9:16"
    case aspect239 = "2.39:1"

    public var id: String { rawValue }

    public var displayLabel: String {
        switch self {
        case .aspect16x9: return "16:9 Widescreen"
        case .aspect1x1: return "1:1 Square"
        case .aspect9x16: return "9:16 Vertical"
        case .aspect239: return "2.39:1 Scope"
        }
    }

    public var ratio: Double {
        switch self {
        case .aspect16x9: return 16.0 / 9.0
        case .aspect1x1: return 1.0
        case .aspect9x16: return 9.0 / 16.0
        case .aspect239: return 2.39
        }
    }
}

public enum ProxyAspectOption: String, CaseIterable, Identifiable, Codable, Sendable {
    case ratio3x2 = "3:2"
    case ratio16x9 = "16:9"
    case ratio1x1 = "1:1"
    case ratio9x16 = "9:16"
    case ratio239 = "2.39:1"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .ratio3x2: return "3:2 Open Gate (Full Frame + XML)"
        case .ratio16x9: return "16:9 Delivery Crop"
        case .ratio1x1: return "1:1 Social Square"
        case .ratio9x16: return "9:16 Vertical Reels"
        case .ratio239: return "2.39:1 Scope Crop"
        }
    }
}

public enum ProxyResolutionOption: String, CaseIterable, Identifiable, Codable, Sendable {
    case res720p = "720p"
    case res1080p = "1080p"
    case res2160p = "2160p"

    public var id: String { rawValue }
}

public enum ProxyCodecOption: String, CaseIterable, Identifiable, Codable, Sendable {
    case h264 = "h264"
    case hevc = "hevc"
    case prores = "prores"
    case proresLT = "prores_lt"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .h264: return "H.264 (.mp4)"
        case .hevc: return "H.265 / HEVC (.mp4)"
        case .prores: return "ProRes Proxy (.mov)"
        case .proresLT: return "ProRes LT (.mov)"
        }
    }
}

public struct NormalizedRect: Codable, Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }
}

public struct SafeAreaRect: Codable, Equatable, Sendable {
    public let scale: Double
    public let width: Int
    public let height: Int
    public let x: Int
    public let y: Int
    public let normRect: NormalizedRect

    private enum CodingKeys: String, CodingKey {
        case scale
        case width
        case height
        case x
        case y
        case normRect = "norm_rect"
    }

    public init(scale: Double, width: Int, height: Int, x: Int, y: Int, normRect: NormalizedRect) {
        self.scale = scale
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.normRect = normRect
    }
}

public struct DeliveryCropSpec: Codable, Equatable, Identifiable, Sendable {
    public let aspect: String
    public let label: String
    public let width: Int
    public let height: Int
    public let x: Int
    public let y: Int
    public let normRect: NormalizedRect
    public let ffmpegCrop: String
    public let actionSafe: SafeAreaRect?
    public let titleSafe: SafeAreaRect?

    public var id: String { aspect }

    private enum CodingKeys: String, CodingKey {
        case aspect
        case label
        case width
        case height
        case x
        case y
        case normRect = "norm_rect"
        case ffmpegCrop = "ffmpeg_crop"
        case actionSafe = "action_safe"
        case titleSafe = "title_safe"
    }

    public init(
        aspect: String,
        label: String,
        width: Int,
        height: Int,
        x: Int,
        y: Int,
        normRect: NormalizedRect,
        ffmpegCrop: String,
        actionSafe: SafeAreaRect? = nil,
        titleSafe: SafeAreaRect? = nil
    ) {
        self.aspect = aspect
        self.label = label
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.normRect = normRect
        self.ffmpegCrop = ffmpegCrop
        self.actionSafe = actionSafe
        self.titleSafe = titleSafe
    }
}

public enum DeliveryCropCalculator {
    private static func roundEven(_ value: Double, maxVal: Int) -> Int {
        let rounded = Int(value.rounded())
        var even = rounded - (rounded % 2)
        if even < 2 { even = 2 }
        let maxEven = maxVal - (maxVal % 2)
        return min(even, maxEven >= 2 ? maxEven : maxVal)
    }

    private static func safeRect(
        width: Int,
        height: Int,
        x: Int,
        y: Int,
        scale: Double,
        srcW: Int,
        srcH: Int
    ) -> SafeAreaRect {
        let sw = roundEven(Double(width) * scale, maxVal: width)
        let sh = roundEven(Double(height) * scale, maxVal: height)
        let sx = x + (width - sw) / 2
        let sy = y + (height - sh) / 2
        return SafeAreaRect(
            scale: scale,
            width: sw,
            height: sh,
            x: sx,
            y: sy,
            normRect: NormalizedRect(
                x: Double(sx) / Double(srcW),
                y: Double(sy) / Double(srcH),
                width: Double(sw) / Double(srcW),
                height: Double(sh) / Double(srcH)
            )
        )
    }

    public static func compute(width: Int, height: Int) -> [DeliveryCropSpec] {
        guard width >= 2, height >= 2 else { return [] }
        let srcAR = Double(width) / Double(height)

        return DeliveryAspect.allCases.map { aspect in
            let cropW: Int
            let cropH: Int
            if srcAR >= aspect.ratio {
                cropH = height - (height % 2)
                cropW = roundEven(Double(cropH) * aspect.ratio, maxVal: width)
            } else {
                cropW = width - (width % 2)
                cropH = roundEven(Double(cropW) / aspect.ratio, maxVal: height)
            }
            let x = (width - cropW) / 2
            let y = (height - cropH) / 2
            let norm = NormalizedRect(
                x: Double(x) / Double(width),
                y: Double(y) / Double(height),
                width: Double(cropW) / Double(width),
                height: Double(cropH) / Double(height)
            )
            return DeliveryCropSpec(
                aspect: aspect.rawValue,
                label: aspect.displayLabel,
                width: cropW,
                height: cropH,
                x: x,
                y: y,
                normRect: norm,
                ffmpegCrop: "crop=\(cropW):\(cropH):\(x):\(y)",
                actionSafe: safeRect(width: cropW, height: cropH, x: x, y: y, scale: 0.90, srcW: width, srcH: height),
                titleSafe: safeRect(width: cropW, height: cropH, x: x, y: y, scale: 0.80, srcW: width, srcH: height)
            )
        }
    }
}

public enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let b = try? container.decode(Bool.self) {
            self = .bool(b)
        } else if let d = try? container.decode(Double.self) {
            self = .number(d)
        } else if let s = try? container.decode(String.self) {
            self = .string(s)
        } else if let a = try? container.decode([JSONValue].self) {
            self = .array(a)
        } else if let o = try? container.decode([String: JSONValue].self) {
            self = .object(o)
        } else {
            self = .null
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let s): try container.encode(s)
        case .number(let n): try container.encode(n)
        case .bool(let b): try container.encode(b)
        case .array(let a): try container.encode(a)
        case .object(let o): try container.encode(o)
        case .null: try container.encodeNil()
        }
    }

    public var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    public var boolValue: Bool? {
        if case .bool(let b) = self { return b }
        return nil
    }

    public var doubleValue: Double? {
        if case .number(let n) = self { return n }
        return nil
    }

    public var objectValue: [String: JSONValue]? {
        if case .object(let o) = self { return o }
        return nil
    }

    public var arrayValue: [JSONValue]? {
        if case .array(let a) = self { return a }
        return nil
    }

    public var displayString: String {
        switch self {
        case .string(let s): return s
        case .bool(let b): return b ? "Yes" : "No"
        case .number(let n):
            if n.rounded() == n { return String(Int(n)) }
            return String(format: "%.3f", n)
        case .array(let a):
            return a.map(\.displayString).joined(separator: ", ")
        case .object(let o):
            return o.keys.sorted().map { "\($0): \(o[$0]?.displayString ?? "")" }.joined(separator: "; ")
        case .null: return "—"
        }
    }
}

public struct GyroDiagnosticResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let readyForGyroflow: Bool
    public let readyForCatalyst: Bool
    public let bodyId: String?
    public let file: String?
    public let failureCategory: String
    public let summary: String
    public let checks: JSONValue?
    public let readoutCalibration: JSONValue?
    public let ibisGuidance: JSONValue?
    public let recommendedActions: [String]
    public let clipReport: ClipCheckResult?

    private enum CodingKeys: String, CodingKey {
        case ok
        case readyForGyroflow = "ready_for_gyroflow"
        case readyForCatalyst = "ready_for_catalyst"
        case bodyId = "body_id"
        case file
        case failureCategory = "failure_category"
        case summary
        case checks
        case readoutCalibration = "readout_calibration"
        case ibisGuidance = "ibis_guidance"
        case recommendedActions = "recommended_actions"
        case clipReport = "clip_report"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.ok = try c.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        self.readyForGyroflow = try c.decodeIfPresent(Bool.self, forKey: .readyForGyroflow) ?? false
        self.readyForCatalyst = try c.decodeIfPresent(Bool.self, forKey: .readyForCatalyst) ?? false
        self.bodyId = try c.decodeIfPresent(String.self, forKey: .bodyId)
        self.file = try c.decodeIfPresent(String.self, forKey: .file)
        self.failureCategory = try c.decodeIfPresent(String.self, forKey: .failureCategory) ?? "unknown"
        self.summary = try c.decodeIfPresent(String.self, forKey: .summary) ?? ""
        self.checks = try c.decodeIfPresent(JSONValue.self, forKey: .checks)
        self.readoutCalibration = try c.decodeIfPresent(JSONValue.self, forKey: .readoutCalibration)
        self.ibisGuidance = try c.decodeIfPresent(JSONValue.self, forKey: .ibisGuidance)
        self.recommendedActions = try c.decodeIfPresent([String].self, forKey: .recommendedActions) ?? []
        self.clipReport = try c.decodeIfPresent(ClipCheckResult.self, forKey: .clipReport)
    }

    public var readoutTimeMs: Double? {
        readoutCalibration?.objectValue?["frame_readout_time_ms"]?.doubleValue
            ?? readoutCalibration?.objectValue?["readout_time_ms"]?.doubleValue
    }

    public var evidenceLevel: String? {
        readoutCalibration?.objectValue?["evidence_level"]?.stringValue
    }

    public var checkPairs: [(key: String, passed: Bool?, detail: String)] {
        if let obj = checks?.objectValue {
            return obj.keys.sorted().map { k in
                let val = obj[k] ?? .null
                if let b = val.boolValue {
                    return (k, b, b ? "PASS" : "FAIL")
                }
                if let sub = val.objectValue {
                    let ok = sub["ok"]?.boolValue ?? sub["passed"]?.boolValue
                    let msg = sub["detail"]?.stringValue ?? sub["summary"]?.stringValue ?? val.displayString
                    return (k, ok, msg)
                }
                return (k, nil, val.displayString)
            }
        }
        if let arr = checks?.arrayValue {
            return arr.enumerated().map { idx, item in
                if let sub = item.objectValue {
                    let name = sub["title"]?.stringValue ?? sub["name"]?.stringValue ?? sub["id"]?.stringValue ?? sub["check"]?.stringValue ?? "check_\(idx + 1)"
                    let ok = sub["ok"]?.boolValue ?? sub["passed"]?.boolValue
                    let msg = sub["detail"]?.stringValue ?? sub["message"]?.stringValue ?? item.displayString
                    return (name, ok, msg)
                }
                return ("check_\(idx + 1)", nil, item.displayString)
            }
        }
        return []
    }
}

public struct GyroflowPresetEntry: Codable, Equatable, Identifiable, Sendable {
    public let filename: String
    public let bodyId: String
    public let cameraModel: String
    public let dimension: String
    public let frameReadoutTimeMs: Double?
    public let evidenceLevel: String
    public let sha256: String

    public var id: String { filename }

    private enum CodingKeys: String, CodingKey {
        case filename
        case bodyId = "body_id"
        case cameraModel = "camera_model"
        case dimension
        case frameReadoutTimeMs = "frame_readout_time_ms"
        case evidenceLevel = "evidence_level"
        case sha256
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.filename = try c.decode(String.self, forKey: .filename)
        self.bodyId = try c.decodeIfPresent(String.self, forKey: .bodyId) ?? ""
        self.cameraModel = try c.decodeIfPresent(String.self, forKey: .cameraModel) ?? ""
        self.dimension = try c.decodeIfPresent(String.self, forKey: .dimension) ?? ""
        self.frameReadoutTimeMs = try c.decodeIfPresent(Double.self, forKey: .frameReadoutTimeMs)
        self.evidenceLevel = try c.decodeIfPresent(String.self, forKey: .evidenceLevel) ?? "estimated"
        self.sha256 = try c.decodeIfPresent(String.self, forKey: .sha256) ?? ""
    }
}

public struct GyroflowPresetListResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let presetDir: String
    public let presets: [GyroflowPresetEntry]

    private enum CodingKeys: String, CodingKey {
        case ok
        case presetDir = "preset_dir"
        case presets
    }
}

public struct InstallGyroflowPresetsResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let targetDir: String
    public let installedCount: Int
    public let installedFiles: [String]

    private enum CodingKeys: String, CodingKey {
        case ok
        case targetDir = "target_dir"
        case installedCount = "installed_count"
        case installedFiles = "installed_files"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.ok = try c.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        self.targetDir = try c.decodeIfPresent(String.self, forKey: .targetDir) ?? ""
        self.installedCount = try c.decodeIfPresent(Int.self, forKey: .installedCount) ?? 0
        self.installedFiles = try c.decodeIfPresent([String].self, forKey: .installedFiles) ?? []
    }
}

public struct IngestedClipItem: Codable, Equatable, Identifiable, Sendable {
    public let ok: Bool
    public let file: String
    public let filename: String
    public let relativePath: String
    public let expectedMode: String
    public let body: String
    public let sidecarXml: String?
    public let width: Int
    public let height: Int
    public let displayAspect: String
    public let codec: String
    public let codecProfileLevel: String?
    public let fps: String
    public let durationSec: Double?
    public let avgBitrateMbps: Double?
    public let cadenceConstant: Bool?
    public let vprf3x2: Bool
    public let xml3x2: Bool?
    public let rtmdGyroPresent: Bool
    public let rtmdSamples: Int
    public let readyForGyroflow: Bool
    public let readyForCatalyst: Bool
    public let failureCategory: String
    public let gyroSummary: String
    public let recommendedActions: [String]
    public let deliveryCrops: [String: DeliveryCropSpec]?
    public let warnings: [String]
    public let issues: [String]

    public var id: String { file }

    private enum CodingKeys: String, CodingKey {
        case ok
        case file
        case filename
        case relativePath = "relative_path"
        case expectedMode = "expected_mode"
        case body
        case sidecarXml = "sidecar_xml"
        case width
        case height
        case displayAspect = "display_aspect"
        case codec
        case codecProfileLevel = "codec_profile_level"
        case fps
        case durationSec = "duration_sec"
        case avgBitrateMbps = "avg_bitrate_mbps"
        case cadenceConstant = "cadence_constant"
        case vprf3x2 = "vprf_3x2"
        case xml3x2 = "xml_3x2"
        case rtmdGyroPresent = "rtmd_gyro_present"
        case rtmdSamples = "rtmd_samples"
        case readyForGyroflow = "ready_for_gyroflow"
        case readyForCatalyst = "ready_for_catalyst"
        case failureCategory = "failure_category"
        case gyroSummary = "gyro_summary"
        case recommendedActions = "recommended_actions"
        case deliveryCrops = "delivery_crops"
        case warnings
        case issues
    }
}

public struct BatchIngestResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let allClipsOk: Bool
    public let rootDir: String
    public let recursive: Bool
    public let expect: String
    public let clipsScanned: Int
    public let clipsPassed: Int
    public let clipsFailed: Int
    public let gyroflowReadyCount: Int
    public let clips: [IngestedClipItem]

    private enum CodingKeys: String, CodingKey {
        case ok
        case allClipsOk = "all_clips_ok"
        case rootDir = "root_dir"
        case recursive
        case expect
        case clipsScanned = "clips_scanned"
        case clipsPassed = "clips_passed"
        case clipsFailed = "clips_failed"
        case gyroflowReadyCount = "gyroflow_ready_count"
        case clips
    }
}

public struct ProxyRelinkVerification: Codable, Equatable, Sendable {
    public let fpsMatch: Bool?
    public let durationDeltaSec: Double?
    public let timecodeMatch: Bool?
    public let audioChannelsMatch: Bool?
    public let originalSha256Unchanged: Bool
    public let relinkOk: Bool?

    private enum CodingKeys: String, CodingKey {
        case fpsMatch = "fps_match"
        case durationDeltaSec = "duration_delta_sec"
        case timecodeMatch = "timecode_match"
        case audioChannelsMatch = "audio_channels_match"
        case originalSha256Unchanged = "original_sha256_unchanged"
        case relinkOk = "relink_ok"
    }
}

public struct GeneratedProxyItem: Codable, Equatable, Identifiable, Sendable {
    public let ok: Bool
    public let dryRun: Bool
    public let inputFile: String
    public let outputFile: String
    public let targetWidth: Int?
    public let targetHeight: Int?
    public let aspect: String?
    public let resolution: String?
    public let codec: String?
    public let sourceFps: String?
    public let proxyFps: String?
    public let sourceTimecode: String?
    public let proxyTimecode: String?
    public let sourceAudioChannels: Int?
    public let proxyAudioChannels: Int?
    public let originalSha256: String?
    public let sidecarSource: String?
    public let sidecarCopied: Bool?
    public let sidecarOutput: String?
    public let sidecarNote: String?
    public let rtmdPreservedInProxy: Bool
    public let relinkToOriginalForGyro: Bool
    public let relinkVerification: ProxyRelinkVerification
    public let ffmpegCmd: [String]?
    public let error: String?

    public var id: String { inputFile + "->" + outputFile }

    private enum CodingKeys: String, CodingKey {
        case ok
        case dryRun = "dry_run"
        case inputFile = "input_file"
        case outputFile = "output_file"
        case targetWidth = "target_width"
        case targetHeight = "target_height"
        case aspect
        case resolution
        case codec
        case sourceFps = "source_fps"
        case proxyFps = "proxy_fps"
        case sourceTimecode = "source_timecode"
        case proxyTimecode = "proxy_timecode"
        case sourceAudioChannels = "source_audio_channels"
        case proxyAudioChannels = "proxy_audio_channels"
        case originalSha256 = "original_sha256"
        case sidecarSource = "sidecar_source"
        case sidecarCopied = "sidecar_copied"
        case sidecarOutput = "sidecar_output"
        case sidecarNote = "sidecar_note"
        case rtmdPreservedInProxy = "rtmd_preserved_in_proxy"
        case relinkToOriginalForGyro = "relink_to_original_for_gyro"
        case relinkVerification = "relink_verification"
        case ffmpegCmd = "ffmpeg_cmd"
        case error
    }
}

public struct ProxyGenerationResult: Codable, Equatable, Sendable {
    public let ok: Bool
    public let dryRun: Bool
    public let outDir: String
    public let manifestPath: String
    public let aspect: String
    public let resolution: String
    public let codec: String
    public let targetWidth: Int
    public let targetHeight: Int
    public let generatedUtc: String
    public let totalInputs: Int
    public let succeededCount: Int
    public let failedCount: Int
    public let proxies: [GeneratedProxyItem]

    private enum CodingKeys: String, CodingKey {
        case ok
        case dryRun = "dry_run"
        case outDir = "out_dir"
        case manifestPath = "manifest_path"
        case aspect
        case resolution
        case codec
        case targetWidth = "target_width"
        case targetHeight = "target_height"
        case generatedUtc = "generated_utc"
        case totalInputs = "total_inputs"
        case succeededCount = "succeeded_count"
        case failedCount = "failed_count"
        case proxies
    }
}
