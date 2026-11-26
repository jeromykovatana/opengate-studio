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
            return "Could not locate opengate-studio repository root (expected cli/studio_cli.py and kits/). Searched: \(searched.joined(separator: ", "))"
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

    public var liveInAppScriptURL: URL {
        repoRoot.appendingPathComponent("macos/run_live_inapp.sh")
    }

    public static let defaultAdminPrompt =
        "OpenGate Studio needs administrator access once to release macOS USB Mass Storage from your Sony camera (volatile RAM only)."

    /// POSIX single-quoting safe against shell expansion, spaces, quotes, and special characters.
    public static func shellSingleQuote(_ value: String) -> String {
        let sanitized = value.replacingOccurrences(of: "\0", with: "")
        return "'" + sanitized.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    /// Escapes a string for safe embedding inside an AppleScript double-quoted literal.
    public static func escapeAppleScriptString(_ value: String) -> String {
        var out = ""
        out.reserveCapacity(value.count)
        for ch in value {
            switch ch {
            case "\\":
                out.append("\\\\")
            case "\"":
                out.append("\\\"")
            case "\r":
                out.append("\\r")
            case "\n":
                out.append("\\n")
            case "\t":
                out.append("\\t")
            case "\0":
                continue
            default:
                out.append(ch)
            }
        }
        return out
    }

    /// Builds a single-quoted `/bin/bash <scriptPath> <arguments...>` shell command string.
    public static func buildLiveInAppShellCommand(scriptPath: String, arguments: [String]) -> String {
        let parts = ["/bin/bash", scriptPath] + arguments
        return parts.map(shellSingleQuote).joined(separator: " ")
    }

    /// Builds an injection-safe AppleScript `do shell script ... with administrator privileges` snippet.
    public static func buildAdminAppleScript(
        shellCommand: String,
        prompt: String = defaultAdminPrompt
    ) -> String {
        let escapedCmd = escapeAppleScriptString(shellCommand)
        let escapedPrompt = escapeAppleScriptString(prompt)
        return "do shell script \"\(escapedCmd)\" with prompt \"\(escapedPrompt)\" with administrator privileges"
    }

    /// Detects whether `/usr/bin/osascript` exited because the user dismissed the admin prompt.
    public static func isOsascriptUserCancelled(exitCode: Int32, stderr: String) -> Bool {
        guard exitCode != 0 else { return false }
        let lower = stderr.lowercased()
        return lower.contains("-128") || lower.contains("user canceled") || lower.contains("user cancelled")
    }

    /// Starts a native in-app Live USB run via `macos/run_live_inapp.sh`, streaming JSONL events
    /// and log chunks in real time while supporting safe between-step cancellation.
    public func startLiveInAppRun(
        action: LiveCommandAction,
        bodyId: String,
        firmwareConfirmed: String,
        confirmVolatileRam: Bool,
        packs: [String]? = nil,
        sessionDir: URL? = nil,
        dryRunSimulate: Bool = false,
        noMovieSession: Bool = false,
        onEvent: @escaping @Sendable (LiveRunEvent) -> Void,
        onLogChunk: @escaping @Sendable (String) -> Void
    ) -> (handle: LiveRunHandle, task: Task<LiveRunResult, Error>) {
        let effectiveSessionDir = sessionDir ?? sessionDirectory
        let runDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("opengate_live_\(UUID().uuidString)", isDirectory: true)
        let eventsFile = runDir.appendingPathComponent("events.jsonl")
        let logFile = runDir.appendingPathComponent("output.log")
        let cancelFile = runDir.appendingPathComponent("cancel.flag")

        try? FileManager.default.createDirectory(at: runDir, withIntermediateDirectories: true)

        let handle = LiveRunHandle(
            runDirectory: runDir,
            cancelFile: cancelFile,
            eventsFile: eventsFile,
            logFile: logFile
        )

        let envDryRun = ProcessInfo.processInfo.environment["OPENGATE_LIVE_INAPP_DRY_RUN"] == "1"
        let useDryRun = dryRunSimulate || envDryRun
        let scriptURL = liveInAppScriptURL
        let rootURL = repoRoot
        let uid = String(getuid())
        let gid = String(getgid())

        var scriptArgs: [String] = [
            "--owner-uid", uid,
            "--owner-gid", gid,
            action.rawValue,
            "--body", bodyId,
            "--session-dir", effectiveSessionDir.path,
            "--firmware-confirmed", firmwareConfirmed,
            "--events-file", eventsFile.path,
            "--log-file", logFile.path,
            "--cancel-file", cancelFile.path
        ]
        if confirmVolatileRam {
            scriptArgs.append("--confirm-volatile-ram")
        }
        if let packs, !packs.isEmpty {
            scriptArgs.append(contentsOf: ["--packs", packs.joined(separator: ",")])
        }
        if noMovieSession {
            scriptArgs.append("--no-movie-session")
        }
        if useDryRun {
            scriptArgs.append(contentsOf: ["--dry-run", "--simulate-events"])
        }

        let finalScriptArgs = scriptArgs

        let task = Task.detached(priority: .userInitiated) { () throws -> LiveRunResult in
            try FileManager.default.createDirectory(at: effectiveSessionDir, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: runDir, withIntermediateDirectories: true)

            guard FileManager.default.fileExists(atPath: scriptURL.path) else {
                throw StudioBridgeError.processLaunchFailed("Missing live runner script: \(scriptURL.path)")
            }

            let process = Process()
            process.currentDirectoryURL = rootURL

            if useDryRun {
                process.executableURL = URL(fileURLWithPath: "/bin/bash")
                process.arguments = [scriptURL.path] + finalScriptArgs
                var env = ProcessInfo.processInfo.environment
                env["PYTHONUNBUFFERED"] = "1"
                env["OPENGATE_STUDIO_ROOT"] = rootURL.path
                process.environment = env
            } else {
                let shellCommand = Self.buildLiveInAppShellCommand(
                    scriptPath: scriptURL.path,
                    arguments: finalScriptArgs
                )
                let appleScript = Self.buildAdminAppleScript(shellCommand: shellCommand)
                process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
                process.arguments = ["-e", appleScript]
            }

            let stdoutPipe = Pipe()
            let stderrPipe = Pipe()
            process.standardOutput = stdoutPipe
            process.standardError = stderrPipe

            do {
                try process.run()
            } catch {
                throw StudioBridgeError.processLaunchFailed(error.localizedDescription)
            }

            let pipeGroup = DispatchGroup()
            let stdoutBox = LockedDataBox()
            let stderrBox = LockedDataBox()

            pipeGroup.enter()
            DispatchQueue.global(qos: .utility).async {
                stdoutBox.set(stdoutPipe.fileHandleForReading.readDataToEndOfFile())
                pipeGroup.leave()
            }

            pipeGroup.enter()
            DispatchQueue.global(qos: .utility).async {
                stderrBox.set(stderrPipe.fileHandleForReading.readDataToEndOfFile())
                pipeGroup.leave()
            }

            let exitTask = Task.detached(priority: .userInitiated) { () -> Int32 in
                await withCheckedContinuation { (cont: CheckedContinuation<Int32, Never>) in
                    DispatchQueue.global(qos: .userInitiated).async {
                        process.waitUntilExit()
                        pipeGroup.wait()
                        cont.resume(returning: process.terminationStatus)
                    }
                }
            }

            let tailer = LiveStreamTailer(eventsFile: eventsFile, logFile: logFile)

            while process.isRunning {
                tailer.drain(final: false, onEvent: onEvent, onLogChunk: onLogChunk)
                if Task.isCancelled {
                    handle.cancel()
                }
                await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
                    DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + .milliseconds(200)) {
                        cont.resume()
                    }
                }
            }

            let exitCode = await exitTask.value
            tailer.drain(final: true, onEvent: onEvent, onLogChunk: onLogChunk)

            let stderrStr = String(data: stderrBox.get(), encoding: .utf8) ?? ""
            let osascriptCancelled = !useDryRun && Self.isOsascriptUserCancelled(exitCode: exitCode, stderr: stderrStr)
            let eventCancelled = tailer.events.contains(where: { $0.type == "cancelled" })
            let wasUserCancelled = osascriptCancelled || eventCancelled || exitCode == 130

            return LiveRunResult(
                exitCode: exitCode,
                wasUserCancelled: wasUserCancelled,
                events: tailer.events,
                logOutput: tailer.logOutput,
                eventsFile: eventsFile,
                logFile: logFile,
                stderrOutput: stderrStr
            )
        }

        return (handle, task)
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
        xmlURL: URL? = nil,
        expect: String = "open-gate"
    ) async throws -> (result: ClipCheckResult, trace: CommandTrace) {
        var args = ["check-clip", mp4URL.path, "--expect", expect]
        if let xmlURL {
            args.append(contentsOf: ["--xml", xmlURL.path])
        }
        args.append("--json")
        return try await runAndDecode(ClipCheckResult.self, context: "check-clip", args: args)
    }

    public func buildReport(
        bodyId: String,
        clipsDir: URL? = nil,
        outDir: URL? = nil,
        sessionDir: URL? = nil,
        mediaCard: String = "",
        lens: String = "",
        ambientC: String = "",
        soakMinutes: String = "",
        thermalResult: String = "",
        reactivationSeconds: String = "",
        afDesqueezeNotes: String = "",
        gyroApp: String = "",
        editorApp: String = "",
        notes: String = ""
    ) async throws -> (result: BuildReportResult, trace: CommandTrace) {
        let effectiveSessionDir = sessionDir ?? sessionDirectory
        try FileManager.default.createDirectory(at: effectiveSessionDir, withIntermediateDirectories: true)

        var args = [
            "build-report",
            "--body", bodyId,
            "--session-dir", effectiveSessionDir.path
        ]
        if let clipsDir {
            args.append(contentsOf: ["--clips-dir", clipsDir.path])
        }
        if let outDir {
            args.append(contentsOf: ["--out-dir", outDir.path])
        }
        let optionals: [(String, String)] = [
            ("--media-card", mediaCard),
            ("--lens", lens),
            ("--ambient-c", ambientC),
            ("--soak-minutes", soakMinutes),
            ("--thermal-result", thermalResult),
            ("--reactivation-seconds", reactivationSeconds),
            ("--af-desqueeze-notes", afDesqueezeNotes),
            ("--gyro-app", gyroApp),
            ("--editor-app", editorApp),
            ("--notes", notes),
        ]
        for (flag, val) in optionals {
            let trimmed = val.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                args.append(contentsOf: [flag, trimmed])
            }
        }
        args.append("--json")
        return try await runAndDecode(BuildReportResult.self, context: "build-report", args: args)
    }

    public func latestSession(
        bodyId: String,
        sessionDir: URL? = nil
    ) async throws -> (result: LatestSessionResult, trace: CommandTrace) {
        let effectiveSessionDir = sessionDir ?? sessionDirectory
        try FileManager.default.createDirectory(at: effectiveSessionDir, withIntermediateDirectories: true)

        let args = [
            "latest-session",
            "--body", bodyId,
            "--session-dir", effectiveSessionDir.path,
            "--json"
        ]
        return try await runAndDecode(LatestSessionResult.self, context: "latest-session", args: args)
    }

    public func prepareLiveCommand(
        action: LiveCommandAction,
        bodyId: String,
        packs: [String]? = nil,
        sessionDir: URL? = nil
    ) async throws -> (result: PrepareLiveCommandResult, trace: CommandTrace) {
        let effectiveSessionDir = sessionDir ?? sessionDirectory
        try FileManager.default.createDirectory(at: effectiveSessionDir, withIntermediateDirectories: true)

        var args = [
            "prepare-live-command",
            "--action", action.rawValue,
            "--body", bodyId
        ]
        if let packs, !packs.isEmpty {
            args.append(contentsOf: ["--packs", packs.joined(separator: ",")])
        }
        args.append(contentsOf: ["--session-dir", effectiveSessionDir.path, "--json"])
        return try await runAndDecode(PrepareLiveCommandResult.self, context: "prepare-live-command", args: args)
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

private final class LockedDataBox: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()

    func set(_ newData: Data) {
        lock.lock()
        data = newData
        lock.unlock()
    }

    func get() -> Data {
        lock.lock()
        defer { lock.unlock() }
        return data
    }
}

