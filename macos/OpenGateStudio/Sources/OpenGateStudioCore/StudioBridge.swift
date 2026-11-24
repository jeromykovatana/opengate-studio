import Foundation

public enum MockCameraState: String, CaseIterable, Identifiable, Sendable {
    case stock = "stock"
    case mixedPowerswitch = "mixed_powerswitch"
    case applied = "applied"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .stock:
            return "stock"
        case .mixedPowerswitch:
            return "mixed_powerswitch"
        case .applied:
            return "applied"
        }
    }
}

public struct CommandTrace: Sendable, Identifiable, Equatable {
    public let id: UUID
    public let timestamp: Date
    public let command: String
    public let exitCode: Int32
    public let stdout: String
    public let stderr: String

    public init(
        id: UUID = UUID(),
        timestamp: Date = Date(),
        command: String,
        exitCode: Int32,
        stdout: String,
        stderr: String
    ) {
        self.id = id
        self.timestamp = timestamp
        self.command = command
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
    }
}

public enum StudioBridgeError: LocalizedError, Sendable {
    case repoRootNotFound(searched: [String])
    case processLaunchFailed(String)
    case cliFailed(exitCode: Int32, message: String, trace: CommandTrace)
    case invalidJSON(context: String, rawOutput: String, underlyingDescription: String)

    public var errorDescription: String? {
        switch self {
        case .repoRootNotFound(let searched):
            return "Could not locate sony-opengate-studio repository root (expected cli/studio_cli.py and kits/). Searched: \(searched.joined(separator: ", "))"
        case .processLaunchFailed(let detail):
            return "Failed to launch python3 process: \(detail)"
        case .cliFailed(let exitCode, let message, _):
            return "studio_cli.py exited with status \(exitCode): \(message)"
        case .invalidJSON(let context, let rawOutput, let underlyingDescription):
            let preview = String(rawOutput.prefix(400))
            return "Failed to decode JSON for \(context): \(underlyingDescription). Output: \(preview)"
        }
    }
}

private struct CLIErrorPayload: Decodable {
    let error: String?
    let message: String?
    let verdict: String?
    let detail: String?
}

public final class StudioBridge: @unchecked Sendable {
    public let repoRoot: URL
    public let sessionDirectory: URL
    private let pythonExecutable: String

    public init(
        repoRoot: URL? = nil,
        sessionDirectory: URL? = nil,
        pythonExecutable: String = "/usr/bin/env"
    ) throws {
        if let repoRoot {
            guard Self.isValidRepoRoot(repoRoot) else {
                throw StudioBridgeError.repoRootNotFound(searched: [repoRoot.path])
            }
            self.repoRoot = repoRoot
        } else {
            self.repoRoot = try Self.discoverRepoRoot()
        }

        if let sessionDirectory {
            self.sessionDirectory = sessionDirectory
        } else {
            let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
                ?? URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
            self.sessionDirectory = appSupport
                .appendingPathComponent("OpenGateStudio", isDirectory: true)
                .appendingPathComponent("sessions", isDirectory: true)
        }

        self.pythonExecutable = pythonExecutable
    }

    public static func isValidRepoRoot(_ url: URL) -> Bool {
        let fm = FileManager.default
        let cliPath = url.appendingPathComponent("cli/studio_cli.py").path
        let kitsPath = url.appendingPathComponent("kits").path
        var isDir: ObjCBool = false
        return fm.fileExists(atPath: cliPath) && fm.fileExists(atPath: kitsPath, isDirectory: &isDir) && isDir.boolValue
    }

    public static func discoverRepoRoot(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        filePath: String = #filePath
    ) throws -> URL {
        var searched: [String] = []

        if let envRoot = environment["OPENGATE_STUDIO_ROOT"], !envRoot.isEmpty {
            let url = URL(fileURLWithPath: envRoot, isDirectory: true)
            searched.append(url.path)
            if isValidRepoRoot(url) {
                return url
            }
        }

        var candidateSeeds: [URL] = []
        if let resourceURL = Bundle.main.resourceURL {
            candidateSeeds.append(resourceURL)
            candidateSeeds.append(resourceURL.appendingPathComponent("studio", isDirectory: true))
        }
        candidateSeeds.append(Bundle.main.bundleURL)
        candidateSeeds.append(URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true))
        candidateSeeds.append(URL(fileURLWithPath: filePath, isDirectory: false).deletingLastPathComponent())