private final class LiveStreamTailer {
    private let eventsFile: URL
    private let logFile: URL
    private let decoder = JSONDecoder()

    private var eventsOffset: UInt64 = 0
    private var pendingEventBytes = Data()

    private var logOffset: UInt64 = 0
    private var pendingLogBytes = Data()

    private(set) var events: [LiveRunEvent] = []
    private(set) var logOutput: String = ""

    init(eventsFile: URL, logFile: URL) {
        self.eventsFile = eventsFile
        self.logFile = logFile
    }

    func drain(
        final: Bool,
        onEvent: @Sendable (LiveRunEvent) -> Void,
        onLogChunk: @Sendable (String) -> Void
    ) {
        drainEvents(final: final, onEvent: onEvent)
        drainLog(final: final, onLogChunk: onLogChunk)
    }

    private func drainEvents(final: Bool, onEvent: @Sendable (LiveRunEvent) -> Void) {
        if let chunk = readNewBytes(from: eventsFile, offset: &eventsOffset), !chunk.isEmpty {
            pendingEventBytes.append(chunk)
        }

        let newline: UInt8 = 0x0A
        while let nlIndex = pendingEventBytes.firstIndex(of: newline) {
            let lineData = pendingEventBytes.subdata(in: pendingEventBytes.startIndex..<nlIndex)
            let nextIndex = pendingEventBytes.index(after: nlIndex)
            pendingEventBytes.removeSubrange(pendingEventBytes.startIndex..<nextIndex)
            decodeEventLine(lineData, onEvent: onEvent)
        }

        if final && !pendingEventBytes.isEmpty {
            let remaining = pendingEventBytes
            pendingEventBytes.removeAll(keepingCapacity: false)
            decodeEventLine(remaining, onEvent: onEvent)
        }
    }

    private func decodeEventLine(_ rawLine: Data, onEvent: @Sendable (LiveRunEvent) -> Void) {
        guard var lineStr = String(data: rawLine, encoding: .utf8) else { return }
        lineStr = lineStr.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !lineStr.isEmpty else { return }
        if lineStr.hasPrefix("@OG_EVENT ") {
            lineStr = String(lineStr.dropFirst("@OG_EVENT ".count)).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        guard let jsonData = lineStr.data(using: .utf8),
              let event = try? decoder.decode(LiveRunEvent.self, from: jsonData) else {
            return
        }
        events.append(event)
        onEvent(event)
    }

    private func drainLog(final: Bool, onLogChunk: @Sendable (String) -> Void) {
        if let chunk = readNewBytes(from: logFile, offset: &logOffset), !chunk.isEmpty {
            pendingLogBytes.append(chunk)
        }
        guard !pendingLogBytes.isEmpty else { return }

        if let text = String(data: pendingLogBytes, encoding: .utf8) {
            pendingLogBytes.removeAll(keepingCapacity: true)
            if !text.isEmpty {
                logOutput.append(text)
                onLogChunk(text)
            }
            return
        }

        if final {
            let text = String(decoding: pendingLogBytes, as: UTF8.self)
            pendingLogBytes.removeAll(keepingCapacity: false)
            if !text.isEmpty {
                logOutput.append(text)
                onLogChunk(text)
            }
            return
        }

        // Trim up to 3 trailing bytes in case a multi-byte UTF-8 char straddles the read boundary
        for trimCount in 1...min(3, pendingLogBytes.count) {
            let prefixEnd = pendingLogBytes.index(pendingLogBytes.endIndex, offsetBy: -trimCount)
            let prefix = pendingLogBytes[pendingLogBytes.startIndex..<prefixEnd]
            if let text = String(data: prefix, encoding: .utf8) {
                pendingLogBytes = Data(pendingLogBytes[prefixEnd..<pendingLogBytes.endIndex])
                if !text.isEmpty {
                    logOutput.append(text)
                    onLogChunk(text)
                }
                return
            }
        }
    }

    private func readNewBytes(from fileURL: URL, offset: inout UInt64) -> Data? {
        guard FileManager.default.fileExists(atPath: fileURL.path),
              let fh = try? FileHandle(forReadingFrom: fileURL) else {
            return nil
        }
        defer { try? fh.close() }
        do {
            try fh.seek(toOffset: offset)
            if let chunk = try fh.readToEnd(), !chunk.isEmpty {
                offset += UInt64(chunk.count)
                return chunk
            }
        } catch {
            return nil
        }
        return nil
    }
}