        for seed in candidateSeeds {
            var current = seed.standardizedFileURL
            for _ in 0..<10 {
                searched.append(current.path)
                if isValidRepoRoot(current) {
                    return current
                }
                let parent = current.deletingLastPathComponent()
                if parent.path == current.path {
                    break
                }
                current = parent
            }
        }

        throw StudioBridgeError.repoRootNotFound(searched: Array(Set(searched)).sorted())
    }

    public var cliScriptURL: URL {
        repoRoot.appendingPathComponent("cli/studio_cli.py")
    }

    public func listBodies() async throws -> (result: ListBodiesResult, trace: CommandTrace) {
        try await runAndDecode(ListBodiesResult.self, context: "list-bodies", args: ["list-bodies", "--json"])
    }

    public func verifyPins(bodyId: String? = nil) async throws -> (result: VerifyPinsResult, trace: CommandTrace) {
        var args = ["verify-pins"]
        if let bodyId, !bodyId.isEmpty {
            args.append(contentsOf: ["--body", bodyId])
        }
        args.append("--json")
        return try await runAndDecode(VerifyPinsResult.self, context: "verify-pins", args: args)
    }

    public func preflight(
        bodyId: String,
        mockCamera: Bool = true,
        mockState: MockCameraState = .stock,
        sessionDir: URL? = nil
    ) async throws -> (result: PreflightResult, trace: CommandTrace) {
        let effectiveSessionDir = sessionDir ?? sessionDirectory
        try FileManager.default.createDirectory(at: effectiveSessionDir, withIntermediateDirectories: true)

        var args = ["preflight", "--body", bodyId]
        if mockCamera {
            args.append(contentsOf: ["--mock-camera", "--mock-state", mockState.rawValue])
        } else {
            args.append("--live-usb")
        }
        args.append(contentsOf: ["--session-dir", effectiveSessionDir.path, "--json"])
        return try await runAndDecode(PreflightResult.self, context: "preflight", args: args)
    }

    public func apply(
        bodyId: String,
        packs: [String],
        mockCamera: Bool = true,
        sessionDir: URL? = nil
    ) async throws -> (result: ApplyResult, trace: CommandTrace) {
        let effectiveSessionDir = sessionDir ?? sessionDirectory
        try FileManager.default.createDirectory(at: effectiveSessionDir, withIntermediateDirectories: true)

        var args = ["apply", "--body", bodyId, "--packs", packs.joined(separator: ",")]
        if mockCamera {
            args.append("--mock-camera")
        } else {
            args.append("--live-usb")
        }
        args.append(contentsOf: ["--session-dir", effectiveSessionDir.path, "--json"])
        return try await runAndDecode(ApplyResult.self, context: "apply", args: args)
    }

    public func putback(
        bodyId: String,
        packs: [String]? = nil,
        mockCamera: Bool = true,
        sessionDir: URL? = nil
    ) async throws -> (result: PutbackResult, trace: CommandTrace) {
        let effectiveSessionDir = sessionDir ?? sessionDirectory
        try FileManager.default.createDirectory(at: effectiveSessionDir, withIntermediateDirectories: true)

        var args = ["putback", "--body", bodyId]
        if let packs, !packs.isEmpty {
            args.append(contentsOf: ["--packs", packs.joined(separator: ",")])
        }
        if mockCamera {
            args.append("--mock-camera")
        } else {
            args.append("--live-usb")
        }
        args.append(contentsOf: ["--session-dir", effectiveSessionDir.path, "--json"])
        return try await runAndDecode(PutbackResult.self, context: "putback", args: args)
    }

    public func checkClip(
        mp4URL: URL,
        xmlURL: URL? = nil
    ) async throws -> (result: ClipCheckResult, trace: CommandTrace) {
        var args = ["check-clip", mp4URL.path]
        if let xmlURL {
            args.append(contentsOf: ["--xml", xmlURL.path])
        }
        args.append("--json")
        return try await runAndDecode(ClipCheckResult.self, context: "check-clip", args: args)
    }

    /// Auto-detects a matching Sony sidecar XML next to an MP4 clip (e.g., C0001.MP4 -> C0001M01.XML).
    public static func autoDetectSidecarXML(for mp4URL: URL) -> URL? {
        let fm = FileManager.default
        let dir = mp4URL.deletingLastPathComponent()
        let stem = mp4URL.deletingPathExtension().lastPathComponent
        let candidates = [
            dir.appendingPathComponent("\(stem)M01.XML"),
            dir.appendingPathComponent("\(stem)M01.xml"),
            dir.appendingPathComponent("\(stem).XML"),
            dir.appendingPathComponent("\(stem).xml")
        ]
        return candidates.first(where: { fm.fileExists(atPath: $0.path) })
    }

    private func runAndDecode<T: Decodable & Sendable>(
        _ type: T.Type,
        context: String,
        args: [String]
    ) async throws -> (result: T, trace: CommandTrace) {
        let trace = try await runCLI(args: args)
        let stdoutData = Data(trace.stdout.utf8)

        if trace.exitCode != 0 {
            let message = Self.extractErrorMessage(stdout: trace.stdout, stderr: trace.stderr)
            throw StudioBridgeError.cliFailed(exitCode: trace.exitCode, message: message, trace: trace)
        }

        do {
            let decoded = try JSONDecoder().decode(T.self, from: stdoutData)
            return (decoded, trace)
        } catch {
            throw StudioBridgeError.invalidJSON(
                context: context,
                rawOutput: trace.stdout,
                underlyingDescription: error.localizedDescription
            )
        }
    }

    private func runCLI(args: [String]) async throws -> CommandTrace {
        let cliPath = cliScriptURL.path
        let rootURL = repoRoot
        let executable = pythonExecutable

        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: executable)
                var fullArgs = ["python3", cliPath]
                fullArgs.append(contentsOf: args)
                process.arguments = fullArgs
                process.currentDirectoryURL = rootURL

                var env = ProcessInfo.processInfo.environment
                env["PYTHONUNBUFFERED"] = "1"
                env["OPENGATE_STUDIO_ROOT"] = rootURL.path
                process.environment = env

                let stdoutPipe = Pipe()
                let stderrPipe = Pipe()
                process.standardOutput = stdoutPipe
                process.standardError = stderrPipe

                do {
                    try process.run()
                } catch {
                    continuation.resume(throwing: StudioBridgeError.processLaunchFailed(error.localizedDescription))
                    return
                }

                let group = DispatchGroup()
                var stdoutData = Data()
                var stderrData = Data()

                group.enter()
                DispatchQueue.global(qos: .utility).async {
                    stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
                    group.leave()
                }

                group.enter()
                DispatchQueue.global(qos: .utility).async {
                    stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                    group.leave()
                }

                process.waitUntilExit()
                group.wait()

                let stdoutStr = String(data: stdoutData, encoding: .utf8) ?? ""
                let stderrStr = String(data: stderrData, encoding: .utf8) ?? ""
                let cmdDisplay = ([executable] + fullArgs).joined(separator: " ")

                let trace = CommandTrace(
                    command: cmdDisplay,
                    exitCode: process.terminationStatus,
                    stdout: stdoutStr,
                    stderr: stderrStr
                )
                continuation.resume(returning: trace)
            }
        }
    }

    private static func extractErrorMessage(stdout: String, stderr: String) -> String {
        for raw in [stdout, stderr] {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            if let data = trimmed.data(using: .utf8),
               let payload = try? JSONDecoder().decode(CLIErrorPayload.self, from: data) {
                if let msg = payload.error ?? payload.message ?? payload.detail ?? payload.verdict, !msg.isEmpty {
                    return msg
                }
            }
        }
        let combined = [stderr.trimmingCharacters(in: .whitespacesAndNewlines),
                        stdout.trimmingCharacters(in: .whitespacesAndNewlines)]
            .filter { !$0.isEmpty }
            .joined(separator: " | ")
        return combined.isEmpty ? "Unknown CLI error" : combined
    }
}
